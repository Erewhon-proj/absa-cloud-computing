# Cluster EKS gestito con un node group di istanze CPU (t3.medium).
# Il modulo crea l'OIDC provider necessario a IRSA (enable_irsa di default).
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.8"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  cluster_endpoint_public_access = true

  # Dà all'utente che esegue terraform i permessi admin sul cluster (kubectl).
  enable_cluster_creator_admin_permissions = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_instance_type]
      capacity_type  =   "SPOT" # "ON_DEMAND"
      desired_size   = var.node_desired
      min_size       = var.node_min
      max_size       = var.node_max
    }
  }
}
