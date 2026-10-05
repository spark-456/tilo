output "topic_name" {
  value = google_pubsub_topic.gmail.name
}

output "topic_publishers" {
  description = "Members granted pubsub.publisher on the Gmail topic."
  value       = [google_pubsub_topic_iam_member.gmail_publisher.member]
}

output "subscription_name" {
  value = google_pubsub_subscription.gmail_push.name
}

output "push_path" {
  value = var.push_path
}

output "scheduler_jobs" {
  description = "Job key => {name, schedule, path} (config values)."
  value = {
    for k, j in local.jobs : k => {
      name     = google_cloud_scheduler_job.gmail[k].name
      schedule = j.schedule
      path     = j.path
    }
  }
}
