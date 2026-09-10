"""Test di render_manifest.py: i placeholder ${VAR} vanno risolti a
deploy-time, le variabili runtime $VAR (senza graffe) devono restare intatte
per la shell dei container."""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_manifest.py"


def render(text, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=text,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )


def test_placeholder_risolto():
    out = render("url: ${SQS_QUEUE_URL}", {"SQS_QUEUE_URL": "https://sqs/coda"})
    assert out.stdout == "url: https://sqs/coda"


def test_variabile_runtime_intatta():
    # $MODEL_MODE senza graffe è una variabile della shell del container:
    # non deve essere toccata, nemmeno se esiste nell'ambiente di deploy.
    out = render('cmd: echo "$MODEL_MODE"', {"MODEL_MODE": "pyabsa"})
    assert out.stdout == 'cmd: echo "$MODEL_MODE"'


def test_variabile_mancante_fa_fallire_il_rendering():
    # Meglio un deploy che si ferma qui che un Secret applicato vuoto: il
    # manifest reso a metà non deve mai arrivare a kubectl.
    env = {k: v for k, v in os.environ.items() if k != "NON_ESISTE"}
    out = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="x: ${NON_ESISTE}",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode != 0
    assert out.stdout == ""
    assert "NON_ESISTE" in out.stderr


def test_elenca_tutte_le_variabili_mancanti_in_una_volta():
    # Segnalarle una per volta costringerebbe a rilanciare il deploy N volte.
    env = {k: v for k, v in os.environ.items() if k not in ("MANCA_UNO", "MANCA_DUE")}
    out = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="a: ${MANCA_UNO}\nb: ${MANCA_DUE}\n",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "MANCA_UNO" in out.stderr
    assert "MANCA_DUE" in out.stderr
