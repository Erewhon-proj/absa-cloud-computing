# Coda principale + Dead Letter Queue. 
# La lunghezza della coda principale è la metrica che KEDA usa per scalare i worker (0 -> N).
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project}-reviews-dlq"
  message_retention_seconds = 1209600 # 14 giorni
}

resource "aws_sqs_queue" "reviews" {
  name                       = "${var.project}-reviews"
  visibility_timeout_seconds = 300 # 5 minuti
  message_retention_seconds  = 345600 # 4 giorni

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}
