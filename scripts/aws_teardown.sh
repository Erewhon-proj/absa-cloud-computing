#!/usr/bin/env bash
# Spegne la parte a pagamento della Fase B (EKS, RDS, NAT, VPC).
# Lascia in piedi lo stack persistent (S3, ECR, Budget): costa pochi centesimi
# ed evita di ricaricare il modello da 450 MB a ogni sessione.
set -euo pipefail

cd "$(dirname "$0")/.."

# Prima i Service LoadBalancer: gli ELB li crea Kubernetes, non Terraform, e se
# restano appesi il destroy della VPC fallisce perche' la trova ancora in uso.
echo ">> Rimuovo i manifest (e con loro gli ELB)"
kubectl delete namespace absa-cloud --ignore-not-found --wait=true

echo ">> Distruggo lo stack compute"
terraform -chdir=terraform/aws/compute destroy -auto-approve

echo ">> Verifica: non deve restare nulla"
aws eks list-clusters --region eu-west-1
aws rds describe-db-instances --region eu-west-1 --query 'DBInstances[].DBInstanceIdentifier'
