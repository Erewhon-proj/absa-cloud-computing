variable "aws_region" {
  type        = string
  default     = "eu-west-1"
  description = "Regione AWS."
}

variable "project" {
  type        = string
  default     = "absa"
  description = "Prefisso per i nomi delle risorse."
}

variable "model_bucket_name" {
  type        = string
  description = "Nome (globalmente unico) del bucket S3 per il checkpoint del modello."
}

variable "budget_notify_email" {
  type        = string
  description = "Email a cui inviare gli alert di AWS Budgets."
}

variable "budget_limit" {
  type        = string
  default     = "150"
  description = "Teto mensile del budget (nella valuta dell'account)."
}

variable "budget_currency" {
  type        = string
  default     = "USD"
  description = "Valuta del budget di default"
}
