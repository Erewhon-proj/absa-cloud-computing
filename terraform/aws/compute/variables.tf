variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "project" {
  type    = string
  default = "absa"
}

variable "cluster_name" {
  type    = string
  default = "absa-cluster"
}

variable "kubernetes_version" {
  type    = string
  default = "1.34"
}

variable "node_instance_type" {
  type        = string
  default     = "m7i-flex.large"
  description = <<-EOT
    Solo CPU (vincolo budget: niente GPU). 2 vCPU / 8 GiB: la RAM serve per il
    modello reale (BERT + PyTorch), e ci stanno due worker per nodo.
    Deve essere free-tier eligible: l'account è sul piano Free, che rifiuta
    gli altri con "instance type is not eligible for Free Tier".
  EOT
}

variable "node_desired" {
  type        = number
  default     = 3
  description = "Nodi alla creazione del cluster. Terraform lo usa solo la prima volta: il modulo EKS ignora le modifiche successive."
}

variable "node_min" {
  type    = number
  default = 1
}

variable "node_max" {
  type    = number
  default = 4
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "db_name" {
  type    = string
  default = "absa"
}

variable "db_username" {
  type    = string
  default = "absa_app"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "Password del DB RDS (fornire via tfvars o variabile d'ambiente TF_VAR_db_password)."

  validation {
    condition     = can(regex("^[A-Za-z0-9_.~-]{8,128}$", var.db_password))
    error_message = "db_password: usa 8-128 caratteri tra lettere, cifre e _ . ~ - (niente : # % ? & @ / spazi, che romperebbero DATABASE_URL/YAML)."
  }
}

variable "model_bucket_name" {
  type        = string
  description = "Nome del bucket S3 del modello, creato dallo stack persistent."
}

variable "namespace" {
  type    = string
  default = "absa-cloud"
}
