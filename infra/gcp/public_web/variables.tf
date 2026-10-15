variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-northeast1"
}
variable "zone" {
  type    = string
  default = "asia-northeast1-b"
}
variable "name" {
  type    = string
  default = "reqlox-web"
  validation {
    condition     = var.name == "reqlox-web"
    error_message = "Use the dedicated reqlox-web namespace."
  }
}
variable "domain" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9-]+\\.[a-z0-9-]+\\.[a-z]{2,}$", var.domain))
    error_message = "Use an explicit single-level HTTPS subdomain."
  }
}
variable "image" {
  type = string
  validation {
    condition     = can(regex("^projects/debian-cloud/global/images/debian-12-", var.image))
    error_message = "Pin an exact Debian 12 image."
  }
}
variable "release_archive" { type = string }
variable "initial_release_archive" {
  type    = string
  default = ""
}
variable "retained_release_archives" {
  type    = map(string)
  default = {}
}
variable "release_bucket" { type = string }
variable "static_directory" { type = string }
variable "deploy_runtime" {
  type    = bool
  default = false
}
variable "owner_secret_version" {
  type    = string
  default = ""
  validation {
    condition     = var.owner_secret_version == "" || can(regex("^[1-9][0-9]*$", var.owner_secret_version))
    error_message = "Pin a numeric owner secret version."
  }
}
variable "tunnel_secret_version" {
  type    = string
  default = ""
  validation {
    condition     = var.tunnel_secret_version == "" || can(regex("^[1-9][0-9]*$", var.tunnel_secret_version))
    error_message = "Pin a numeric connector token version."
  }
}
variable "cloudflared_url" {
  type = string
  validation {
    condition     = can(regex("^https://github.com/cloudflare/cloudflared/releases/download/[0-9.]+/cloudflared-linux-amd64$", var.cloudflared_url))
    error_message = "Use a pinned official cloudflared binary."
  }
}
variable "cloudflared_sha256" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.cloudflared_sha256))
    error_message = "The official binary checksum is required."
  }
}
variable "iap_members" { type = set(string) }
variable "lease_seconds" {
  type    = number
  default = 86400
  validation {
    condition     = var.lease_seconds >= 3600 && var.lease_seconds <= 86400
    error_message = "Finite hosting leases must remain between one hour and 24 hours."
  }
}
variable "continuous_hosting" {
  type        = bool
  default     = false
  description = "Explicitly authorized continued UI hosting; worker and experiment limits remain separate."
}
variable "frontend_mode" {
  type    = string
  default = "CLOUD_RUN_GATEWAY"
  validation {
    condition     = contains(["CLOUD_RUN_GATEWAY", "CLOUDFLARE_TUNNEL"], var.frontend_mode)
    error_message = "Choose an explicit HTTPS frontend."
  }
}
variable "gateway_image" {
  type    = string
  default = ""
  validation {
    condition     = var.gateway_image == "" || can(regex("^asia-northeast1-docker.pkg.dev/[a-z0-9-]+/reqlox-web/gateway@sha256:[a-f0-9]{64}$", var.gateway_image))
    error_message = "Pin the deployed gateway container digest."
  }
}
variable "deploy_gateway" {
  type    = bool
  default = false
}

# Reviewed updates preserve VM identity; continuous hosting requires an explicit mode.
variable "reviewed_startup_script_path" {
  type    = string
  default = ""
  validation {
    condition     = var.reviewed_startup_script_path == "" || fileexists(var.reviewed_startup_script_path)
    error_message = "Use the exact reviewed startup script file for an existing VM rollout."
  }
}
variable "termination_time" {
  type    = string
  default = ""
  validation {
    condition     = var.termination_time == "" || can(formatdate("YYYY-MM-DD", var.termination_time))
    error_message = "Use the existing absolute RFC3339 stop deadline; never extend it during a rollout."
  }
}

variable "reviewed_runtime_metadata_path" {
  type    = string
  default = ""
  validation {
    condition     = var.reviewed_runtime_metadata_path == "" || fileexists(var.reviewed_runtime_metadata_path)
    error_message = "Use the observed runtime metadata file for an existing rollout."
  }
}
variable "gateway_deployment_client" {
  type    = string
  default = null
}
variable "gateway_deployment_client_version" {
  type    = string
  default = null
}
