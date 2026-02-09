terraform {
  backend "s3" {
    bucket         = "logicall-ai-terraform-state-494777943750"
    key            = "eks/terraform.tfstate"
    region         = "us-west-2"
    dynamodb_table = "Shingo8843"
    encrypt        = true
  }
}

