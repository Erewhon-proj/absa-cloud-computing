"""API Gateway (Tier 2).

Riceve recensioni via HTTP, le persiste come 'pending' su PostgreSQL e
pubblica un task sulla coda (RabbitMQ in locale, SQS in cloud: vedi queue.py).
Il worker le elabora in modo asincrono.
"""
import logging
import uuid

from fastapi import FastAPI, HTTPException, Query
from psycopg2.extras import RealDictCursor

from .db import get_conn
from .queue import publish
from .schemas import ReviewAccepted, ReviewIn, ReviewOut

logger = logging.getLogger("api")

app = FastAPI(title="ABSA API Gateway", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reviews", status_code=202, response_model=ReviewAccepted)
def create_review(review: ReviewIn):
    """Accetta una recensione e la mette in coda per l'inferenza asincrona."""
    review_id = str(uuid.uuid4())
    # Prima il commit, poi la coda. Il worker cerca la recensione con un'altra
    # connessione e finché non c'è il commit non la vede: pubblicando prima,
    # un worker libero la cercava, non la trovava e scartava il messaggio.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reviews (id, bank, text, status) "
                "VALUES (%s, %s, %s, 'pending')",
                (review_id, review.bank, review.text),
            )
    try:
        publish({"review_id": review_id})
    except Exception:
        # Senza messaggio in coda nessuno la elaborerebbe: si rimuove dal DB,
        # così non resta 'pending' per sempre ed il client può riprovare.
        logger.exception("Pubblicazione in coda fallita per %s", review_id)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
        raise HTTPException(status_code=503, detail="Queue unavailable") from None
    return {"id": review_id, "status": "pending"}


@app.get("/reviews", response_model=list[ReviewOut])
def list_reviews(bank: str | None = Query(None), limit: int = Query(20, ge=1, le=100)):
    """Ultime recensioni inserite, con i relativi aspetti (per la dashboard)."""
    where = "WHERE bank = %s" if bank else ""
    params = [bank] if bank else []
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM reviews {where} ORDER BY created_at DESC LIMIT %s",
            params + [limit],
        )
        rows = cur.fetchall()
        # una sola query per gli aspetti di tutte le recensioni trovate
        by_review: dict = {}
        if rows:
            cur.execute(
                "SELECT review_id, aspect, sentiment, confidence FROM aspects "
                "WHERE review_id = ANY(%s::uuid[])",
                ([r["id"] for r in rows],),
            )
            for a in cur.fetchall():
                by_review.setdefault(a["review_id"], []).append(a)
        for r in rows:
            r["aspects"] = by_review.get(r["id"], [])
    return rows


@app.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: str):
    """Restituisce stato della recensione e aspetti estratti."""
    # Valida il formato prima della query
    try:
        uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Review not found") from None
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM reviews WHERE id = %s", (review_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Review not found")
        cur.execute(
            "SELECT aspect, sentiment, confidence FROM aspects "
            "WHERE review_id = %s",
            (review_id,),
        )
        row["aspects"] = cur.fetchall()
    return row


@app.get("/stats")
def stats(bank: str | None = Query(None)):
    """Aggrega il sentiment per aspetto (filtrabile per banca)."""
    where = "WHERE r.bank = %s" if bank else ""
    params = [bank] if bank else []
    query = (
        "SELECT a.aspect, a.sentiment, COUNT(*) AS count "
        "FROM aspects a JOIN reviews r ON r.id = a.review_id "
        f"{where} "
        "GROUP BY a.aspect, a.sentiment "
        "ORDER BY a.aspect, a.sentiment"
    )
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return {"data": rows}
