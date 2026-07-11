output "cluster_name" {
  value = module.eks.cluster_name
}

output "region" {
  value = var.aws_region
}

output "namespace" {
  value = var.namespace
}

output "sqs_queue_url" {
  value = aws_sqs_queue.reviews.url
}

output "sqs_queue_arn" {
  value = aws_sqs_queue.reviews.arn
}

output "rds_endpoint" {
  value = aws_db_instance.postgres.endpoint
}

# DATABASE_URL pronto all'uso per il Secret K8s (include host:porta).
output "database_url" {
  value     = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.endpoint}/${var.db_name}"
  sensitive = true
}

output "api_role_arn" {
  value       = aws_iam_role.api.arn
  description = "Da annotare sul ServiceAccount absa-api."
}

output "worker_role_arn" {
  value       = aws_iam_role.worker.arn
  description = "Da annotare sul ServiceAccount absa-worker."
}
