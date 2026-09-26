#!/usr/bin/env bash
# Spegne tutta la Fase A: namespace, KEDA, stack Compose e immagini locali.
set -euo pipefail

cd "$(dirname "$0")/.."

CONTESTO_ATTESO="${KUBE_CONTEXT:-orbstack}"

# L'inverso del controllo in aws_teardown.sh: qui il rischio è di cancellare
# namespace e KEDA su EKS credendo di essere in locale.
CONTESTO="$(kubectl config current-context)"
case "$CONTESTO" in
    arn:aws:eks:*)
        echo "Contesto kubectl attuale: $CONTESTO" >&2
        echo "È un cluster EKS" >&2
        echo "Passa al cluster locale con:" >&2
        echo "  kubectl config use-context $CONTESTO_ATTESO" >&2
        exit 1
        ;;
esac
echo ">> Contesto: $CONTESTO"

echo ">> Rimuovo il namespace (deployment, service, PVC e dati locali)"
kubectl delete namespace absa-cloud --ignore-not-found --wait=true

echo ">> Distruggo il namespace gestito da Terraform"
terraform -chdir=terraform/local destroy -auto-approve

# KEDA lo installa il playbook con kubectl apply, quindi Terraform non lo vede.
echo ">> Disinstallo KEDA"
kubectl delete -f https://github.com/kedacore/keda/releases/download/v2.14.0/keda-2.14.0.yaml --ignore-not-found

echo ">> Fermo lo stack Docker Compose"
docker compose down --volumes --remove-orphans

# Le immagini le ricostruisce il playbook al prossimo avvio.
echo ">> Rimuovo le immagini del progetto e la cache di build"
docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E '^(absa|absa-cloud)-(api|worker|frontend):' \
    | xargs -r docker rmi -f
docker builder prune -f

echo ">> Verifica"
kubectl get namespace absa-cloud --ignore-not-found
kubectl get pods -n keda --ignore-not-found
docker images --filter reference='absa*'
