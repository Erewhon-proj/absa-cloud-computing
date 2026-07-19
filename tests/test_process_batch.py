"""Test di process_batch, la logica di elaborazione condivisa del worker.

DB e inferenza sono sostituiti da oggetti finti in memoria: qui si verifica
il contratto sui messaggi (quali handle vengono confermati e in quale stato
finiscono le recensioni), non psycopg2 ne' il modello.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "worker"))

from app import worker  # noqa: E402


class FakeCursor:
    def __init__(self, select_rows, executed):
        self._select_rows = select_rows
        self.executed = executed

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchall(self):
        return self._select_rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, cursor_factory=None):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_db(monkeypatch, select_rows):
    """Sostituisce worker.get_conn; ritorna la lista delle SQL eseguite."""
    executed = []
    cursor = FakeCursor(select_rows, executed)
    monkeypatch.setattr(worker, "get_conn", lambda: FakeConn(cursor))
    return executed


def test_batch_vuoto():
    assert worker.process_batch([]) == []


def test_batch_ok_conferma_tutti_gli_handle(monkeypatch):
    executed = fake_db(monkeypatch, [
        {"id": "id1", "text": "testo uno"},
        {"id": "id2", "text": "testo due"},
    ])
    monkeypatch.setattr(worker, "infer_batch", lambda texts: [[] for _ in texts])

    acked = worker.process_batch([("h1", "id1"), ("h2", "id2")])

    assert sorted(acked) == ["h1", "h2"]
    # le recensioni elaborate vengono chiuse in stato done
    assert any("'done'" in sql for sql in executed)


def test_messaggio_orfano_confermato_senza_inferenza(monkeypatch):
    """Review sparita dal DB: il messaggio va confermato (ritentare e' inutile)
    e il suo testo non deve arrivare al modello."""
    fake_db(monkeypatch, [{"id": "id1", "text": "testo uno"}])
    chiamate = []

    def spia(texts):
        chiamate.append(texts)
        return [[] for _ in texts]

    monkeypatch.setattr(worker, "infer_batch", spia)

    acked = worker.process_batch([("h1", "id1"), ("h2", "id-mancante")])

    assert sorted(acked) == ["h1", "h2"]
    assert chiamate == [["testo uno"]]


def test_errore_di_inferenza_marca_error_e_conferma(monkeypatch):
    """Fallimento del modello: stato error sul DB e messaggio comunque
    confermato, per non generare un poison message."""
    executed = fake_db(monkeypatch, [{"id": "id1", "text": "testo uno"}])

    def boom(texts):
        raise RuntimeError("modello rotto")

    monkeypatch.setattr(worker, "infer_batch", boom)

    acked = worker.process_batch([("h1", "id1")])

    assert acked == ["h1"]
    assert any("'error'" in sql for sql in executed)


def test_db_irraggiungibile_nessuna_conferma(monkeypatch):
    """DB giu': nessun handle restituito, i messaggi verranno riconsegnati."""
    def no_db():
        raise ConnectionError("db giu'")

    monkeypatch.setattr(worker, "get_conn", no_db)

    assert worker.process_batch([("h1", "id1")]) == []
