# Autenticazione di GitHub Actions verso AWS tramite OIDC.


# Si legge la configurazione OIDC pubblicata da GitHub
# per estrarne l'impronta del certificato TLS, usata sotto per registrarlo.
data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

# Si dichiara GitHub identity provider di fiducia per questo account AWS:

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

# Trust policy
# Due filtri sul contenuto del token: il destinatario (`aud`) e l'identità
# della workflow run (`sub`).
data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Solo il branch main del repo indicato. GitHub per questo repo scrive il
    # nome con gli ID numerici accodati (repo:owner@123/nome@456:ref:...), per
    # questo c'è anche la seconda forma: "@*" sostituisce solo i numeri.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repo}:ref:refs/heads/main",
        "repo:${split("/", var.github_repo)[0]}@*/${split("/", var.github_repo)[1]}@*:ref:refs/heads/main",
      ]
    }
  }
}

# Il suo ARN finisce nel secret usato dal job build-and-push in .github/workflows/ci.yml.
resource "aws_iam_role" "github_actions_ecr_push" {
  name               = "${var.project}-github-actions-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

# I permessi di cosa può fare la pipeline.
data "aws_iam_policy_document" "ecr_push" {
  # Restituisce la password temporanea per il `docker login` al registry.
  # GetAuthorizationToken non supporta permessi a livello di risorsa: va su "*".
  statement {
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
    ]
    resources = [for r in aws_ecr_repository.this : r.arn]
  }
}

# Policy agganciata inline al ruolo così nasce e muore con esso.
resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_actions_ecr_push.id
  policy = data.aws_iam_policy_document.ecr_push.json
}
