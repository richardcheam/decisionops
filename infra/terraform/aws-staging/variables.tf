variable "region" {
  type    = string
  default = "eu-west-3"
}

variable "name" {
  type    = string
  default = "decisionops-staging"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Use a short lowercase resource prefix."
  }
}

variable "vpc_id" {
  type        = string
  description = "Existing reviewed VPC; this module does not create NAT or public ingress."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "At least two private subnets in distinct availability zones with approved EKS/ECR egress."
  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "Supply at least two private subnets."
  }
}

variable "kubernetes_version" {
  type        = string
  description = "Select a currently supported EKS version after staging authorization."
  validation {
    condition     = can(regex("^1\\.[0-9]{2}$", var.kubernetes_version))
    error_message = "Specify an EKS major.minor version."
  }
}

variable "cluster_admin_role_arn" {
  type        = string
  description = "Explicit operator IAM role for private-cluster access; not an application identity."
}

variable "backup_bucket_name" {
  type        = string
  description = "Globally unique private backup bucket name; no actual account identifier is checked in."
}
