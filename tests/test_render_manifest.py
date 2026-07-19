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
    # $MODEL_MODE senza graffe e' una variabile della shell del container:
    # non deve essere toccata, nemmeno se esiste nell'ambiente di deploy.
    out = render('cmd: echo "$MODEL_MODE"', {"MODEL_MODE": "pyabsa"})
    assert out.stdout == 'cmd: echo "$MODEL_MODE"'


def test_variabile_mancante_avvisa_e_svuota():
    env = {k: v for k, v in os.environ.items() if k != "NON_ESISTE"}
    out = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="x: ${NON_ESISTE}",
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.stdout == "x: "
    assert "NON_ESISTE" in out.stderr
