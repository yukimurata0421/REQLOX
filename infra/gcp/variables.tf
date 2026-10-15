variable "project_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use an explicit Google Cloud project ID."
  }
}

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
  default = "reqlox-demo"
  validation {
    condition     = can(regex("^reqlox-[a-z0-9-]{1,15}$", var.name))
    error_message = "Use the reqlox- prefix and at most 22 characters so the runtime account ID fits."
  }
}

variable "machine_type" {
  type    = string
  default = "e2-medium"
  validation {
    condition     = contains(["e2-small", "e2-medium"], var.machine_type)
    error_message = "The finite demo supports only e2-small or e2-medium."
  }
}

variable "image" {
  type = string
  validation {
    condition     = can(regex("^projects/debian-cloud/global/images/debian-12-", var.image))
    error_message = "Pin an exact Debian 12 image; image families are not releases."
  }
}

variable "release_archive" {
  type = string
  validation {
    condition     = fileexists(var.release_archive)
    error_message = "Build the allowlisted release archive first."
  }
}

variable "retained_release_archives" {
  type    = map(string)
  default = {}
  validation {
    condition     = alltrue([for digest, path in var.retained_release_archives : can(regex("^[a-f0-9]{64}$", digest)) && fileexists(path) && filesha256(path) == digest])
    error_message = "Retained archives must exist and match their immutable hash."
  }
}

variable "iap_members" {
  type = set(string)
  validation {
    condition     = length(var.iap_members) > 0 && alltrue([for m in var.iap_members : can(regex("^(user|group):[^ ]+@[^ ]+$", m))])
    error_message = "Grant access to explicit users or groups, never allUsers."
  }
}

variable "billing_account_id" {
  type = string
}

variable "budget_jpy" {
  type    = number
  default = 1000
  validation {
    condition     = var.budget_jpy > 0 && var.budget_jpy <= 10000 && floor(var.budget_jpy) == var.budget_jpy
    error_message = "Use an integer budget within the inherited JPY 10,000 limit."
  }
}

variable "lease_seconds" {
  type    = number
  default = 86400
  validation {
    condition     = var.lease_seconds >= 3600 && var.lease_seconds <= 86400 && floor(var.lease_seconds) == var.lease_seconds
    error_message = "VM sessions must expire within 24 hours."
  }
}

variable "deploy_runtime" {
  type    = bool
  default = false
}

variable "jev_secret_version" {
  type    = string
  default = ""
  validation {
    condition     = var.jev_secret_version == "" || can(regex("^[1-9][0-9]*$", var.jev_secret_version))
    error_message = "Use a numeric immutable secret version, never latest."
  }
}
