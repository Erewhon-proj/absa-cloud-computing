"""Publisher: deposita un messaggio nella coda di inferenza.

Due backend, selezionati da QUEUE_BACKEND:
  - "rabbitmq" (default): RabbitMQ via pika   -> Fase A locale (OrbStack).
  - "sqs":                Amazon SQS via boto3 -> Fase B cloud (AWS).

L'interfaccia pubblica resta `publish(message: dict)`, identica per entrambi:
chi chiama (main.py) non sa quale backend è attivo.
"""
import json
import os

QUEUE_BACKEND = os.getenv("QUEUE_BACKEND", "rabbitmq").lower()

# --- RabbitMQ (Fase A) ---
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
QUEUE_NAME = os.getenv("QUEUE_NAME", "absa.reviews")

# --- SQS (Fase B) ---
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")

_sqs_client = None


def _publish_rabbitmq(message: dict) -> None:
    """Apre una connessione per publish."""
    import pika

    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps(message),
            properties=pika.BasicProperties(delivery_mode=2),  # persistente
        )
    finally:
        connection.close()


def _get_sqs():
    """Client SQS riusato tra le richieste (boto3 è thread-safe per send_message)."""
    global _sqs_client
    if _sqs_client is None:
        import boto3

        _sqs_client = boto3.client("sqs", region_name=AWS_REGION)
    return _sqs_client


def _publish_sqs(message: dict) -> None:
    _get_sqs().send_message(
        QueueUrl=SQS_QUEUE_URL,
        MessageBody=json.dumps(message),
    )


def publish(message: dict) -> None:
    """Pubblica un messaggio JSON sulla coda di inferenza (backend secondo QUEUE_BACKEND)."""
    if QUEUE_BACKEND == "sqs":
        _publish_sqs(message)
    else:
        _publish_rabbitmq(message)
