# Acceptance tests for the P0-07b access audit (infra/ACCESS.md).
#   terraform -chdir=infra/envs/dev test

variables {
  project_id                 = "tilo-dev-test"
  region                     = "asia-southeast1"
  billing_account_id         = "000000-000000-000000"
  github_repository          = "tilo-org/tilo"
  github_repository_id       = "123456789"
  github_repository_owner_id = "987654321"
  budget_amount_usd          = 150
  alert_email                = "alerts@example.com"
}

mock_provider "google" {}
mock_provider "google-beta" {}

run "SEC_02_connectors_encrypts_and_decrypts_oauth_tokens_on_that_key_only" {
  command = plan

  assert {
    condition     = output.oauth_token_key_role == "roles/cloudkms.cryptoKeyEncrypterDecrypter"
    error_message = "The token broker wraps data keys, so connectors needs encrypt as well as decrypt on the oauth-tokens key."
  }

  assert {
    condition     = length(output.oauth_token_key_decrypters) == 1 && strcontains(output.oauth_token_key_decrypters[0], "tilo-connectors@")
    error_message = "Only tilo-connectors may use the oauth-tokens key (SEC-02)."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !strcontains(b.role, "cloudkms")])
    error_message = "No project-wide KMS role: key access is granted on the key (SEC-02, SEC-12)."
  }
}

run "SEC_04_model_armor_user_only_for_services_that_screen" {
  command = plan

  assert {
    condition = toset([
      for b in output.project_iam_bindings : b.member if b.role == "roles/modelarmor.user"
      ]) == toset([
      "serviceAccount:tilo-api@${var.project_id}.iam.gserviceaccount.com",
      "serviceAccount:tilo-harness@${var.project_id}.iam.gserviceaccount.com",
      "serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com",
    ])
    error_message = "modelarmor.user belongs to api, harness and channels only (PRD 6.3 Model Armor)."
  }

  assert {
    condition     = output.model_armor_template.template_id == "tilo-default"
    error_message = "A Model Armor template must exist for the safety provider."
  }
}

run "PRD_6_3_extra_apis_enabled_and_speech_absent" {
  command = plan

  assert {
    condition = alltrue([
      for api in [
        "serviceusage.googleapis.com", "firebaserules.googleapis.com", "recaptchaenterprise.googleapis.com",
        "docs.googleapis.com", "sheets.googleapis.com", "slides.googleapis.com",
      ] : contains(output.enabled_apis, api)
    ])
    error_message = "Firestore rules, App Check provider and Google output APIs must be enabled up front."
  }

  assert {
    condition     = alltrue([for a in output.enabled_apis : !strcontains(a, "speech") && !strcontains(a, "texttospeech") && !strcontains(a, "imagen") && !strcontains(a, "video")])
    error_message = "No speech, image or video API: no provider profile names one."
  }
}

run "FR_CHN_08_gmail_push_topic_publisher_and_jobs" {
  command = plan

  assert {
    condition     = output.gmail_push.topic_publishers == ["serviceAccount:gmail-api-push@system.gserviceaccount.com"]
    error_message = "Only gmail-api-push@system.gserviceaccount.com may publish to the Gmail topic."
  }

  assert {
    condition     = output.gmail_push.topic_name != output.pubsub_events_topic_name
    error_message = "Gmail notifications use their own topic, not tilo-events."
  }

  assert {
    condition     = toset(keys(output.gmail_push.scheduler_jobs)) == toset(["renew", "poll"]) && output.gmail_push.scheduler_jobs.renew.schedule == "0 3 * * *"
    error_message = "A daily watch renewal and a polling fallback job must exist."
  }

  assert {
    condition = toset(output.cloud_run_services["channels"].invokers) == toset([
      "allUsers",
      "serviceAccount:tilo-gmail-push@${var.project_id}.iam.gserviceaccount.com",
      "serviceAccount:tilo-gmail-scheduler@${var.project_id}.iam.gserviceaccount.com",
    ])
    error_message = "The push and scheduler identities hold run.invoker on tilo-channels."
  }

  assert {
    condition = alltrue([
      for s in ["api", "harness", "connectors", "browser", "render", "sandbox-web"] :
      !contains(output.cloud_run_services[s].invokers, "serviceAccount:tilo-gmail-push@${var.project_id}.iam.gserviceaccount.com") &&
      !contains(output.cloud_run_services[s].invokers, "serviceAccount:tilo-gmail-scheduler@${var.project_id}.iam.gserviceaccount.com")
    ])
    error_message = "The Gmail identities may invoke tilo-channels only."
  }
}

run "PRD_13_2_storage_grants_are_bucket_scoped_create_and_read" {
  command = plan

  assert {
    condition = alltrue([
      for k, m in output.service_storage_grants :
      !strcontains(k, "objectAdmin") && !strcontains(k, "objectUser") && !strcontains(k, "tilo-browser")
    ])
    error_message = "Service grants are create and read only (render alone holds objectAdmin) and never reach tilo-browser."
  }

  assert {
    condition     = !contains(keys(output.service_storage_grants), "archive::harness::roles/storage.objectAdmin") && !anytrue([for k in keys(output.service_storage_grants) : startswith(k, "archive::api")])
    error_message = "The archive bucket is create-only for harness plus read for chain checks; api gets nothing."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !startswith(b.role, "roles/storage.")])
    error_message = "No project-wide Storage role (SEC-12)."
  }
}

run "SEC_12_deployer_still_holds_no_project_role_by_default" {
  command = plan

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !strcontains(b.member, "tilo-deployer@")])
    error_message = "var.deployer_project_roles defaults to none."
  }

  assert {
    condition     = length([for b in output.project_iam_bindings : b if strcontains(b.member, "tilo-cloudbuild@")]) == 1
    error_message = "The build identity holds exactly one project role (logging.logWriter)."
  }
}

run "SEC_12_deployer_project_roles_are_explicit_opt_in" {
  command = plan

  variables {
    deployer_project_roles = ["roles/cloudbuild.builds.editor"]
  }

  assert {
    condition     = length([for b in output.project_iam_bindings : b if b.role == "roles/cloudbuild.builds.editor"]) == 1
    error_message = "An opted-in deployer role must appear in the bindings, visible to review."
  }
}
