# Elenco dei datacennter attivi -> prendi i primi due
data "aws_availability_zones" "available" {
  state = "available"
}

# Salva l'ARN del bucket per il worker
data "aws_s3_bucket" "model" {
  bucket = var.model_bucket_name
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}
