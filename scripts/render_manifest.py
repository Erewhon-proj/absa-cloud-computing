#!/usr/bin/env python3
"""Risolve i placeholder ${VAR} di un manifest K8s con le variabili d'ambiente.

Regola unica: ogni ${VAR} viene sostituito con la variabile d'ambiente omonima.
Le variabili *runtime* dei container si scrivono SENZA graffe ($MODEL_MODE,
$DATABASE_URL, ...)

In breve: cerca il placeholder, chiede all'os se esiste e lo sostituisce

Uso:
    cat k8s/aws/01-config.yaml | python3 scripts/render_manifest.py | kubectl apply -f -
"""
import os
import re
import sys

PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def rendi(testo: str) -> tuple[str, list[str]]:
    """Sostituisce i placeholder e restituisce (testo reso, variabili mancanti)."""
    mancanti: list[str] = []

    def sostituisci(match: re.Match) -> str:
        nome = match.group(1)
        valore = os.environ.get(nome)
        if valore is None:
            if nome not in mancanti:
                mancanti.append(nome)
            return ""
        return valore

    return PLACEHOLDER.sub(sostituisci, testo), mancanti


def main() -> None:
    reso, mancanti = rendi(sys.stdin.read())
    if mancanti:
        sys.exit(
            "render_manifest: variabili non impostate: " + ", ".join(mancanti)
        )
    sys.stdout.write(reso)


if __name__ == "__main__":
    main()
