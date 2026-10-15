data "google_project" "target" { project_id = var.project_id }
locals {
  initial_release_archive = var.initial_release_archive != "" ? var.initial_release_archive : var.release_archive
  labels                  = { application = "reqlox", managed_by = "terraform", purpose = "bounded-web" }
  digest                  = filesha256(var.release_archive)
  static_files            = toset(["index.html", "study.html", "knowledge.html", "app.js", "study.js", "knowledge.js", "style.css", "targets.html", "targets.js", "targets.css", "records.html", "records.js", "workspace.js", "workspace.css", "public-demo.html", "public-demo.js", "public-demo.css", "public-demo.json"])
  runtime = jsonencode({
    project_id          = var.project_id, project_number = data.google_project.target.number,
    host_id             = var.name, release_sha256 = local.digest,
    artifact_bucket     = var.release_bucket, artifact_object = "releases/${local.digest}.tar.gz",
    jev_secret_resource = "projects/${var.project_id}/secrets/reqlox-jev-api-key/versions/1",
    lease_seconds       = var.lease_seconds, application_port = 8765,
    access              = "CLOUDFLARE_OWNER_LOGIN", paid_model_calls_enabled = false,
    data_disk           = "${var.name}-state", database_backend = "SQLITE",
    web = {
      frontend_mode          = var.frontend_mode,
      public_origin          = "https://${var.domain}", authentication = "OWNER_BASIC_AUTH",
      assets_bucket          = google_storage_bucket.assets.name,
      owner_secret_resource  = "projects/${var.project_id}/secrets/${google_secret_manager_secret.owner.secret_id}/versions/${var.owner_secret_version}",
      tunnel_secret_resource = "projects/${var.project_id}/secrets/${google_secret_manager_secret.tunnel.secret_id}/versions/${var.tunnel_secret_version}",
      cloudflared_url        = var.cloudflared_url, cloudflared_sha256 = var.cloudflared_sha256
    }
  })
}
resource "google_service_account" "runtime" {
  account_id   = "${var.name}-runtime"
  display_name = "REQLOX isolated Web runtime"
}
resource "google_compute_network" "web" {
  name                    = var.name
  auto_create_subnetworks = false
}
resource "google_compute_subnetwork" "web" {
  name                     = var.name
  region                   = var.region
  network                  = google_compute_network.web.id
  ip_cidr_range            = "10.83.0.0/24"
  private_ip_google_access = true
}
resource "google_compute_firewall" "iap" {
  name                    = "${var.name}-iap-ui"
  network                 = google_compute_network.web.name
  direction               = "INGRESS"
  source_ranges           = ["35.235.240.0/20"]
  target_service_accounts = [google_service_account.runtime.email]
  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }
}
# This bucket contains exactly fourteen public source assets. Runtime state and
# private releases are never made public or copied here.
resource "google_storage_bucket" "assets" {
  name                        = "${var.project_id}-${var.name}-assets"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "inherited"
  force_destroy               = false
  labels                      = local.labels
}
resource "google_storage_bucket_object" "asset" {
  for_each      = local.static_files
  name          = each.key
  bucket        = google_storage_bucket.assets.name
  source        = "${var.static_directory}/${each.key}"
  content_type  = endswith(each.key, ".html") ? "text/html; charset=utf-8" : endswith(each.key, ".js") ? "text/javascript; charset=utf-8" : "text/css; charset=utf-8"
  cache_control = "no-store"
}
resource "google_storage_bucket_iam_member" "public_assets" {
  bucket     = google_storage_bucket.assets.name
  role       = "roles/storage.objectViewer"
  member     = "allUsers"
  depends_on = [google_storage_bucket_object.asset]
}
resource "google_storage_bucket_object" "release" {
  name   = "releases/${filesha256(local.initial_release_archive)}.tar.gz"
  bucket = var.release_bucket
  source = local.initial_release_archive
}
resource "google_storage_bucket_object" "release_updates" {
  for_each = { for digest, path in merge(var.retained_release_archives, { (local.digest) = var.release_archive }) : digest => path if digest != filesha256(local.initial_release_archive) }
  name     = "releases/${each.key}.tar.gz"
  bucket   = var.release_bucket
  source   = each.value
}
resource "google_storage_bucket_iam_member" "runtime_read" {
  bucket = var.release_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_secret_manager_secret" "tunnel" {
  secret_id = "${var.name}-tunnel-token"
  labels    = local.labels
  replication {
    auto {}
  }
  lifecycle { prevent_destroy = true }
}
resource "google_secret_manager_secret" "owner" {
  secret_id = "${var.name}-owner-login"
  labels    = local.labels
  replication {
    auto {}
  }
  lifecycle { prevent_destroy = true }
}
resource "google_secret_manager_secret_iam_member" "read" {
  for_each  = toset([google_secret_manager_secret.owner.secret_id, google_secret_manager_secret.tunnel.secret_id, "reqlox-jev-api-key"])
  project   = var.project_id
  secret_id = each.key
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_compute_disk" "state" {
  name   = "${var.name}-state"
  type   = "pd-standard"
  zone   = var.zone
  size   = 10
  labels = local.labels
  lifecycle { prevent_destroy = true }
}
resource "google_compute_instance" "web" {
  count        = var.deploy_runtime ? 1 : 0
  name         = var.name
  zone         = var.zone
  machine_type = "e2-medium"
  tags         = ["reqlox-web-backend"]
  labels       = local.labels
  boot_disk {
    auto_delete = true
    initialize_params {
      image = var.image
      size  = 15
      type  = "pd-standard"
    }
  }
  attached_disk {
    source      = google_compute_disk.state.id
    device_name = "reqlox-state"
  }
  network_interface {
    subnetwork = google_compute_subnetwork.web.id
    network_ip = "10.83.0.10"
    access_config { network_tier = "STANDARD" }
  }
  service_account {
    email  = google_service_account.runtime.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  scheduling {
    automatic_restart           = false
    on_host_maintenance         = "MIGRATE"
    instance_termination_action = var.continuous_hosting ? null : "STOP"
    termination_time            = !var.continuous_hosting && var.termination_time != "" ? var.termination_time : null
    dynamic "max_run_duration" {
      for_each = !var.continuous_hosting && var.termination_time == "" ? [var.lease_seconds] : []
      content { seconds = max_run_duration.value }
    }
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  metadata = {
    enable-oslogin           = "TRUE"
    block-project-ssh-keys   = "TRUE"
    disable-legacy-endpoints = "TRUE"
    reqlox-runtime           = var.reviewed_runtime_metadata_path != "" ? file(var.reviewed_runtime_metadata_path) : local.runtime
    reqlox-release-sha256    = local.digest
  }
  metadata_startup_script = var.reviewed_startup_script_path != "" ? file(var.reviewed_startup_script_path) : templatefile("${path.module}/startup.sh.tftpl", {
    base_bootstrap_b64 = filebase64("${path.module}/../runtime_bootstrap.py"),
    web_bootstrap_b64  = filebase64("${path.module}/web_bootstrap.py"),
    context_b64        = filebase64("${path.module}/../host_context.py"),
    boot_evidence_b64  = filebase64("${path.module}/boot_evidence.py")
  })
  lifecycle {
    precondition {
      condition     = !var.continuous_hosting || var.termination_time == ""
      error_message = "Continuous hosting cannot retain an automatic stop deadline."
    }
    precondition {
      condition     = var.reviewed_runtime_metadata_path == "" ? true : jsondecode(file(var.reviewed_runtime_metadata_path)) == jsondecode(local.runtime)
      error_message = "Observed runtime metadata must match the current hash-bound configuration."
    }
    precondition {
      condition     = var.owner_secret_version != "" && (var.frontend_mode == "CLOUD_RUN_GATEWAY" || var.tunnel_secret_version != "")
      error_message = "Register both exact secret versions outside Terraform before booting."
    }
  }
  depends_on = [google_storage_bucket_iam_member.public_assets, google_storage_bucket_object.release,
    google_storage_bucket_object.release_updates,
  google_storage_bucket_iam_member.runtime_read, google_secret_manager_secret_iam_member.read, google_compute_firewall.iap]
}
resource "google_iap_tunnel_instance_iam_member" "access" {
  for_each = var.deploy_runtime ? var.iap_members : toset([])
  project  = var.project_id
  zone     = var.zone
  instance = google_compute_instance.web[0].name
  role     = "roles/iap.tunnelResourceAccessor"
  member   = each.value
  lifecycle { replace_triggered_by = [google_compute_instance.web[0]] }
  condition {
    title      = "reqlox-web-ui-only"
    expression = "destination.port == 8080"
  }
}
