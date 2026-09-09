"""Motore di inferenza ABSA.

Due modalità, selezionate da MODEL_MODE:
  - "mock"  : euristica a parole chiave (default). Nessun download del modello,
              gira ovunque: utile per sviluppare e testare l'architettura.
  - "pyabsa": usa il modello reale LCF-ATEPC tramite PyABSA. Richiede le
              dipendenze ML (vedi requirements-ml.txt) e scarica i pesi BERT.

In modalità "pyabsa", se il caricamento fallisce si ricade automaticamente
sul mock, così la pipeline non si blocca mai.
"""
import logging
import os
import re
import time

logger = logging.getLogger("inference")

MODEL_MODE = os.getenv("MODEL_MODE", "mock").lower()
# Path della cartella-checkpoint LCF-ATEPC (i 4 file lcf_atepc.*), oppure un
# nome di checkpoint pubblico ("multilingual").
ABSA_CHECKPOINT = os.getenv("ABSA_CHECKPOINT", "multilingual")
# Secondi di attesa per ogni batch elaborato dal mock. Il mock è un'euristica a
# stringhe: costa microsecondi, mentre il modello reale su CPU impiega secondi.
# Con 0 un solo worker svuota la coda prima che KEDA la campioni, e l'autoscaling
# non si osserva. Alzarlo simula il costo dell'inferenza. 0 = disattivato.
MOCK_DELAY = float(os.getenv("MOCK_DELAY", "0"))

_extractor = None


# --------------------------------------------------------------------------- #
# Modalità PyABSA (modello reale LCF-ATEPC)
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


# Il checkpoint è stato addestrato con etichette numeriche (-1/0/1). Il resto
# del sistema (DB, /stats, frontend) usa le stringhe, quindi le normalizziamo qui.
_SENTIMENT_LABELS = {
    "-1": "Negative",
    "0": "Neutral",
    "1": "Positive",
}


def _normalize_sentiment(value) -> str:
    label = str(value).strip()
    return _SENTIMENT_LABELS.get(label, label.capitalize())


def _map_result(item: dict) -> list[dict]:
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


def _pyabsa_infer_batch(texts: list[str]) -> list[list[dict]]:
    extractor = _load_pyabsa()
    results = extractor.extract_aspect(
        inference_source=texts, pred_sentiment=True
    )
    return [_map_result(r) for r in results]


# --------------------------------------------------------------------------- #
# Modalità mock (euristica a parole chiave, in italiano)
# --------------------------------------------------------------------------- #
ASPECT_KEYWORDS = {
    "assistenza": ["assistenza", "supporto", "operatore", "operatori", "aiuto",
                   "consulente", "sportello"],
    "app": ["app", "applicazione", "interfaccia", "sito", "homebanking"],
    "costi": ["costi", "costo", "commissioni", "commissione", "canone", "spese",
              "spesa", "prezzo", "gratis"],
    "carta": ["carta", "carte", "bancomat", "credito", "debito"],
    "bonifico": ["bonifico", "bonifici", "pagamento", "pagamenti", "trasferimento",
                 "accredito", "accrediti"],
    "conto": ["conto", "conti", "apertura", "iban", "chiusura"],
    "tempi": ["tempi", "tempo", "attesa", "attese", "ritardo", "ritardi"],
}

# Indice inverso parola -> aspetto, costruito una volta sola. Permette di
# scorrere il testo una parola alla volta invece di rileggerlo per ogni aspetto,
# e restituisce gli aspetti nell'ordine in cui compaiono nella recensione.
_KEYWORD_TO_ASPECT = {kw: asp for asp, kws in ASPECT_KEYWORDS.items() for kw in kws}

# Radici, confrontate con str.startswith su ogni singolo token: "lent" prende
# lento/lenta/lentissima, ma non parole che se la ritrovano in mezzo. Con un
# match a sottostringa "insoddisfatto" conterebbe come positivo (contiene
# "soddisf") e "sconsiglio" pure (contiene "consigl").
POSITIVE_STEMS = (
    "ottim", "buon", "veloc", "rapid", "efficient", "comod", "gratis",
    "facil", "perfett", "consigl", "soddisf", "profession", "chiar",
    "gentil", "risolt", "bass",
    # "funziona" è positivo di suo, e con la regola sulle negazioni qui sotto
    # copre "non funziona", che è la lamentela più frequente.
    "funzion",
)
NEGATIVE_STEMS = (
    "pessim", "lent", "ritard", "costos", "difficil", "problem", "error",
    "scars", "delus", "truff", "scandal", "vergogn", "inutil", "nascost",
    # forme negate che le radici positive qui sopra non intercettano
    "insoddisf", "sconsigl", "inefficient",
    # "costi alti": le quattro forme per esteso e non la radice "alt", che
    # prenderebbe anche altro/altri/altra/altre
    "alto", "alta", "alti", "alte",
)

# Una negazione inverte la parola che la segue: "non consiglio" vale come
# negativo, "nessun problema" come positivo. Guarda solo la parola subito dopo,
# quindi non copre le negazioni a distanza ("nessun altro problema").
NEGATIONS = frozenset({"non", "nessun", "nessuna", "nessuno", "mai", "senza"})

WINDOW = 4  # parole a sinistra/destra dell'aspetto per stimarne il sentiment

# La finestra non supera la fine di una frase né una congiunzione avversativa.
# In "app ottima, ma assistenza lentissima" altrimenti "ottima" e "lentissima"
# finirebbero in tutte e due le finestre, e i due aspetti uscirebbero Neutral.
# La virgola no: separa anche pezzi della stessa frase ("conto a canone zero,
# nessuna commissione: ottimo"). E nemmeno "invece", che spesso sta dopo il
# soggetto ("il bonifico invece è veloce") e taglierebbe proprio la parte utile.
CONFINI = frozenset({".", "!", "?", ";", "ma", "però", "mentre", "tuttavia"})


def _score(tokens: list[str]) -> str:
    pos = neg = 0
    for i, tok in enumerate(tokens):
        if tok.startswith(POSITIVE_STEMS):
            polarita = 1
        elif tok.startswith(NEGATIVE_STEMS):
            polarita = -1
        else:
            continue
        if i and tokens[i - 1] in NEGATIONS:
            polarita = -polarita
        if polarita > 0:
            pos += 1
        else:
            neg += 1
    if pos > neg:
        return "Positive"
    if neg > pos:
        return "Negative"
    return "Neutral"


def _finestra(tokens: list[str], i: int) -> list[str]:
    """Fino a WINDOW parole per lato attorno a tokens[i], fermandosi ai CONFINI."""
    inizio = i
    while inizio > 0 and i - inizio < WINDOW and tokens[inizio - 1] not in CONFINI:
        inizio -= 1
    fine = i
    while fine < len(tokens) - 1 and fine - i < WINDOW and tokens[fine + 1] not in CONFINI:
        fine += 1
    return tokens[inizio: fine + 1]


def _mock_infer(text: str) -> list[dict]:
    # oltre alle parole tiene la punteggiatura di fine frase, che serve a _finestra
    tokens = re.findall(r"\w+|[.!?;]", text.lower())
    out = []
    seen = set()  # ogni aspetto una volta sola, alla prima parola che lo nomina
    for i, tok in enumerate(tokens):
        aspect = _KEYWORD_TO_ASPECT.get(tok)
        if aspect is None or aspect in seen:
            continue
        out.append(
            {"aspect": aspect, "sentiment": _score(_finestra(tokens, i)), "confidence": None}
        )
        seen.add(aspect)
    if not out:
        # nessun aspetto noto: sentiment generale sull'intero testo
        out.append(
            {"aspect": "generale", "sentiment": _score(tokens), "confidence": None}
        )
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def infer(text: str) -> list[dict]:
    """Inferenza su un singolo testo -> lista di coppie (aspetto, sentiment)."""
    return infer_batch([text])[0]


def infer_batch(texts: list[str]) -> list[list[dict]]:
    """Inferenza su più testi in un colpo solo (molto più efficiente su BERT).

    Da usare per il micro-batching lato worker: si accumulano N messaggi dalla
    coda e si chiama questa funzione una sola volta.
    """
    if MODEL_MODE == "pyabsa":
        try:
            return _pyabsa_infer_batch(texts)
        except Exception as exc:
            logger.exception("PyABSA non disponibile, uso il mock: %s", exc)
    if MOCK_DELAY:
        # Il ritardo è per batch, non per testo: è così che si comporta il
        # modello reale, ed è la ragione per cui il worker fa micro-batching.
        time.sleep(MOCK_DELAY)
    return [_mock_infer(t) for t in texts]
