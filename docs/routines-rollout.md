# Routines rollout (scheduled runs, FR-AGT-14) on tilo-dev

Run this yourself. Claude's tooling never applies Terraform or authenticates to Google Cloud.

Before you start:
- Wait until the scheduled-runs stack (#498, #513, #579, #583, #584) is merged into phase0-stack, and tilo-api is
  deployed from that commit (`just deploy-dev-cloudbuild api`).
- You are signed in to gcloud as the project Owner, and Terraform is initialised as `infra/README.md` describes.

```powershell
# --- 0. Fixed values for tilo-dev --------------------------------------------------------------
$Project = "essential-wares-510320-f0"
$Region  = "asia-southeast1"
$Repo    = "C:\Users\josna\OneDrive\Desktop\Claude Projects\Tilo"
Set-Location $Repo

# --- 1. Terraform: the runs queue, the Scheduler job and its identity, the Firestore index ------
#   It creates or changes: google_cloud_tasks_queue.runs, google_service_account.schedule_scheduler,
#   google_service_account.tasks_invoker (+ serviceAccountUser for api and harness), module.schedule_tick
#   (Cloud Scheduler job "tilo-schedule-tick", every minute, OIDC to tilo-api /internal/schedules/tick)
#   and google_firestore_index.schedules_due. Read the plan: nothing should be destroyed.
$RepoIds = gh api repos/spark-456/tilo --jq '.id, .owner.id'
terraform -chdir=infra/envs/dev plan `
  -var="billing_account_id=YOUR_BILLING_ACCOUNT_ID" `
  -var="github_repository=spark-456/tilo" `
  -var="github_repository_id=$($RepoIds[0])" `
  -var="github_repository_owner_id=$($RepoIds[1])" `
  -var="alert_email=YOUR_ALERT_EMAIL" `
  -out=tfplan
terraform -chdir=infra/envs/dev apply tfplan

# --- 2. tilo-api settings for the tick and the hand-off ----------------------------------------
$ApiUrl = gcloud run services describe tilo-api --project $Project --region $Region --format "value(status.url)"
$Env = @(
  "TILO_SCHEDULE_TICK_AUDIENCE=$ApiUrl",                                            # the Scheduler's OIDC audience
  "TILO_SCHEDULE_TICK_CALLER=tilo-schedule-scheduler@$Project.iam.gserviceaccount.com",
  "TILO_SCHEDULES_STORE=firestore",
  "TILO_FIRESTORE_PROJECT=$Project",
  "TILO_RUNS_QUEUE=projects/$Project/locations/$Region/queues/runs",
  "TILO_TASKS_CALLER=tilo-tasks-invoker@$Project.iam.gserviceaccount.com",
  "TILO_TEAM_STORE=firestore"                                                        # team roles, limits and switches (#642)
) -join ","
gcloud run services update tilo-api --project $Project --region $Region --update-env-vars $Env

# --- 3. Check a tick happened (wait two minutes after step 2) -----------------------------------
# A healthy idle tick answers 200 {"fired":0}; the Scheduler shows the last attempt and its status.
gcloud scheduler jobs describe tilo-schedule-tick --project $Project --location $Region `
  --format "value(state,lastAttemptTime,status.code)"
# Recent tick requests on tilo-api (status 200 = fine, 503 = see the codes below):
gcloud logging read `
  "resource.type=cloud_run_revision AND resource.labels.service_name=tilo-api AND httpRequest.requestUrl:`"/internal/schedules/tick`"" `
  --project $Project --freshness 10m --limit 10 --format "table(timestamp,httpRequest.status)"
# Failures from the scheduled-runs code (AGT14f-h). Search the text until the JSON log handler (NFR-26) lands:
gcloud logging read `
  "resource.type=cloud_run_revision AND resource.labels.service_name=tilo-api AND (textPayload:`"tasks_`" OR textPayload:`"schedule`") AND severity>=WARNING" `
  --project $Project --freshness 1h --limit 20 --format "table(timestamp,severity,textPayload)"
```

## Env drift check (read-only)

Run after step 2 and after any plan that touches tilo-api. It only reads the service, flags settings that must never be
set on a deployed service, and flags names that are not on the allowlist. It never prints a value (names only).

```powershell
$Project = "essential-wares-510320-f0"; $Region = "asia-southeast1"
$Allow = @("TILO_SCHEDULE_TICK_AUDIENCE","TILO_SCHEDULE_TICK_CALLER","TILO_SCHEDULES_STORE","TILO_FIRESTORE_PROJECT",
  "TILO_RUNS_QUEUE","TILO_TASKS_CALLER","TILO_TEAM_STORE","TILO_SKILLS_STORE","TILO_API_CORS_ORIGINS")        # extend per service as settings are added
$Never = @("LIVE","TILO_API_DEV","TILO_JUDGE_LIVE","FIRESTORE_EMULATOR_HOST","TILO_MODELS_FILE")
$Svc = gcloud run services describe tilo-api --project $Project --region $Region --format json | ConvertFrom-Json
$Vars = @($Svc.spec.template.spec.containers[0].env)
$Bad = @()
foreach ($v in $Vars) {
  if ($Never -contains $v.name) { $Bad += "FORBIDDEN: $($v.name) is set" }
  elseif ($v.name -eq "TILO_TEAM_STORE" -and $v.value -and $v.value.Trim().ToLower() -eq "memory") { $Bad += "FORBIDDEN: TILO_TEAM_STORE=memory" }
  elseif ($Allow -notcontains $v.name) { $Bad += "UNEXPECTED: $($v.name) is not on the allowlist" }
}
foreach ($n in $Allow) { if (-not ($Vars | Where-Object { $_.name -eq $n })) { $Bad += "MISSING: $n" } }
if ($Bad.Count) { $Bad | ForEach-Object { Write-Host $_ -ForegroundColor Red } } else { Write-Host "env OK ($($Vars.Count) settings)" }
```

## What the tick's answers mean

| Answer | Meaning | What to do |
|---|---|---|
| 200 `{"fired": n}` | n routines were handed to the runs queue | nothing |
| 503 `not_configured` | a step-2 setting is missing, or the store is not Firestore | re-run step 2 |
| 503 `tasks_unavailable` | Cloud Tasks refused the whole service (401, 403 or 404): queue missing, or tilo-api cannot act as tilo-tasks-invoker | re-run step 1; check the queue exists |
| 503 `tasks_credential` | tilo-api's own credential failed to refresh (can also be a network problem reaching Google's credential server) | check the tilo-api service account |
| 503 `tasks_transport` | a network failure to Cloud Tasks | usually passes; repeated means an outage |
| 503 `tasks_quota` / `tasks_server` | Cloud Tasks answered 429 or 5xx for the first two routines in a tick | usually passes; repeated means a quota limit or an outage |

Routines that were due during any 503 stay due, and fire once the cause is fixed. None is disabled by an outage.

## Known caveats
- The tilo-api settings in step 2 are set with gcloud. Only tilo-api and tilo-connectors have `ignore_env = true` in `infra/envs/dev`, so the
  module ignores `env` drift on those services (`ignore_changes` on `template[0].containers[0].env`) and a later
  Terraform run leaves the settings alone; every other service's env stays fully managed. The service module declares
  no `env` block (a tests/repo guard), because declared env would never be applied.
- Secrets only via `--update-secrets` (Secret Manager references), never in `--update-env-vars`.
- If a Terraform plan REPLACES the tilo-api service (it shows `must be replaced`), the new service starts without these
  settings: re-run step 2 afterwards. A plan that only updates it in place keeps them. Until `TILO_TEAM_STORE=firestore` is set, the team controls
  (roles, limits, switches, tool levels) are inert and `/v1/team` answers 503.
- The structured log fields (`event`, `status`, `code`) reach Cloud Logging only once the NFR-26 JSON handler lands.
  Until then, search the log text as step 3 does.
