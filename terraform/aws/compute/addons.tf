# KEDA: autoscaling del worker pilotato dalla lunghezza della coda SQS.
# Il ServiceAccount dell'operator viene annotato con il ruolo IRSA cosi' KEDA
# puo' leggere ApproximateNumberOfMessages senza credenziali statiche.
resource "helm_release" "keda" {
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = "2.14.2"
  namespace        = "keda"
  create_namespace = true

  set {
    name  = "serviceAccount.operator.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.keda.arn
  }

  depends_on = [module.eks]
}
