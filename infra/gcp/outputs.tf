output "project_id" {
  value = var.project_id
}
output "release_sha256" {
  value = local.release_sha256
}
output "instance_name" {
  value = var.deploy_runtime ? google_compute_instance.demo[0].name : null
}
output "zone" {
  value = var.zone
}
output "runtime_service_account" {
  value = google_service_account.runtime.email
}
output "jev_secret_name" {
  value = google_secret_manager_secret.jev.id
}
output "data_disk_name" {
  value = google_compute_disk.state.name
}
output "access_command" {
  value = "gcloud compute start-iap-tunnel ${var.name} 8080 --local-host-port=127.0.0.1:8765 --project=${var.project_id} --zone=${var.zone}"
}
