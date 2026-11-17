output "cluster_name" {
  value = aws_eks_cluster.staging.name
}

output "database_endpoint" {
  value = aws_db_instance.staging.address
}

output "database_secret_arn" {
  description = "Reference only; retrieve with separately authorized operator tooling."
  value       = aws_db_instance.staging.master_user_secret[0].secret_arn
}

output "repository_urls" {
  value = { for name, repo in aws_ecr_repository.application : name => repo.repository_url }
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.id
}
