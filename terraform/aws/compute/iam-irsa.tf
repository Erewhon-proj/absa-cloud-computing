# IRSA: ruoli IAM assumibili dai ServiceAccount dei pod via OIDC.
# - api    -> invia messaggi su SQS
# - worker -> consuma da SQS + legge il modello da S3
# - keda   -> legge la lunghezza coda per lo scaling (SA keda-operator nel ns "keda")
locals {
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = replace(module.eks.cluster_oidc_issuer_url, "https://", "")
}

# Genera la trust policy OIDC per un dato ServiceAccount (namespace + nome).
data "aws_iam_policy_document" "irsa_assume" {
  for_each = {
    api    = "system:serviceaccount:${var.namespace}:absa-api"
    worker = "system:serviceaccount:${var.namespace}:absa-worker"
    keda   = "system:serviceaccount:keda:keda-operator"
  }

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider_url}:sub"
      values   = [each.value]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

# --- Ruolo API: sqs:SendMessage ---
resource "aws_iam_role" "api" {
  name               = "${var.project}-api-irsa"
  assume_role_policy = data.aws_iam_policy_document.irsa_assume["api"].json
}

resource "aws_iam_role_policy" "api_sqs" {
  name = "sqs-send"
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage", "sqs:GetQueueUrl", "sqs:GetQueueAttributes"] # azioni permesse
      Resource = aws_sqs_queue.reviews.arn
    }]
  })
}

# --- Ruolo Worker: consuma da SQS + legge il modello da S3 ---
resource "aws_iam_role" "worker" {
  name               = "${var.project}-worker-irsa"
  assume_role_policy = data.aws_iam_policy_document.irsa_assume["worker"].json
}

resource "aws_iam_role_policy" "worker" {
  name = "sqs-consume-s3-read"
  role = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:DeleteMessageBatch",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
        ]
        Resource = aws_sqs_queue.reviews.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [data.aws_s3_bucket.model.arn, "${data.aws_s3_bucket.model.arn}/*"]
      },
    ]
  })
}

# --- Ruolo KEDA: legge gli attributi della coda per lo scaling ---
resource "aws_iam_role" "keda" {
  name               = "${var.project}-keda-irsa"
  assume_role_policy = data.aws_iam_policy_document.irsa_assume["keda"].json
}

resource "aws_iam_role_policy" "keda_sqs" {
  name = "sqs-read"
  role = aws_iam_role.keda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:GetQueueAttributes"]
      Resource = aws_sqs_queue.reviews.arn
    }]
  })
}
