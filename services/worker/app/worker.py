"""Inference worker (Tier 2, asincrono).

Consuma i task da una coda di messaggi (RabbitMQ), esegue l'inferenza ABSA sulla
recensione e salva gli aspetti estratti su PostgreSQL. E' il componente che
l'HPA/KEDA (o un Auto Scaling Group) replichera' sotto carico. Implementa
micro-batching per massimizzare il throughput del modello ML.

La logica di elaborazione (`process_batch`) restituisce i delivery tag dei
messaggi elaborati e lascia che sia il chiamante a confermarli (ack su
RabbitMQ).
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

QUEUE_NAME = os.getenv("QUEUE_NAME", "absa.reviews")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "16"))
FLUSH_TIMEOUT = float(os.getenv("FLUSH_TIMEOUT", "2.0"))

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")


def process_batch(batch: List[Tuple]) -> List:
    """Elabora un batch di recensioni: estrae dal DB, fa inferenza, salva i risultati.

    `batch` e' una lista di (delivery_tag, review_id). Restituisce la lista dei
    `delivery_tag` da confermare con basic_ack a fine batch.

    Errori durante il salvataggio: gli aspetti vengono marcati 'error' e i
    messaggi confermati comunque (niente loop su "poison message"). Se invece
    fallisce l'accesso al DB stesso, l'eccezione si propaga SENZA restituire
    handle -> riconsegna.
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
# Consumo dalla coda
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


def main() -> None:
    consume_rabbitmq()


if __name__ == "__main__":
    main()
