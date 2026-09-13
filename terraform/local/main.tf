terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

# Nome del cluster nel kubeconfig. OrbStack lo chiama "orbstack",
# Docker Desktop "docker-desktop". Lo passa il playbook Ansible.
variable "kube_context" {
  type    = string
  default = "orbstack"
}

provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = var.kube_context
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
