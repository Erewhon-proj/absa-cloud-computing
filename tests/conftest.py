"""Rende importabile il package `app` del worker dai test.

Il worker non è un pacchetto installabile (è solo il contenuto di un'immagine
Docker), quindi la sua cartella va aggiunta a sys.path a mano. Stando qui, la
riga vale per tutti i file di test e non va ripetuta in ognuno.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "worker"))
