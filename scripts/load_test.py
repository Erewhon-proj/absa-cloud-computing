"""Generatore di traffico per testare il disaccoppiamento asincrono.

Invia N recensioni in parallelo all'endpoint POST /reviews dell'API.
Sotto Kubernetes/ASG questo carico fa crescere la coda e innesca lo scaling.

Uso:
    python scripts/load_test.py --url http://localhost:8000 --n 200 --concurrency 20
"""
import argparse
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BANKS = ["Fineco", "Revolut", "BBVA", "Intesa", "Unicredit", "N26"]

SAMPLES = [
    "L'app e' comodissima e i bonifici sono velocissimi.",
    "Assistenza pessima, ho aspettato 40 minuti al call center.",
    "Conto a canone zero, nessuna commissione: ottimo.",
    "La carta non funziona e nessuno mi aiuta, vergogna.",
    "Apertura conto facile e veloce, consiglio.",
    "Costi troppo alti e bonifici lenti, deluso.",
    "Interfaccia dell'app chiara ma i tempi di accredito sono lenti.",
    "Operatore gentile e professionale, problema risolto subito.",
    "Commissioni nascoste sul bonifico, esperienza scarsa.",
    "Tutto perfetto: app veloce, assistenza efficiente, costi bassi.",
]


def send_one(url: str) -> int:
    payload = {
        "text": random.choice(SAMPLES),
        "bank": random.choice(BANKS),
    }
    r = requests.post(f"{url}/reviews", json=payload, timeout=15)
    return r.status_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    start = time.time()
    ok = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(send_one, args.url) for _ in range(args.n)]
        for fut in as_completed(futures):
            try:
                if fut.result() == 202:
                    ok += 1
            except Exception as exc:  # noqa: BLE001
                print("Errore:", exc)

    elapsed = time.time() - start
    print(f"Inviate {ok}/{args.n} recensioni in {elapsed:.1f}s "
          f"({args.n / elapsed:.0f} req/s)")


if __name__ == "__main__":
    main()
