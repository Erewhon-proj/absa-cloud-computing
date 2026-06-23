"""Publisher: deposita un messaggio nella coda di inferenza (RabbitMQ via pika).

L'interfaccia pubblica e' `publish(message: dict)`: chi chiama (main.py) non
conosce i dettagli della connessione.
"""
import json
import os

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
QUEUE_NAME = os.getenv("QUEUE_NAME", "absa.reviews")


def publish(message: dict) -> None:
    """Apre una connessione per publish: semplice e robusto (progetto didattico)."""
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
