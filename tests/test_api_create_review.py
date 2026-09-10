"""Test di POST /reviews: ordine tra salvataggio nel DB e pubblicazione in coda.

Il worker legge la recensione con un'altra connessione, quindi il messaggio
deve partire solo dopo il commit. DB e coda sono finti e registrano in una
lista le operazioni nell'ordine in cui avvengono.
"""
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

API_DIR = Path(__file__).resolve().parents[1] / "services" / "api"


def _moduli_app():
    return [nome for nome in sys.modules if nome == "app" or nome.startswith("app.")]


@pytest.fixture
def api(monkeypatch):
    """Importa app.main dell'API.

    Anche il worker ha un package chiamato `app` (vedi conftest.py): per la
    durata del test lo tolgo dalla cache degli import, poi lo rimetto.
    """
    for nome in _moduli_app():
        monkeypatch.delitem(sys.modules, nome)
    monkeypatch.syspath_prepend(str(API_DIR))
    yield importlib.import_module("app.main")
    for nome in _moduli_app():
        del sys.modules[nome]


class FakeCursor:
    def __init__(self, eventi):
        self.eventi = eventi

    def execute(self, sql, params=None):
        self.eventi.append(sql.split()[0])  # INSERT, DELETE, ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, eventi):
        self.eventi = eventi

    def cursor(self):
        return FakeCursor(self.eventi)


def finto_db(monkeypatch, api):
    """Sostituisce get_conn: come quello vero fa commit solo se non ci sono errori."""
    eventi = []

    @contextmanager
    def get_conn():
        yield FakeConn(eventi)
        eventi.append("commit")

    monkeypatch.setattr(api, "get_conn", get_conn)
    return eventi


def test_la_coda_parte_dopo_il_commit(monkeypatch, api):
    eventi = finto_db(monkeypatch, api)
    monkeypatch.setattr(api, "publish", lambda msg: eventi.append("publish"))

    risposta = api.create_review(api.ReviewIn(text="App ottima", bank="Banca"))

    assert eventi == ["INSERT", "commit", "publish"]
    assert risposta["status"] == "pending"


def test_coda_non_raggiungibile_toglie_la_recensione(monkeypatch, api):
    eventi = finto_db(monkeypatch, api)

    def publish_rotto(msg):
        raise ConnectionError("rabbitmq giù")

    monkeypatch.setattr(api, "publish", publish_rotto)

    with pytest.raises(HTTPException) as errore:
        api.create_review(api.ReviewIn(text="App ottima"))

    assert errore.value.status_code == 503
    # senza DELETE resterebbe 'pending' per sempre, senza messaggio in coda
    assert eventi == ["INSERT", "commit", "DELETE", "commit"]
