output "public_url" { value = "https://${var.domain}" }
output "assets_bucket" { value = google_storage_bucket.assets.name }
output "release_sha256" { value = local.digest }
output "owner_login_secret" { value = google_secret_manager_secret.owner.id }
output "instance_name" { value = var.name }
output "gateway_url" { value = var.deploy_gateway ? google_cloud_run_v2_service.gateway[0].uri : null }
