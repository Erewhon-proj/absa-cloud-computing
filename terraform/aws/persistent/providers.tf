provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "absa-cloud"
      ManagedBy = "terraform"
      Stack     = "persistent"
    }
  }
}
