terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Cloud Storage Bucket for Audiobooks
resource "google_storage_bucket" "audiobooks" {
  name          = "${var.project_id}-audiobooks"
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }
}

# 2. Service Account for Cloud Run Job
resource "google_service_account" "audiobook_sa" {
  account_id   = "audiobook-converter-sa"
  display_name = "Service Account for Audiobook Converter Cloud Run Job"
}

# 3. IAM permissions for Service Account
# Access to Cloud Storage
resource "google_storage_bucket_iam_member" "storage_admin" {
  bucket = google_storage_bucket.audiobooks.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.audiobook_sa.email}"
}

# Access to Google TTS
resource "google_project_iam_member" "tts_user" {
  project = var.project_id
  role    = "roles/texttospeech.serviceUser"
  member  = "serviceAccount:${google_service_account.audiobook_sa.email}"
}

# 4. Cloud Run Job
resource "google_cloud_run_v2_job" "converter" {
  name     = "audiobook-converter"
  location = var.region

  template {
    template {
      service_account = google_service_account.audiobook_sa.email

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/audiobook-converter/app:latest"

        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }

        env {
          name  = "GCP_STORAGE_BUCKET"
          value = google_storage_bucket.audiobooks.name
        }

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
      }

      # Allow long running jobs (up to 24h)
      timeout     = "7200s" # 2 hours
      max_retries = 0
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }
}
