data "aws_availability_zones" "available" {
  state = "available"
}

# Il bucket del modello e' gestito dallo stack "persistent": qui lo referenziamo
# solo per ricavarne l'ARN (policy IRSA del worker).
data "aws_s3_bucket" "model" {
  bucket = var.model_bucket_name
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}
