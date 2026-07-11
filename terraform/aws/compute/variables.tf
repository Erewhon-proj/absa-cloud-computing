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
  # 1.30 esce dall'extended support EKS il 23/07/2026: usiamo una versione
  # piu' recente per non ricreare cluster gia' scaduti (e non pagare l'extended).
  default = "1.33"
}

variable "node_instance_type" {
  type        = string
  default     = "m7i-flex.large"
  description = <<-EOT
    Solo CPU (vincolo budget: niente GPU). 2 vCPU / 8 GiB: la RAM serve per il
    modello reale (BERT + PyTorch), e ci stanno due worker per nodo.
    Deve essere free-tier eligible: l'account e' sul piano Free, che rifiuta
    gli altri con "instance type is not eligible for Free Tier".
  EOT
}

variable "node_desired" {
  type    = number
  default = 2
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
  default = "absa_app" # ruolo applicativo; distinto dal nome del DB ("absa")
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "Password del DB RDS (fornire via tfvars o variabile d'ambiente TF_VAR_db_password)."

  # La password finisce dentro DATABASE_URL (postgresql://user:PASS@host/db) e nel
  # Secret K8s: limitiamo ai caratteri sicuri sia per una URL sia per YAML, cosi'
  # non serve URL-encoding e il rendering del manifest non si rompe.
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
