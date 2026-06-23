"""Schemi Pydantic per richieste/risposte dell'API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ReviewIn(BaseModel):
    text: str = Field(..., min_length=3, description="Testo della recensione")
    bank: Optional[str] = Field(None, description="Nome della banca")


class AspectOut(BaseModel):
    aspect: str
    sentiment: str
    confidence: Optional[float] = None


class ReviewOut(BaseModel):
    id: str
    bank: Optional[str]
    text: str
    status: str
    created_at: datetime
    processed_at: Optional[datetime] = None
    aspects: List[AspectOut] = []


class ReviewAccepted(BaseModel):
    id: str
    status: str
