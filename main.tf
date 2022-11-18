terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "2.15.0"
    }
  }
}
#variable block
variable region {
 default = "us-east-1"
}

#provider block 
provider aws {
 region = var.region
}

provider "docker" {
  # version = "~> 2.7"
  host    = "npipe:////.//pipe//docker_engine"
  registry_auth {
    address = "${data.aws_caller_identity.current.account_id}.dkr.${var.region}.amazonaws.com/newgit2.1-demo-lambda-container:latest"
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}

#data block
data "aws_ecr_authorization_token" "token" {} 
data aws_caller_identity current {}
 
locals {
 prefix = "newgit2.1"
 account_id          = data.aws_caller_identity.current.account_id
 ecr_repository_name = "${local.prefix}-demo-lambda-container"
 ecr_image_tag       = "latest"
}

#resource block
#creating ecr repo 
resource aws_ecr_repository repo {
 name = local.ecr_repository_name
}

resource "aws_ecr_repository_policy" "demo-repo-policy" {
  repository = aws_ecr_repository.repo.name
  policy     = <<EOF
  {
    "Version": "2008-10-17",
    "Statement": [
      {
        "Sid": "adds full ecr access to the demo repository",
        "Effect": "Allow",
        "Principal": "*",
        "Action": [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:GetDownloadUrlForLayer",
          "ecr:GetLifecyclePolicy",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart"
        ]
      }
    ]
  }
  EOF
}

#creating null resource : build docker container and push to ecr , teriggers if lambda func code is changed and helps to rebuild the image and update the lambda func
resource null_resource ecr_image {
 triggers = {
   python_file = md5(file("${path.module}/lambdas/app.py"))
   docker_file = md5(file("${path.module}/lambdas/Dockerfile"))
 }
 
#  provisioner "local-exec" {
#    command = <<-EOT
#            aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${local.account_id}.dkr.ecr.${var.region}.amazonaws.com
#            cd ${path.module}/lambdas/git_client
#            docker build -t ${local.ecr_repository_name} .
#            docker tag ${local.ecr_repository_name}:${local.ecr_image_tag} ${local.account_id}.dkr.ecr.${var.region}.amazonaws.com/${local.ecr_repository_name}:${local.ecr_image_tag} 
#            docker push ${local.account_id}.dkr.ecr.${var.region}.amazonaws.com/${local.ecr_repository_name}:${local.ecr_image_tag}
#        EOT
#  }
}
#            docker build -t ${local.account_id}.dkr.ecr.${var.region}.amazonaws.com/${local.ecr_repository_name}:${local.ecr_image_tag} . 
#Build docker image and push to ECR

resource "docker_registry_image" "lambda-image" {
  name = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com/newgit2.1-demo-lambda-container:latest"

  build{
    context = "lambdas"
    dockerfile = "Dockerfile"
  }
  
}
 
data aws_ecr_image lambda_image {
 depends_on = [
   null_resource.ecr_image
 ]
 repository_name = local.ecr_repository_name
 image_tag       = local.ecr_image_tag
}
 
resource aws_iam_role lambda {
 name = "${local.prefix}-lambda-role"
 assume_role_policy = <<EOF
{
   "Version": "2012-10-17",
   "Statement": [
       {
           "Action": "sts:AssumeRole",
           "Principal": {
               "Service": "lambda.amazonaws.com"
           },
           "Effect": "Allow"
       }
   ]
}
 EOF
}
 
data aws_iam_policy_document lambda {
   statement {
     actions = [
         "logs:CreateLogGroup",
         "logs:CreateLogStream",
         "logs:PutLogEvents"
     ]
     effect = "Allow"
     resources = [ "*" ]
     sid = "CreateCloudWatchLogs"
   }

}
 
resource aws_iam_policy lambda {
   name = "${local.prefix}-lambda-policy"
   path = "/"
   policy = data.aws_iam_policy_document.lambda.json
}
 
resource aws_lambda_function git {
 depends_on = [
   null_resource.ecr_image
 ]
 function_name = "ecr-lambda"
 role = aws_iam_role.lambda.arn
 timeout = 300
 image_uri = "${aws_ecr_repository.repo.repository_url}@${data.aws_ecr_image.lambda_image.id}"
 package_type = "Image"
}
 
output "lambda_name" {
 value = aws_lambda_function.git.id
}