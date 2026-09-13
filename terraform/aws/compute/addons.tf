# KEDA: autoscaling del worker in base alla lunghezza della coda SQS.
resource "helm_release" "keda" {
  name       = "keda"
  repository = "https://kedacore.github.io/charts"
  chart      = "keda"
  # Versione del chart Helm, non di KEDA: il chart 2.14.2 installa KEDA 2.14.0,
  # la stessa del manifest usato in locale da ansible/local/playbook.yml.
  version          = "2.14.2"
  namespace        = "keda"
  create_namespace = true

  # Salva l'ARN del ruolo IAM durante l'installazione
  set {
    name  = "serviceAccount.operator.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.keda.arn
  }

  depends_on = [module.eks]
}
