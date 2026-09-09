"""Test del motore di inferenza in modalità mock.

Il mock è un'euristica a parole chiave: gira senza modello e senza rete, quindi
è l'unica parte del worker verificabile per intero in CI. Qui si controllano
l'estrazione degli aspetti, la stima del sentiment nella finestra attorno alla
parola chiave e la normalizzazione delle etichette che arrivano da PyABSA.
"""
import pytest

from app.inference import _map_result, _mock_infer, _normalize_sentiment, infer_batch


def aspetti(testo):
    """Comodità: {aspetto: sentiment} invece della lista di dizionari."""
    return {a["aspect"]: a["sentiment"] for a in _mock_infer(testo)}


def test_riconosce_aspetto_e_sentiment_negativo():
    assert aspetti("Assistenza pessima, ho aspettato 40 minuti.") == {
        "assistenza": "Negative"
    }


def test_riconosce_piu_aspetti_nella_stessa_frase():
    assert aspetti("App comoda e bonifici velocissimi.") == {
        "app": "Positive",
        "bonifico": "Positive",
    }


def test_aspetto_ripetuto_compare_una_volta_sola():
    # "app" e "applicazione" sono keyword dello stesso aspetto: una sola voce.
    assert list(aspetti("app app applicazione")) == ["app"]


def test_senza_parole_chiave_ricade_su_generale():
    assert aspetti("Il meteo di oggi.") == {"generale": "Neutral"}


def test_il_sentiment_guarda_solo_la_finestra_attorno_alla_parola_chiave():
    # "pessima" è accanto ad "assistenza" ma ben oltre i 4 token attorno a
    # "carta": deve pesare sul primo aspetto e non sul secondo.
    testo = "Assistenza pessima, comunque per il resto la carta mi è arrivata."
    giudizi = aspetti(testo)
    assert giudizi["assistenza"] == "Negative"
    assert giudizi["carta"] == "Neutral"


def test_infer_batch_restituisce_una_lista_per_ogni_testo():
    # Invariante su cui si appoggia lo zip(strict=True) in worker.process_batch:
    # se salta, alcune recensioni verrebbero chiuse senza aspetti.
    testi = ["App comoda.", "Il meteo di oggi.", "Costi troppo alti."]
    assert len(infer_batch(testi)) == len(testi)


@pytest.mark.parametrize(
    ("valore", "atteso"),
    [("-1", "Negative"), ("0", "Neutral"), ("1", "Positive"), (1, "Positive")],
)
def test_etichette_numeriche_di_pyabsa_diventano_stringhe(valore, atteso):
    # Il checkpoint addestrato emette -1/0/1, il DB e la dashboard usano le
    # stringhe: se questa conversione salta, /stats mostra categorie sbagliate.
    assert _normalize_sentiment(valore) == atteso


def test_map_result_tollera_i_campi_mancanti():
    # PyABSA può non restituire le confidenze: il campo resta None, non salta
    # l'intero risultato.
    assert _map_result({"aspect": ["app"], "sentiment": ["1"]}) == [
        {"aspect": "app", "sentiment": "Positive", "confidence": None}
    ]
    assert _map_result({}) == []


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        # "insoddisfatto" contiene "soddisf", "sconsiglio" contiene "consigl" e
        # "inefficiente" contiene "efficient": con un confronto a sottostringa
        # verrebbero contate tutte e tre come positive.
        ("Sono insoddisfatto del servizio.", "Negative"),
        ("Sconsiglio questa banca a tutti.", "Negative"),
        ("Tutto inefficiente qui.", "Negative"),
    ],
)
def test_le_radici_si_confrontano_a_inizio_parola(testo, atteso):
    assert aspetti(testo)["generale"] == atteso


def test_la_parola_altri_non_pesa_come_negativa():
    # La radice negativa per "costi alti" sono le quattro forme per esteso:
    # se fosse "alt" prenderebbe anche altro/altri/altra/altre.
    testo = "Ho parlato con altri operatori, molto gentili e disponibili."
    assert aspetti(testo)["assistenza"] == "Positive"


def test_costi_alti_resta_negativo():
    # Controprova del test precedente: la forma che serviva davvero funziona,
    # flessioni comprese.
    assert aspetti("Commissione altissima sul canone.")["costi"] == "Negative"


@pytest.mark.parametrize(
    ("testo", "aspetto", "atteso"),
    [
        ("Nessun problema con i bonifici.", "bonifico", "Positive"),
        ("Non consiglio, assistenza lentissima.", "assistenza", "Negative"),
    ],
)
def test_una_negazione_inverte_la_parola_che_segue(testo, aspetto, atteso):
    assert aspetti(testo)[aspetto] == atteso


def test_gli_aspetti_escono_nell_ordine_in_cui_compaiono():
    testo = "Costi bassi, poi ho aperto il conto e l'app funziona."
    assert list(aspetti(testo)) == ["costi", "conto", "app"]


def test_non_funziona_e_negativo():
    # "funziona" è una radice positiva: è la negazione a renderlo un reclamo.
    assert aspetti("La carta non funziona.")["carta"] == "Negative"
    assert aspetti("La carta funziona bene.")["carta"] == "Positive"


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        (
            "App ottima e veloce, ma assistenza lentissima e costi alti.",
            {"app": "Positive", "assistenza": "Negative", "costi": "Negative"},
        ),
        (
            "Il bonifico è arrivato in ritardo, però l'app è comoda.",
            {"bonifico": "Negative", "app": "Positive"},
        ),
        (
            "Bonifici rapidi, mentre la carta ha avuto problemi.",
            {"bonifico": "Positive", "carta": "Negative"},
        ),
    ],
)
def test_la_finestra_si_ferma_alle_avversative(testo, atteso):
    # Prima la finestra scavalcava il "ma" e i giudizi opposti si annullavano.
    risultato = aspetti(testo)
    for aspetto, sentiment in atteso.items():
        assert risultato[aspetto] == sentiment


def test_la_finestra_si_ferma_a_fine_frase():
    assert aspetti("Carta lenta. Bonifico veloce.") == {
        "carta": "Negative",
        "bonifico": "Positive",
    }


def test_invece_non_taglia_la_finestra():
    assert aspetti("Il sito è lento. Il bonifico invece è veloce.") == {
        "app": "Negative",
        "bonifico": "Positive",
    }
