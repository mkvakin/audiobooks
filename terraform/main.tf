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


# 4. Cloud Run Job
resource "google_cloud_run_v2_job" "converter" {
  name     = "audiobook-converter"
  location = var.region

  template {
    template {
      service_account = google_service_account.audiobook_sa.email

      containers {
        image = "gcr.io/cloudrun/hello:latest"

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

# 5. Workload Identity Federation for GitHub Actions
resource "google_iam_workload_identity_pool" "github_pool" {
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"
  description               = "Identity pool for GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub Provider"
  description                        = "GitHub Actions identity provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_condition = "assertion.repository == 'mkvakin/audiobooks'"
}

# Allow GitHub Actions to impersonate the service account
resource "google_service_account_iam_member" "wif_impersonation" {
  service_account_id = google_service_account.audiobook_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_pool.name}/attribute.repository/mkvakin/audiobooks"
}

# Grant the Service Account permissions to manage Cloud Run and Artifact Registry (needed for deployment)
resource "google_project_iam_member" "sa_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.audiobook_sa.email}"
}

resource "google_project_iam_member" "sa_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.audiobook_sa.email}"
}

resource "google_project_iam_member" "sa_iam_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.audiobook_sa.email}"
}
