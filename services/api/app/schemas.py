"""Schemi Pydantic per richieste/risposte dell'API."""
from datetime import datetime

from pydantic import BaseModel, Field


class ReviewIn(BaseModel):
    text: str = Field(..., min_length=3, description="Testo della recensione")
    bank: str | None = Field(None, description="Nome della banca")


class AspectOut(BaseModel):
    aspect: str
    sentiment: str
    confidence: float | None = None


class ReviewOut(BaseModel):
    id: str
    bank: str | None
    text: str
    status: str
    created_at: datetime
    processed_at: datetime | None = None
    aspects: list[AspectOut] = []


class ReviewAccepted(BaseModel):
    id: str
    status: str
