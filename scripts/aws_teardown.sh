#!/usr/bin/env bash
# Spegne la parte a pagamento della Fase B (EKS, RDS, NAT, VPC).
# Lascia in piedi lo stack persistent (S3, ECR, Budget): costa pochi centesimi
# ed evita di ricaricare il modello da 450 MB a ogni sessione.
set -euo pipefail

cd "$(dirname "$0")/.."

REGIONE="${AWS_REGION:-eu-west-1}"

# Il primo comando cancella un namespace: se il kubeconfig punta ancora al
# cluster locale invece che a EKS, si porterebbe via l'ambiente di sviluppo.
# I contesti creati da `aws eks update-kubeconfig` sono ARN, quelli locali no.
CONTESTO="$(kubectl config current-context)"
case "$CONTESTO" in
    arn:aws:eks:*) ;;
    *)
        echo "Contesto kubectl attuale: $CONTESTO" >&2
        echo "Non è un cluster EKS: mi fermo prima di cancellare qualcosa." >&2
        echo "Passa al cluster con:" >&2
        echo "  aws eks update-kubeconfig --name <cluster> --region $REGIONE" >&2
        exit 1
        ;;
esac
echo ">> Contesto: $CONTESTO"

# Prima i Service LoadBalancer: gli ELB li crea Kubernetes, non Terraform, e se
# restano appesi il destroy della VPC fallisce perché la trova ancora in uso.
echo ">> Rimuovo i manifest (e con loro gli ELB)"
kubectl delete namespace absa-cloud --ignore-not-found --wait=true

echo ">> Distruggo lo stack compute"
terraform -chdir=terraform/aws/compute destroy -auto-approve

echo ">> Verifica: non deve restare nulla"
aws eks list-clusters --region "$REGIONE"
aws rds describe-db-instances --region "$REGIONE" --query 'DBInstances[].DBInstanceIdentifier'
