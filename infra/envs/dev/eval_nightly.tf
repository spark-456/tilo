# Nightly eval smoke on Cloud Scheduler (EFF-05b; PRD 6.6 "Batch the non-urgent", 19.5; user decision 2026-10-06,
# relayed by the supervisor: Cloud Scheduler in tilo-dev, not GitHub Actions).
#
#   Cloud Scheduler (OAuth, as tilo-eval-scheduler) --> POST Cloud Run Admin API  .../jobs/tilo-eval-nightly:run
#     --> Cloud Run job tilo-eval-nightly, running as tilo-eval-runner:  python -m tilo_evals nightly
#
# The job replays recorded cases: no secrets, no live switch, no model call. tilo-eval-scheduler holds exactly one
# grant, roles/run.invoker on that one job (it includes run.jobs.run). tilo-eval-runner holds no role at all: the
# replay reads files baked into the image and writes only to its log. Nothing here grants iam.serviceAccountUser;
# the person who applies already may act as both accounts, and Scheduler's own service agent mints the token.
# Tests: tests/repo/test_EFF_05_nightly_scheduler_terraform.py (static; no terraform binary needed).

variable "eval_nightly_schedule" {
  description = "Cron (unix-cron) of the nightly eval smoke, evaluated in Etc/UTC. 19:00 UTC is 00:30 IST (BQ-EFF05B-1)."
  type        = string
  default     = "0 19 * * *"
}

locals {
  # The image is built and pushed by `just build-evals-image` (evals/cloudbuild.yaml) BEFORE the apply, under the
  # tag `latest`, so each night runs the newest pushed build (BQ-EFF05B-6).
  eval_nightly_image = "${var.region}-docker.pkg.dev/${var.project_id}/tilo/evals:latest"
}

# Identity Scheduler authenticates as. Used for nothing but the trigger and its one invoker grant below.
resource "google_service_account" "eval_scheduler" {
  project      = var.project_id
  account_id   = "tilo-eval-scheduler"
  display_name = "Tilo nightly eval trigger (Cloud Scheduler OAuth identity)"

  depends_on = [google_project_service.apis]
}

# Identity the job runs as: no role anywhere, and never the account that starts it.
resource "google_service_account" "eval_runner" {
  project      = var.project_id
  account_id   = "tilo-eval-runner"
  display_name = "Tilo nightly eval job (replay, no roles)"

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_job" "eval_nightly" {
  project             = var.project_id
  name                = "tilo-eval-nightly"
  location            = var.region
  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1

    template {
      service_account = google_service_account.eval_runner.email
      max_retries     = 1
      timeout         = "3600s"

      containers {
        image   = local.eval_nightly_image
        command = ["python"]
        args    = ["-m", "tilo_evals", "nightly", "--results-md", "/tmp/nightly.md"]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }

  depends_on = [google_project_service.apis]
}

# The one grant: start this job and nothing else. Resource-scoped, never project-wide, never public.
resource "google_cloud_run_v2_job_iam_member" "eval_scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.eval_nightly.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.eval_scheduler.email}"
}

resource "google_cloud_scheduler_job" "eval_nightly" {
  project          = var.project_id
  region           = var.region
  name             = "tilo-eval-nightly"
  description      = "Start the nightly eval smoke Cloud Run job (replay; EFF-05)."
  schedule         = var.eval_nightly_schedule
  time_zone        = "Etc/UTC"
  attempt_deadline = "180s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.eval_nightly.name}:run"

    # A Google API, so an OAuth access token (OIDC is for calls to a service of ours).
    oauth_token {
      service_account_email = google_service_account.eval_scheduler.email
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.eval_scheduler_invoker]
}
