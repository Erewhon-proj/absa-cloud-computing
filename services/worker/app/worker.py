"""Inference worker (Tier 2, asincrono).

Consuma i task da una coda di messaggi, esegue l'inferenza ABSA sulla recensione
e salva gli aspetti estratti su PostgreSQL. È il componente che l'HPA/KEDA (o un
Auto Scaling Group) replicherà sotto carico. Implementa micro-batching per
massimizzare il throughput del modello ML.

Due backend di coda, selezionati da QUEUE_BACKEND:
  - "rabbitmq" (default): RabbitMQ via pika   -> Fase A locale (OrbStack).
  - "sqs":                Amazon SQS via boto3 -> Fase B cloud (AWS).

La logica di elaborazione (`process_batch`) è condivisa: restituisce gli handle
dei messaggi elaborati e lascia che sia il chiamante a confermarli (ack su
RabbitMQ, delete su SQS), così non dipende dal backend.
"""
import json
import logging
import os
import signal
import time

from psycopg2.extras import RealDictCursor

from .db import get_conn
from .inference import infer_batch

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("worker")

QUEUE_BACKEND = os.getenv("QUEUE_BACKEND", "rabbitmq").lower()
QUEUE_NAME = os.getenv("QUEUE_NAME", "absa.reviews")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "16"))
FLUSH_TIMEOUT = float(os.getenv("FLUSH_TIMEOUT", "2.0"))

# --- RabbitMQ (Fase A) ---
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

# --- SQS (Fase B) ---
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
# Tempo concesso per elaborare un batch prima che SQS riconsegni i messaggi (5 minuti)
SQS_VISIBILITY_TIMEOUT = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
# Secondi di attesa prima di riprovare se la lettura da SQS fallisce
SQS_ERROR_BACKOFF = int(os.getenv("SQS_ERROR_BACKOFF", "5"))

# Un handle è l'identificativo univoco del messaggio usato dalla coda per confermarlo


# Flag per lo spegnimento pulito. Diventa True quando Kubernetes chiede di fermare il pod.
_shutdown = False


def _request_shutdown(signum, _frame) -> None:
    """Intercetta il segnale SIGTERM inviato da Kubernetes quando vuole spegnere il pod.

    Invece di interrompere brutalmente il processo a metà lavoro, impostiamo solo questo flag.
    In questo modo il worker conclude il batch di recensioni che sta già elaborando,
    salva i risultati nel database ed esce in modo ordinato senza perdere dati.
    """
    global _shutdown
    _shutdown = True
    logger.info(
        "Ricevuto segnale di terminazione %d, il worker uscirà al termine del batch corrente",
        signum,
    )



def process_batch(batch: list[tuple]) -> list:
    """Elabora un gruppo di recensioni estraendole dal database ed eseguendo l'inferenza.

    Riceve una lista di coppie (identificatore del messaggio, id recensione).
    Restituisce la lista degli identificatori completati, così chi chiama la funzione
    può confermarli sulla coda corretta (ack su RabbitMQ o delete su SQS).

    Se l'inferenza fallisce, le recensioni vengono impostate sullo stato error nel database
    e i messaggi vengono comunque confermati per non bloccare la coda con dati non validi.
    Se invece il database è irraggiungibile, l'errore viene propagato per consentire
    la riconsegna automatica del messaggio.
    """
    if not batch:
        return []

    review_ids = [item[1] for item in batch]
    valid_batch: list[tuple] = []
    to_ack: list = []  # handle dei messaggi finiti, da confermare a fine batch

    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, text FROM reviews WHERE id = ANY(%s::uuid[])",
                (review_ids,),
            )
            rows = cur.fetchall()
            id_to_text = {str(row["id"]): row["text"] for row in rows}

            valid_ids = list(id_to_text.keys())
            if valid_ids:
                cur.execute(
                    "UPDATE reviews SET status = 'processing' WHERE id = ANY(%s::uuid[])",
                    (valid_ids,),
                )

        texts = []
        # Se una recensione non esiste nel database la confermiamo subito per toglierla dalla coda
        for handle, r_id in batch:
            if r_id in id_to_text:
                valid_batch.append((handle, r_id))
                texts.append(id_to_text[r_id])
            else:
                logger.warning("Recensione %s non trovata", r_id)
                to_ack.append(handle)

        if not texts:
            return to_ack

        # Inferenza in batch
        batch_aspects = infer_batch(texts)

        # Salva su DB
        valid_rids = [r_id for _, r_id in valid_batch]
        with get_conn() as conn, conn.cursor() as cur:
            # Idempotenza: rimuove aspetti pre-esistenti in caso di riconsegna.
            cur.execute(
                "DELETE FROM aspects WHERE review_id = ANY(%s::uuid[])", (valid_rids,)
            )
            # strict: se il modello restituisce meno risultati dei testi
            # inviati, zip troncherebbe in silenzio e alcune recensioni
            # finirebbero in 'done' senza aspetti. Meglio un errore.
            for (_, r_id), aspects in zip(valid_batch, batch_aspects, strict=True):
                for a in aspects:
                    cur.execute(
                        "INSERT INTO aspects (review_id, aspect, sentiment, confidence) "
                        "VALUES (%s, %s, %s, %s)",
                        (r_id, a["aspect"], a["sentiment"], a.get("confidence")),
                    )
            cur.execute(
                "UPDATE reviews SET status = 'done', processed_at = now() "
                "WHERE id = ANY(%s::uuid[])",
                (valid_rids,),
            )

        logger.info("Elaborato batch di %d recensioni", len(texts))
        to_ack.extend(handle for handle, _ in valid_batch)
        return to_ack

    except Exception:
        logger.exception("Errore durante l'elaborazione del batch")
        # In caso di errore segniamo le recensioni come error nel database
        # e confermiamo i messaggi per evitare che vengano ritentati all'infinito
        valid_rids = [r_id for _, r_id in valid_batch]
        if valid_rids:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE reviews SET status = 'error' WHERE id = ANY(%s::uuid[])",
                    (valid_rids,),
                )
        to_ack.extend(handle for handle, _ in valid_batch)
        return to_ack



# --------------------------------------------------------------------------- #
# Backend RabbitMQ (Fase A)
# --------------------------------------------------------------------------- #
def connect_with_retry(max_attempts: int = 30):
    import pika

    params = pika.URLParameters(RABBITMQ_URL)
    params.heartbeat = 0  # Disattiviamo l'heartbeat per evitare disconnessioni durante l'inferenza
    params.blocked_connection_timeout = 300
    for attempt in range(1, max_attempts + 1):
        try:
            return pika.BlockingConnection(params)
        except pika.exceptions.AMQPConnectionError:
            logger.info("RabbitMQ non pronto, tentativo %d/%d", attempt, max_attempts)
            time.sleep(2)
    raise RuntimeError("Impossibile connettersi a RabbitMQ")


def consume_rabbitmq() -> None:
    connection = connect_with_retry()
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=BATCH_SIZE)

    logger.info(
        "Worker RabbitMQ pronto (MODEL_MODE=%s, BATCH_SIZE=%d). In attesa...",
        os.getenv("MODEL_MODE", "mock"), BATCH_SIZE,
    )

    batch: list[tuple] = []
    try:
        for method_frame, _properties, body in channel.consume(
            queue=QUEUE_NAME, inactivity_timeout=FLUSH_TIMEOUT
        ):
            if method_frame is not None:
                try:
                    msg = json.loads(body)
                    batch.append((method_frame.delivery_tag, msg["review_id"]))
                except Exception:
                    logger.exception("Messaggio non valido: %r", body)
                    channel.basic_ack(delivery_tag=method_frame.delivery_tag)

            # Elabora se il batch è pieno, se sono passati 2 secondi o se il pod si sta spegnendo
            if batch and (len(batch) >= BATCH_SIZE or method_frame is None or _shutdown):
                try:
                    # Conferma i messaggi completati con successo su RabbitMQ
                    for tag in process_batch(batch):
                        channel.basic_ack(delivery_tag=tag)
                except Exception:
                    logger.exception("Batch fallito; i messaggi verranno riconsegnati")
                batch.clear()


            if _shutdown:
                break
    except KeyboardInterrupt:
        logger.info("Ricevuto segnale di interruzione, uscita...")
    finally:
        channel.cancel()
        connection.close()


# --------------------------------------------------------------------------- #
# Backend SQS (Fase B)
# --------------------------------------------------------------------------- #
def consume_sqs() -> None:
    import boto3

    sqs = boto3.client("sqs", region_name=AWS_REGION)
    max_msgs = min(BATCH_SIZE, 10)  # SQS consente al massimo 10 messaggi per receive

    def delete(handles: list) -> None:
        # Su SQS confermare un messaggio equivale a cancellarlo dalla coda
        for i in range(0, len(handles), 10):
            chunk = handles[i:i + 10]
            entries = [
                {"Id": str(j), "ReceiptHandle": h} for j, h in enumerate(chunk)
            ]
            resp = sqs.delete_message_batch(QueueUrl=SQS_QUEUE_URL, Entries=entries)
            # Se la cancellazione fallisce, il messaggio verrà riconsegnato ed elaborato di nuovo
            failed = resp.get("Failed", [])
            if failed:
                logger.warning(
                    "delete_message_batch: %d entry fallite, verranno riconsegnate",
                    len(failed),
                )

    logger.info(
        "Worker SQS pronto (MODEL_MODE=%s, max_msgs=%d, queue=%s). In attesa...",
        os.getenv("MODEL_MODE", "mock"), max_msgs, SQS_QUEUE_URL,
    )

    while not _shutdown:
        try:
            resp = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=max_msgs,
                WaitTimeSeconds=20,  # Long polling di 20 secondi per ridurre chiamate e costi
                VisibilityTimeout=SQS_VISIBILITY_TIMEOUT,
            )
        except Exception:
            # In caso di errore temporaneo di rete attendiamo qualche secondo prima di riprovare
            logger.exception("receive_message fallita; nuovo tentativo tra %ds", SQS_ERROR_BACKOFF)
            time.sleep(SQS_ERROR_BACKOFF)
            continue


        messages = resp.get("Messages", [])
        if not messages:
            continue

        batch: list[tuple] = []
        for m in messages:
            try:
                body = json.loads(m["Body"])
                batch.append((m["ReceiptHandle"], body["review_id"]))
            except Exception:
                logger.exception("Messaggio non valido: %r", m.get("Body"))
                delete([m["ReceiptHandle"]])  # poison message: toglilo dalla coda

        try:
            # process_batch torna gli handle finiti: su SQS confermare = cancellare.
            delete(process_batch(batch))
        except Exception:
            logger.exception("Batch fallito; riconsegna via visibility timeout")

    logger.info("Uscita pulita del worker SQS")


def main() -> None:
    # Registriamo il gestore di spegnimento prima di iniziare ad ascoltare la coda
    signal.signal(signal.SIGTERM, _request_shutdown)

    if QUEUE_BACKEND == "sqs":
        consume_sqs()
    else:
        consume_rabbitmq()


if __name__ == "__main__":
    main()
