resource "google_project_service" "gateway" {
  for_each           = toset(["run.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com"])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}
resource "google_artifact_registry_repository" "gateway" {
  location      = var.region
  repository_id = var.name
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.gateway]
}
resource "google_service_account" "build" {
  account_id   = "${var.name}-build"
  display_name = "REQLOX gateway build only"
}
resource "google_service_account" "gateway" {
  account_id   = "${var.name}-gateway"
  display_name = "REQLOX owner gateway"
}
resource "google_storage_bucket" "build" {
  name                        = "${var.project_id}-${var.name}-buildsource"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels
  force_destroy               = false
}
resource "google_storage_bucket_iam_member" "build_read" {
  bucket = google_storage_bucket.build.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"
}
resource "google_artifact_registry_repository_iam_member" "build_write" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.gateway.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.build.email}"
}
resource "google_project_iam_member" "build_log" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.build.email}"
}
resource "google_secret_manager_secret_iam_member" "gateway_read" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.owner.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.gateway.email}"
}
resource "google_compute_firewall" "gateway" {
  name                    = "${var.name}-gateway"
  network                 = google_compute_network.web.name
  direction               = "INGRESS"
  source_ranges           = ["10.83.1.0/26"]
  target_service_accounts = [google_service_account.runtime.email]
  allow {
    protocol = "tcp"
    ports    = ["8081"]
  }
}
resource "google_compute_subnetwork" "gateway" {
  name                     = "${var.name}-gateway"
  region                   = var.region
  network                  = google_compute_network.web.id
  ip_cidr_range            = "10.83.1.0/26"
  private_ip_google_access = true
}
resource "google_cloud_run_v2_service" "gateway" {
  client              = var.gateway_deployment_client
  client_version      = var.gateway_deployment_client_version
  count               = var.deploy_gateway ? 1 : 0
  name                = "${var.name}-gateway"
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"
  template {
    service_account                  = google_service_account.gateway.email
    timeout                          = "120s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.web.name
        subnetwork = google_compute_subnetwork.gateway.name
        tags       = ["reqlox-web-gateway"]
      }
    }
    volumes {
      name = "owner"
      secret {
        secret = google_secret_manager_secret.owner.secret_id
        items {
          version = var.owner_secret_version
          path    = "password"
          mode    = 292
        }
      }
    }
    containers {
      image = var.gateway_image
      resources {
        limits   = { cpu = "1", memory = "256Mi" }
        cpu_idle = true
      }
      env {
        name  = "PUBLIC_HOST"
        value = var.domain
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.assets.name
      }
      env {
        name  = "BACKEND_URL"
        value = "http://10.83.0.10:8081"
      }
      env {
        name  = "RELEASE_SHA256"
        value = local.digest
      }
      startup_probe {
        period_seconds    = 10
        timeout_seconds   = 5
        failure_threshold = 12
        http_get {
          path = "/__ready"
          port = 8080
        }
      }
      volume_mounts {
        name       = "owner"
        mount_path = "/var/run/secrets/owner"
      }
    }
  }
  lifecycle {
    precondition {
      condition     = var.gateway_image != "" && var.owner_secret_version != ""
      error_message = "Pin the verified container and owner credential before deployment."
    }
  }
  depends_on = [google_project_service.gateway, google_secret_manager_secret_iam_member.gateway_read, google_compute_firewall.gateway]
}
resource "google_cloud_run_v2_service_iam_member" "gateway" {
  count    = var.deploy_gateway ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.gateway[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
