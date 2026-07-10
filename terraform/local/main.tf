terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = "orbstack" # Config di def. di OrbStack
}

resource "kubernetes_namespace" "absa_cloud" {
  metadata {
    name = "absa-cloud"
    labels = {
      environment = "local"
      project     = "absa"
    }
  }
}
