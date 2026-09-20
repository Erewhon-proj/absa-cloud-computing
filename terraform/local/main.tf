# Configurazione Terraform per l'ambiente locale (Fase A)
# Crea il namespace dedicato sul cluster Kubernetes locale

terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

# Contesto Kubernetes locale (es. orbstack, docker-desktop o minikube)
variable "kube_context" {
  type    = string
  default = "orbstack"
}

provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = var.kube_context
}

# Namespace per isolare tutte le risorse del progetto
resource "kubernetes_namespace" "absa_cloud" {
  metadata {
    name = "absa-cloud"
    labels = {
      environment = "local"
      project     = "absa"
    }
  }
}

