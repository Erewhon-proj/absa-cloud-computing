"""Inference worker (Tier 2, asincrono).

Consuma i task da una coda di messaggi, esegue l'inferenza ABSA sulla recensione
e salva gli aspetti estratti su PostgreSQL. E' il componente che l'HPA/KEDA (o un
Auto Scaling Group) replichera' sotto carico. Implementa micro-batching per
massimizzare il throughput del modello ML.

Due backend di coda, selezionati da QUEUE_BACKEND:
  - "rabbitmq" (default): RabbitMQ via pika   -> Fase A locale (OrbStack).
  - "sqs":                Amazon SQS via boto3 -> Fase B cloud (AWS).

La logica di elaborazione (`process_batch`) e' condivisa: restituisce gli handle
dei messaggi elaborati e lascia che sia il chiamante a confermarli (ack su
RabbitMQ, delete su SQS), cosi' non dipende dal backend.
"""
import json
import logging
import os
import time
from typing import List, Tuple

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
# Deve superare il tempo massimo di elaborazione di un batch (load modello + inferenza CPU).
SQS_VISIBILITY_TIMEOUT = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
# Attesa dopo un errore transitorio di receive_message, prima di riprovare.
SQS_ERROR_BACKOFF = int(os.getenv("SQS_ERROR_BACKOFF", "5"))

# Un "handle" e' il delivery_tag (RabbitMQ) o il ReceiptHandle (SQS): l'identificatore
# che serve al backend per confermare (ack/delete) un messaggio elaborato.


def process_batch(batch: List[Tuple]) -> List:
    """Elabora un batch di recensioni: estrae dal DB, fa inferenza, salva i risultati.

    `batch` e' una lista di (handle, review_id). Restituisce la lista degli
    `handle` da confermare: chi chiama li conferma a modo suo (ack su RabbitMQ,
    delete su SQS), cosi' questa funzione non conosce il backend.

    Errori durante il salvataggio: gli aspetti vengono marcati 'error' e i
    messaggi confermati comunque (niente loop su "poison message"). Se invece
    fallisce l'accesso al DB stesso, l'eccezione si propaga SENZA restituire
    handle -> riconsegna (e DLQ su SQS dopo N tentativi).
    """
    if not batch:
        return []

    review_ids = [item[1] for item in batch]
    valid_batch: List[Tuple] = []
    to_ack: List = []  # handle dei messaggi finiti, da confermare a fine batch

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
        # Divide i messaggi: quelli con una review nel DB vanno elaborati; quelli
        # "orfani" (review sparita) li confermiamo e basta, ritentarli e' inutile.
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
            for (_, r_id), aspects in zip(valid_batch, batch_aspects):
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

    except Exception:  # noqa: BLE001
        logger.exception("Errore durante l'elaborazione del batch")
        # Registra l'errore (se il DB e' raggiungibile) e conferma i messaggi per
        # evitare loop su "poison message". Se anche questo fallisce, l'eccezione
        # si propaga e i messaggi NON vengono confermati -> riconsegna.
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
    params.heartbeat = 0  # niente heartbeat: l'inferenza puo' bloccare a lungo
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

    batch: List[Tuple] = []
    try:
        for method_frame, _properties, body in channel.consume(
            queue=QUEUE_NAME, inactivity_timeout=FLUSH_TIMEOUT
        ):
            if method_frame is not None:
                try:
                    msg = json.loads(body)
                    batch.append((method_frame.delivery_tag, msg["review_id"]))
                except Exception:  # noqa: BLE001
                    logger.exception("Messaggio non valido: %r", body)
                    channel.basic_ack(delivery_tag=method_frame.delivery_tag)

            # Flush se il batch e' pieno o se e' scattato il timeout di inattivita'.
            if len(batch) >= BATCH_SIZE or (method_frame is None and batch):
                try:
                    # process_batch torna gli handle finiti: qui li confermiamo (ack).
                    for tag in process_batch(batch):
                        channel.basic_ack(delivery_tag=tag)
                except Exception:  # noqa: BLE001
                    logger.exception("Batch fallito; i messaggi verranno riconsegnati")
                batch.clear()
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

    def delete(handles: List) -> None:
        # Su SQS "confermare" un messaggio significa cancellarlo. delete_message_batch
        # accetta al massimo 10 entry per chiamata, quindi procediamo a blocchi di 10.
        for i in range(0, len(handles), 10):
            chunk = handles[i:i + 10]
            entries = [
                {"Id": str(j), "ReceiptHandle": h} for j, h in enumerate(chunk)
            ]
            resp = sqs.delete_message_batch(QueueUrl=SQS_QUEUE_URL, Entries=entries)
            # La chiamata puo' fallire parzialmente senza sollevare eccezioni:
            # le entry fallite verranno riconsegnate (elaborazione idempotente).
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

    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=max_msgs,
                WaitTimeSeconds=20,  # long polling: meno richieste vuote, meno costo
                VisibilityTimeout=SQS_VISIBILITY_TIMEOUT,
            )
        except Exception:  # noqa: BLE001
            # Errore transitorio (throttling SQS, blip IAM/rete): non far morire il
            # worker (evita CrashLoopBackOff di massa), attendi un attimo e riprova.
            logger.exception("receive_message fallita; nuovo tentativo tra %ds", SQS_ERROR_BACKOFF)
            time.sleep(SQS_ERROR_BACKOFF)
            continue

        messages = resp.get("Messages", [])
        if not messages:
            continue

        batch: List[Tuple] = []
        for m in messages:
            try:
                body = json.loads(m["Body"])
                batch.append((m["ReceiptHandle"], body["review_id"]))
            except Exception:  # noqa: BLE001
                logger.exception("Messaggio non valido: %r", m.get("Body"))
                delete([m["ReceiptHandle"]])  # poison message: toglilo dalla coda

        try:
            # process_batch torna gli handle finiti: su SQS confermare = cancellare.
            delete(process_batch(batch))
        except Exception:  # noqa: BLE001
            logger.exception("Batch fallito; riconsegna via visibility timeout")


def main() -> None:
    if QUEUE_BACKEND == "sqs":
        consume_sqs()
    else:
        consume_rabbitmq()


if __name__ == "__main__":
    main()
