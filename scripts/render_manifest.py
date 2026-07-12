#!/usr/bin/env python3
"""Risolve i placeholder ${VAR} di un manifest K8s con le variabili d'ambiente.

Regola unica: ogni ${VAR} viene sostituito con la variabile d'ambiente omonima.
Le variabili *runtime* dei container si scrivono SENZA graffe ($MODEL_MODE,
$DATABASE_URL, ...): la regex non le tocca, quindi restano intatte per la shell
del container. Equivalente portabile di `envsubst`, ma in python3 (presente ovunque).

Uso:
    cat k8s/aws/01-config.yaml | python3 scripts/render_manifest.py | kubectl apply -f -
"""
import os
import re
import sys


def _replace(match: "re.Match") -> str:
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        # Variabile attesa ma non impostata: avvisa, ma non bloccare il deploy.
        sys.stderr.write(f"ATTENZIONE: variabile ${{{name}}} non impostata\n")
        return ""
    return value


def main() -> None:
    # \$\{(\w+)\} cattura solo i placeholder con graffe; le var runtime ($VAR,
    # senza graffe) non fanno match e passano intatte.
    sys.stdout.write(re.sub(r"\$\{(\w+)\}", _replace, sys.stdin.read()))


if __name__ == "__main__":
    main()
