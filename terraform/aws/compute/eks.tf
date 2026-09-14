# Cluster EKS gestito con un node group di sole istanze CPU.
# Il modulo crea l'OIDC provider necessario a IRSA (enable_irsa di default).
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.8"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  # Creazione endpoint sicuro per l'accesso
  cluster_endpoint_public_access = true

  # Dà all'utente che esegue terraform i permessi admin sul cluster (kubectl).
  enable_cluster_creator_admin_permissions = true

  # Collegamento alla nostro vpc
  vpc_id = module.vpc.vpc_id

  # I nodi si avviano dentro la sub privata -> nessun ip pubblico
  subnet_ids = module.vpc.private_subnets

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_instance_type]
      capacity_type  = "SPOT" # oppure "ON_DEMAND"
      desired_size   = var.node_desired
      min_size       = var.node_min
      max_size       = var.node_max
    }
  }
}
