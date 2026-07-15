output "model_bucket" {
  value       = aws_s3_bucket.model.bucket
  description = "Nome del bucket S3 del modello."
}

output "model_bucket_arn" {
  value = aws_s3_bucket.model.arn
}

output "ecr_repository_urls" {
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
  description = "URL dei repository ECR, usati dalla CI per il push."
}

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions_ecr_push.arn
  description = "Da impostare come secret AWS_ECR_PUSH_ROLE_ARN nel repo GitHub."
}
