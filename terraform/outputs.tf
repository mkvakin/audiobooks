output "audiobooks_bucket" {
  value = google_storage_bucket.audiobooks.name
}

output "cloud_run_job_name" {
  value = google_cloud_run_v2_job.converter.name
}

output "service_account_email" {
  value = google_service_account.audiobook_sa.email
}
