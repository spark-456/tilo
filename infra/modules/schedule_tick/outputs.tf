output "tick" {
  description = "The tick job as configured (FR-AGT-14)."
  value = {
    job_name        = google_cloud_scheduler_job.tick.name
    schedule        = google_cloud_scheduler_job.tick.schedule
    time_zone       = google_cloud_scheduler_job.tick.time_zone
    path            = var.path
    http_method     = google_cloud_scheduler_job.tick.http_target[0].http_method
    retry_count     = google_cloud_scheduler_job.tick.retry_config[0].retry_count
    service_account = var.service_account_email
    audience        = var.target_uri
    uri             = google_cloud_scheduler_job.tick.http_target[0].uri
  }
}
