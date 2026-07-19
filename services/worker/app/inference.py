"""Motore di inferenza ABSA.

Due modalita', selezionate da MODEL_MODE:
  - "mock"  : euristica a parole chiave (default). Nessun download del modello,
              gira ovunque: utile per sviluppare e testare l'architettura.
  - "pyabsa": usa il modello reale LCF-ATEPC tramite PyABSA. Richiede le
              dipendenze ML (vedi requirements-ml.txt) e scarica i pesi BERT.

In modalita' "pyabsa", se il caricamento fallisce si ricade automaticamente
sul mock, cosi' la pipeline non si blocca mai.
"""
import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger("inference")

MODEL_MODE = os.getenv("MODEL_MODE", "mock").lower()
# Path della cartella-checkpoint LCF-ATEPC (i 4 file lcf_atepc.*), oppure un
# nome di checkpoint pubblico ("multilingual"). Per il nostro modello addestrato
# montare la cartella e puntare qui, es. /models/checkpoint
ABSA_CHECKPOINT = os.getenv("ABSA_CHECKPOINT", "multilingual")

_extractor = None


# --------------------------------------------------------------------------- #
# Modalita' PyABSA (modello reale LCF-ATEPC)
# --------------------------------------------------------------------------- #
def _load_pyabsa():
    """Carica l'AspectExtractor (stessa API usata nel repo absa-trustpilot)."""
    global _extractor
    if _extractor is None:
        from pyabsa import AspectTermExtraction as ATEPC  # import lazy: pesante

        logger.info("Carico checkpoint PyABSA: %s", ABSA_CHECKPOINT)
        _extractor = ATEPC.AspectExtractor(
            checkpoint=ABSA_CHECKPOINT,
            auto_device=True,  # GPU se disponibile, altrimenti CPU
        )
    return _extractor


# Il checkpoint e' stato addestrato con etichette numeriche (-1/0/1). Il resto
# del sistema (DB, /stats, frontend) usa le stringhe, quindi le normalizziamo qui.
_SENTIMENT_LABELS = {
    "-1": "Negative",
    "0": "Neutral",
    "1": "Positive",
}


def _normalize_sentiment(value) -> str:
    label = str(value).strip()
    return _SENTIMENT_LABELS.get(label, label.capitalize())


def _map_result(item: Dict) -> List[Dict]:
    """Converte un risultato PyABSA in lista di coppie (aspetto, sentiment)."""
    aspects = item.get("aspect", []) or []
    sentiments = item.get("sentiment", []) or []
    confidences = item.get("confidence", []) or []
    out = []
    for i, asp in enumerate(aspects):
        out.append(
            {
                "aspect": asp,
                "sentiment": _normalize_sentiment(sentiments[i])
                if i < len(sentiments)
                else "Neutral",
                "confidence": float(confidences[i])
                if i < len(confidences)
                else None,
            }
        )
    return out


def _pyabsa_infer_batch(texts: List[str]) -> List[List[Dict]]:
    extractor = _load_pyabsa()
    results = extractor.extract_aspect(
        inference_source=texts, pred_sentiment=True
    )
    return [_map_result(r) for r in results]


# --------------------------------------------------------------------------- #
# Modalita' mock (euristica a parole chiave, in italiano)
# --------------------------------------------------------------------------- #
ASPECT_KEYWORDS = {
    "assistenza": ["assistenza", "supporto", "operatore", "operatori", "aiuto"],
    "app": ["app", "applicazione", "interfaccia", "sito", "homebanking"],
    "costi": ["costi", "costo", "commissioni", "canone", "spese", "prezzo", "gratis"],
    "carta": ["carta", "bancomat", "credito", "debito"],
    "bonifico": ["bonifico", "bonifici", "pagamento", "trasferimento", "accredito"],
    "conto": ["conto", "apertura", "iban", "chiusura"],
    "tempi": ["tempi", "attesa", "ritardo"],
}

# Matching per radice (substring): cattura anche flessioni (lento/lentissima).
POSITIVE_STEMS = {
    "ottim", "buon", "veloc", "rapid", "efficient", "comod", "gratis",
    "facil", "perfett", "consigl", "soddisf", "profession", "chiar",
    "gentil", "risolt", "bass",
}
NEGATIVE_STEMS = {
    "pessim", "lent", "ritard", "costos", "difficil", "problem", "error",
    "scars", "delus", "truff", "scandal", "vergogn", "inutil", "alt",
    "nascost",
}

WINDOW = 4  # token a sinistra/destra dell'aspetto per stimarne il sentiment


def _score(tokens: List[str]) -> str:
    text = " ".join(tokens)
    pos = sum(1 for s in POSITIVE_STEMS if s in text)
    neg = sum(1 for s in NEGATIVE_STEMS if s in text)
    if pos > neg:
        return "Positive"
    if neg > pos:
        return "Negative"
    return "Neutral"


def _mock_infer(text: str) -> List[Dict]:
    tokens = re.findall(r"\w+", text.lower())
    out = []
    seen = set()  # ogni aspetto una volta sola: alla prima keyword, break
    for aspect, keywords in ASPECT_KEYWORDS.items():
        for i, tok in enumerate(tokens):
            if tok in keywords and aspect not in seen:
                # trovata la keyword: guardo WINDOW token a sinistra/destra per il sentiment
                window = tokens[max(0, i - WINDOW): i + WINDOW + 1]
                out.append(
                    {"aspect": aspect, "sentiment": _score(window), "confidence": None}
                )
                seen.add(aspect)
                break
    if not out:
        # nessun aspetto noto: sentiment generale sull'intero testo
        out.append(
            {"aspect": "generale", "sentiment": _score(tokens), "confidence": None}
        )
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def infer(text: str) -> List[Dict]:
    """Inferenza su un singolo testo -> lista di coppie (aspetto, sentiment)."""
    return infer_batch([text])[0]


def infer_batch(texts: List[str]) -> List[List[Dict]]:
    """Inferenza su piu' testi in un colpo solo (molto piu' efficiente su BERT).

    Da usare per il micro-batching lato worker: si accumulano N messaggi dalla
    coda e si chiama questa funzione una sola volta.
    """
    if MODEL_MODE == "pyabsa":
        try:
            return _pyabsa_infer_batch(texts)
        except Exception as exc:  # noqa: BLE001
            logger.exception("PyABSA non disponibile, uso il mock: %s", exc)
    return [_mock_infer(t) for t in texts]
