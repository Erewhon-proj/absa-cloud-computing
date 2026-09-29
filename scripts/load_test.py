"""Generatore di traffico per testare il disaccoppiamento asincrono.

Invia N recensioni in parallelo all'endpoint POST /reviews dell'API.
Sotto Kubernetes/ASG questo carico fa crescere la coda e innesca lo scaling.

Uso:
    python scripts/load_test.py --url http://localhost:8000 --n 200 --concurrency 20

Senza --url cerca il cluster EKS tra i context di kubectl e usa il LoadBalancer
dell'API; se non lo trova usa localhost.

Di default pesca a caso tra le 10 recensioni di esempio qui sotto. Con
--csv file.csv (colonne bank,text) usa invece le recensioni del file, senza
ripetizioni.
"""
import argparse
import csv
import random
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BANKS = ["Fineco", "Revolut", "BBVA", "Intesa", "Unicredit", "N26"]

SAMPLES = [
    "L'app è comodissima e i bonifici sono velocissimi.",
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


def build_payloads(n: int, csv_path: str | None) -> list[dict]:
    if not csv_path:
        return [{"text": random.choice(SAMPLES), "bank": random.choice(BANKS)}
                for _ in range(n)]

    with open(csv_path, encoding="utf-8") as f:
        reviews = [{"text": r["text"], "bank": r["bank"]} for r in csv.DictReader(f)]
    random.shuffle(reviews)
    if n > len(reviews):
        print(f"Nel file ci sono solo {len(reviews)} recensioni: ne invio {len(reviews)}")
    return reviews[:n]


def send_one(url: str, payload: dict) -> int:
    r = requests.post(f"{url}/reviews", json=payload, timeout=15)
    return r.status_code


def find_url() -> str:
    try:
        contexts = subprocess.run(["kubectl", "config", "get-contexts", "-o", "name"],
                                  capture_output=True, text=True).stdout.split()
        eks = [c for c in contexts if c.endswith("cluster/absa-cluster")]
        if eks:
            host = subprocess.run(
                ["kubectl", "--context", eks[0], "-n", "absa-cloud", "get", "svc", "api",
                 "-o", "jsonpath={.status.loadBalancer.ingress[0].hostname}"],
                capture_output=True, text=True).stdout.strip()
            if host:
                return f"http://{host}:8000"
    except FileNotFoundError:
        pass
    return "http://localhost:8000"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--csv", help="file con colonne bank,text")
    args = parser.parse_args()
    if not args.url:
        args.url = find_url()
    print("Invio a", args.url)

    payloads = build_payloads(args.n, args.csv)
    args.n = len(payloads)

    start = time.time()
    ok = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(send_one, args.url, p) for p in payloads]
        for fut in as_completed(futures):
            try:
                if fut.result() == 202:
                    ok += 1
            except requests.RequestException as exc:
                print("Errore:", exc)

    elapsed = time.time() - start
    print(f"Inviate {ok}/{args.n} recensioni in {elapsed:.1f}s "
          f"({args.n / elapsed:.0f} req/s)")


if __name__ == "__main__":
    main()
