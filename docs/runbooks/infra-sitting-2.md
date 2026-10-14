# Infrastructure sitting 2: uploads, TTLs, test-only gate identity, web push, optional Meet bot

You run every block below yourself, in order, in one PowerShell window. Claude's tooling plans nothing against the cloud
and applies nothing (`terraform apply` is yours; so is every `gcloud run services update`). Project
`essential-wares-510320-f0`, region `asia-southeast1`. Nothing here sets the live switch: that stays yours, section 10.

Sources: `agy-bridge/tasks/USER-INFRA-SITTING-2.md`, `USER-INFRA-SITTING-2-DETAILS-20261012.md`,
`MEETING-OPTIONAL-BOT-PLAN-14OCT.md`, `infra/ACCESS.md`, `docs/routines-rollout.md` ("Known caveats").

## What the plan adds, and what stays off

| Part | Result | Terraform |
|---|---|---|
| Uploads (#853) | api: archive create plus view (no delete, no update), artifacts delete through a one-permission custom role | `sitting2.tf`, `storage_grants` in `main.tf` |
| TTLs (#609, BQ-PA06B-2) | Firestore TTL on `limiter_counters.expires_at`, `limiter_keys.expires_at`, `link_nonces.expires_at` | `google_firestore_field.ttl` |
| Test-only gate identity (#870) | `tilo-cloudbuild-tests`: staging-source read and build logs only. The gate keeps `tilo-cloudbuild` until you change `serviceAccount` | `sitting2.tf` |
| Link signing key | api may read `tilo-link-signing-key` (the secret was made by hand; only the accessor binding is Terraform's) | `sitting2.tf` |
| Channels env | `tilo-channels` gets `ignore_env`, so the gcloud-set push settings survive a later apply (a `moved` block: no destroy) | `modules/service`, `main.tf` |
| **Egress NAT (already created by hand; adopted in section 2)** | Cloud Router `tilo-nat-router` plus a Cloud NAT on `tilo-run-egress` only (automatic IPs, errors-only logs), made by hand on 14 Oct about 09:00 with exactly these names. Section 2 adopts both into Terraform state with two `terraform import` commands, before the plan; the code matches the live arguments, so the plan has no entry for them (no create, no change). Fixes the live Home 503 ("safety screen failed" after about 10.9 s): api and harness send ALL_TRAFFIC into `tilo-vpc`, which had no NAT, and the regional Model Armor endpoint (and NIM, Canva, Lovable, vendor hosts) is not reached by Private Google Access | `network.tf` |
| Optional Meet bot | plan made with `meet_bot_enabled=true` (variable default stays false) | existing flag |
| Skills store | `TILO_SKILLS_STORE=firestore` on tilo-api (`GET /v1/skills` was 503 `SkillStoreNotConfigured`); a gcloud setting, section 6.3 | none |
| Left OFF | `TILO_PLATE_DIGEST` (section 6.4 says why); the live switch; Gemini Live (`voice.live.enabled` and `price_approved` stay false) | none |

Expected plan with the bot, from the code (not from a refreshed plan; the script in section 3 enforces it):
**21 to add, 3 to change, 0 to destroy**, plus one "has moved" (channels). Without the bot it is 11 to add, 0 to change.
The NAT router and NAT are in none of these numbers: after the section 2 import they are unchanged, and the review gate
fails if either appears as an add, a change or an import (it means the import step was skipped or the code drifted).
Anything else: stop and send it for review.

**Order of the sitting:** sections 1 to 3 (plan and review), then 4 (apply). The NAT you created by hand is adopted into state in
section 2, before the plan, so the apply leaves it alone. Then do the section 4 verification (NAT, then a Home task) before any env step in
sections 5 and 6: if Home still answers 503 after the NAT shows READY, stop there and send the log lines.

**Cost of the NAT:** (it is already running; importing changes nothing) Cloud NAT bills a small per-hour charge for the gateway while it exists plus a per-GiB charge on the
traffic through it, and automatically allocated external IPs may carry a small address charge while in use. At this
project's traffic that is cents a month, not a budget item; check the regional price before you apply if it matters. Only
`tilo-run-egress` is NATed, nothing else in the project gains internet egress.

## 1. Preflight (read-only)

```powershell
$ErrorActionPreference = 'Stop'
$P = 'essential-wares-510320-f0'; $R = 'asia-southeast1'
$Wt = 'C:/Users/josna/OneDrive/Desktop/Claude Projects/Tilo-wt/infra-sitting2'   # the reviewed checkout of the PR branch
Set-Location $Wt
git status --short                   # must print nothing
git log -1 --format='%H %s'          # write this sha down; it is the code you are applying
# Sign in again only if these fail:  gcloud auth login ; gcloud auth application-default login
gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud config set project $P | Out-Null
gcloud auth application-default set-quota-project $P
gcloud billing accounts list --format='table(name.basename(),displayName,open)'   # the ID is the first column
if (-not (Test-Path infra/envs/dev/backend.hcl)) {
  Set-Content -Path infra/envs/dev/backend.hcl -Value @('bucket = "essential-wares-510320-f0-tfstate"', 'prefix = "envs/dev"')
}
terraform -chdir=infra/envs/dev init -input=false '-backend-config=backend.hcl'
if ($LASTEXITCODE -ne 0) { throw 'init failed; stop' }
terraform -chdir=infra/envs/dev validate
# Secrets this sitting reads: each must show version 1 enabled.
foreach ($s in 'webpush-vapid-private-key', 'tilo-link-signing-key', 'workspace-oauth-client-id', 'workspace-oauth-client-secret') {
  "$s : " + (gcloud secrets versions list $s --project $P --filter='state=ENABLED' --format='value(name.basename())')
}
```

## 2. Adopt the hand-made NAT into state, then the saved plan

### 2.0 Import the router and the NAT (writes Terraform state only; changes nothing in the cloud)

You created `tilo-nat-router` and `tilo-run-egress-nat` by hand, with the names `network.tf` uses. Without this step the
plan would try to create them and fail with "already exists". Each command reads the live object and records it in the
state; neither creates, changes or deletes anything in the cloud. Run it once; a second run answers "already managed".

```powershell
$billingId = Read-Host 'Billing account ID (first column of the list above)'
$alertEmail = Read-Host 'Monitoring alert email (same as the first sitting)'
$varArgs = @(
  "-var=project_id=$P", "-var=region=$R", "-var=billing_account_id=$billingId",
  '-var=github_repository=spark-456/tilo', '-var=github_repository_id=1386743901',
  '-var=github_repository_owner_id=81423861', "-var=alert_email=$alertEmail",
  '-var=budget_amount_usd=15000', '-var=budget_currency_code=INR',
  '-var=api_durable_stores=true', '-var=meet_bot_enabled=true'
)
terraform -chdir=infra/envs/dev import -input=false @varArgs google_compute_router.nat "projects/$P/regions/$R/routers/tilo-nat-router"
if ($LASTEXITCODE -ne 0) { throw 'router import failed; stop' }
terraform -chdir=infra/envs/dev import -input=false @varArgs google_compute_router_nat.run_egress "$P/$R/tilo-nat-router/tilo-run-egress-nat"
if ($LASTEXITCODE -ne 0) { throw 'NAT import failed; stop' }
terraform -chdir=infra/envs/dev state list | Select-String 'google_compute_router'   # both addresses
```

The live NAT is: automatic IPs, `LIST_OF_SUBNETWORKS` with `tilo-run-egress` on `PRIMARY_IP_RANGE`, errors-only logs. The code
says the same, so the plan below has no line for either. If section 3 reports `NAT PAIR IN THE PLAN`, stop and send it.

### 2.1 Saved plan (writes a local file; changes nothing in the cloud)

`-refresh=true` reads the live state. The repository ids and the budget are the values of the first sitting. Add any
other override you used then. The file `sitting2.tfplan` is git-ignored and can hold sensitive state: keep it local.

```powershell
# $billingId and $alertEmail come from section 2.0 (same window); ask again only if they are empty.
if (-not $billingId) { $billingId = Read-Host 'Billing account ID (first column of the list above)' }
if (-not $alertEmail) { $alertEmail = Read-Host 'Monitoring alert email (same as the first sitting)' }
$planArgs = @(
  '-chdir=infra/envs/dev', 'plan', '-refresh=true', '-input=false',
  "-var=project_id=$P", "-var=region=$R", "-var=billing_account_id=$billingId",
  '-var=github_repository=spark-456/tilo', '-var=github_repository_id=1386743901',
  '-var=github_repository_owner_id=81423861', "-var=alert_email=$alertEmail",
  '-var=budget_amount_usd=15000', '-var=budget_currency_code=INR',
  '-var=api_durable_stores=true', '-var=meet_bot_enabled=true', '-out=sitting2.tfplan'
)
& terraform @planArgs
if ($LASTEXITCODE -ne 0) { throw 'plan failed; stop' }
```

## 3. Review gate: stops on any destroy, replace or unexpected address

```powershell
$Dev = 'infra/envs/dev'
terraform -chdir=$Dev show -no-color sitting2.tfplan | Select-String -Pattern '^Plan:|has moved|must be replaced|will be destroyed'
$plan = terraform -chdir=$Dev show -json sitting2.tfplan | ConvertFrom-Json
$rc = @($plan.resource_changes)
$real = @($rc | Where-Object { ($_.change.actions -join ',') -notin @('no-op', 'read') })
$add = @($real | Where-Object { ($_.change.actions -join ',') -eq 'create' })
$chg = @($real | Where-Object { ($_.change.actions -join ',') -eq 'update' })
$gone = @($real | Where-Object { $_.change.actions -contains 'delete' })   # destroy, or replace (delete + create)
$moved = @($rc | Where-Object { $_.previous_address })
$imported = @($rc | Where-Object { $_.change.importing })   # none expected: the NAT was adopted in section 2.0
"add=$($add.Count) change=$($chg.Count) destroy_or_replace=$($gone.Count) moved=$($moved.Count) import=$($imported.Count)"
if ($gone.Count) { $gone | ForEach-Object { "  $($_.change.actions -join '+')  $($_.address)" }; throw 'STOP: a destroy or replace appears. Do not apply. Send this output for review.' }

$expectAdd = @(
  'google_project_iam_custom_role.artifact_object_delete',
  'google_firestore_field.ttl["limiter_counters"]', 'google_firestore_field.ttl["limiter_keys"]', 'google_firestore_field.ttl["link_nonces"]',
  'google_secret_manager_secret_iam_member.api_link_signing_key',
  'google_service_account.cloudbuild_tests', 'google_storage_bucket_iam_member.cloudbuild_tests_staging_viewer',
  'module.iam.google_project_iam_member.this["cloudbuild-tests::roles/logging.logWriter"]',
  'google_storage_bucket_iam_member.service_access["archive::api::roles/storage.objectCreator"]',
  'google_storage_bucket_iam_member.service_access["archive::api::roles/storage.objectViewer"]',
  'google_storage_bucket_iam_member.service_access["artifacts::api::projects/essential-wares-510320-f0/roles/tiloArtifactObjectDelete"]',
  # the optional bot (MEETING-OPTIONAL-BOT-PLAN-14OCT.md items 1 to 10)
  'google_project_service.apis["texttospeech.googleapis.com"]',
  'module.service.google_service_account.this["meet-bot"]',
  'module.service.google_cloud_run_v2_service.this["meet-bot"]',
  'module.service.google_cloud_run_v2_service_iam_member.invoker["meet-bot::api"]',
  'module.iam.google_project_iam_member.this["meet-bot::projects/essential-wares-510320-f0/roles/tiloVertexGenerate"]',
  'module.iam.google_project_iam_member.this["meet-bot::roles/serviceusage.serviceUsageConsumer"]',
  'module.service.google_cloud_run_v2_service_iam_member.developer["meet-bot::deployer"]',
  'module.service.google_cloud_run_v2_service_iam_member.developer["meet-bot::cloudbuild"]',
  'google_service_account_iam_member.deployer_act_as["meet-bot"]',
  'google_service_account_iam_member.cloudbuild_act_as["meet-bot"]'
)
$expectChange = @(
  'module.service.google_cloud_run_v2_service.env_ignored["api"]',                # item 11: timeout 3600s only
  'module.monitoring.google_monitoring_alert_policy.run_5xx_ratio',              # the filter regex gains tilo-meet-bot
  'module.monitoring.google_monitoring_alert_policy.run_latency_p95'             # same
)
$problems = @()
# The hand-made NAT pair was adopted in section 2 and must not appear: not as an add (import skipped), not as a change
# (the code differs from the live NAT), not as an import (import blocks are not used).
$natPair = @('google_compute_router.nat', 'google_compute_router_nat.run_egress')
$problems += @($rc | Where-Object { $_.address -in $natPair -and (($_.change.actions -join ',') -ne 'no-op' -or $_.change.importing) }) |
  ForEach-Object { "NAT PAIR IN THE PLAN: $($_.address) ($($_.change.actions -join '+')): run the section 2.0 import, or the code differs from the live NAT" }
$problems += @($imported | Where-Object { $_.address -notin $natPair }) | ForEach-Object { "UNEXPECTED import: $($_.address)" }
$problems += @($add.address | Where-Object { $_ -notin $expectAdd }) | ForEach-Object { "UNEXPECTED add: $_" }
$problems += @($expectAdd | Where-Object { $_ -notin $add.address }) | ForEach-Object { "MISSING add: $_" }
$problems += @($chg.address | Where-Object { $_ -notin $expectChange }) | ForEach-Object { "UNEXPECTED change: $_" }
$problems += @($expectChange | Where-Object { $_ -notin $chg.address }) | ForEach-Object { "MISSING change: $_" }
if ($moved.Count -ne 1 -or $moved[0].address -ne 'module.service.google_cloud_run_v2_service.env_ignored["channels"]') { $problems += 'MOVED: expected exactly the tilo-channels state move' }
# Which attributes change in place (names only, never values):
foreach ($c in $chg) {
  $names = @($c.change.after.PSObject.Properties.Name | Where-Object { ($c.change.before.$_ | ConvertTo-Json -Depth 20 -Compress) -ne ($c.change.after.$_ | ConvertTo-Json -Depth 20 -Compress) })
  "  change $($c.address): $($names -join ', ')"
}
if ($problems.Count) { $problems | ForEach-Object { Write-Host $_ -ForegroundColor Red }; throw 'STOP: the plan is not the reviewed one. Do not apply.' }
Write-Host 'Plan matches the reviewed list: nothing is destroyed or replaced.' -ForegroundColor Green
```

Read the changed attribute names above. `env_ignored["api"]` must show only `template` (timeout), and the two alert policies
only `conditions`. A changed Cloud Run image, ingress, scaling or env on any other service is not part of this plan: stop.

## 4. Apply (you, the saved plan only)

```powershell
terraform -chdir=infra/envs/dev apply sitting2.tfplan
if ($LASTEXITCODE -ne 0) { throw 'apply failed; read the error, do not re-plan blindly' }
```

The three TTL policies are long-running operations and can take a few minutes. Then verify (read-only):

```powershell
$P = 'essential-wares-510320-f0'
# Custom role: one permission.
gcloud iam roles describe tiloArtifactObjectDelete --project $P --format='value(includedPermissions)'
# api on the two buckets: archive creator+viewer only; artifacts creator+viewer+custom delete.
foreach ($b in 'archive', 'artifacts') {
  "== $b"
  gcloud storage buckets get-iam-policy "gs://$P-$b" --format=json | ConvertFrom-Json |
    ForEach-Object { $_.bindings } | Where-Object { $_.members -match 'tilo-api@' } | ForEach-Object { $_.role }
}
# TTL policies (state ACTIVE) and that the field's single-field indexes are still configured:
gcloud firestore fields ttls list --database='(default)' --project $P
foreach ($c in 'limiter_counters', 'limiter_keys', 'link_nonces') {
  gcloud firestore indexes fields describe expires_at --collection-group=$c --database='(default)' --project $P --format='yaml(indexConfig.indexes,ttlConfig)'
}
# Test-only identity: its project roles must be exactly roles/logging.logWriter.
gcloud projects get-iam-policy $P --flatten='bindings[].members' --filter='bindings.members:tilo-cloudbuild-tests@' --format='value(bindings.role)'
gcloud secrets get-iam-policy tilo-link-signing-key --project $P --format='value(bindings.members)'
```

If a TTL field shows an empty `indexConfig` (all indexes disabled) where it had indexes before, say so before going on:
the policy was written without an index configuration on purpose.

### 4.1 The NAT already exists (adopted in section 2.0): verify only, before any env step

You created the router and the NAT by hand (about 09:00 on 14 Oct) and adopted them into state in section 2.0, so there
is nothing to create here. The NAT needs no new Cloud Run revision: running instances use it on their next outbound
connection. Order: NAT exists and serves the subnet, then one Home task, then (only if it passes) sections 5 and 6.

```powershell
$P = 'essential-wares-510320-f0'; $R = 'asia-southeast1'
# The NAT exists, serves exactly the egress subnet, and has automatic IPs:
gcloud compute routers nats describe tilo-run-egress-nat --router tilo-nat-router --region $R --project $P `
  --format='yaml(natIpAllocateOption,sourceSubnetworkIpRangesToNat,subnetworks,logConfig)'
gcloud compute routers get-status tilo-nat-router --region $R --project $P --format='yaml(result.natStatus)'
```

Then, in the web app (signed in as the owner), submit one short synthetic task from Home (for example one sentence asking
for a two-line plan). Expect it to be accepted. Server side, read-only:

```powershell
# POST /intake: status 200 (or 2xx) and a latency well under 10 s; before the NAT it was 503 after about 10.9 s.
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="tilo-api" AND httpRequest.requestUrl:"/intake"' `
  --project $P --freshness 15m --limit 10 --format='table(timestamp,httpRequest.status,httpRequest.latency)'
# NAT errors only (dropped connections, port exhaustion); no lines is the expected answer:
gcloud logging read 'resource.type="nat_gateway"' --project $P --freshness 15m --limit 10 --format='table(timestamp,jsonPayload.allocation_status,jsonPayload.connection.dest_ip)'
```

If `/intake` is still 503 with `safety screen failed`, the NAT is not the whole story: stop, and send those log lines and
the `nats describe` output. Do not continue to sections 5 and 6 on a failing Home task.

## 5. Meet bot image (the digest from the details file, section 2)

The digest below still exists in Artifact Registry (checked read-only 14 Oct, tag `be6cbc43`, built 11 Oct). It predates
the current voice and runtime inputs (`MEETING-OPTIONAL-BOT-PLAN-14OCT.md`): it proves guest start-up, auth refusal and a
synthetic tone, not a heard Chirp reply.

```powershell
$P = 'essential-wares-510320-f0'; $R = 'asia-southeast1'
$Digest = 'sha256:2f8ab6057a801462219d0fa219fcf81fb70b8cba288a4e4330ddac7969736d2f'
gcloud artifacts docker images list "$R-docker.pkg.dev/$P/tilo/meet-bot" --include-tags --format='table(version,tags,createTime)'
# Continue only if the digest is listed. If it is not, build a new image first (about 20 minutes, one build):
#   gcloud builds submit --config meet-bot/docker/cloudbuild.yaml --ignore-file meet-bot/docker/cloudbuild.gcloudignore `
#     --project $P --region $R --gcs-source-staging-dir "gs://$P-cloudbuild-staging/source" `
#     --substitutions "_BOT_IMAGE=$R-docker.pkg.dev/$P/tilo/meet-bot:manual-1" .
#   then take the digest it prints and use it below.
gcloud run services update tilo-meet-bot --project $P --region $R --image "$R-docker.pkg.dev/$P/tilo/meet-bot@$Digest"
if ($LASTEXITCODE -ne 0) { throw 'bot image update failed; stop' }
gcloud run services describe tilo-meet-bot --project $P --region $R --format='yaml(spec.template.spec.containers[0].image,spec.template.spec.timeoutSeconds,spec.template.spec.containerConcurrency,spec.template.metadata.annotations,metadata.annotations)'
```

Check: image is the digest, `timeoutSeconds` 3600, `containerConcurrency` 1, `maxScale` 1, ingress `internal`. Keep it private.

## 6. Runtime settings (gcloud; `--update-*` keeps every other setting; secrets only as secret references)

Only after section 4.1 passed (the NAT is in place and a Home task is accepted). Order matters: channels first (api
needs its URL), then api, then the bot. Do 6.1 to 6.3 before 6.5. No command here
removes or rewrites an existing setting (LIVE, the stores, the schedule tick settings stay).

```powershell
$P = 'essential-wares-510320-f0'; $R = 'asia-southeast1'
$ApiSa = gcloud run services describe tilo-api --project $P --region $R --format='value(spec.template.spec.serviceAccountName)'
$ChUrl = gcloud run services describe tilo-channels --project $P --region $R --format='value(status.url)'
$ApiUrl = gcloud run services describe tilo-api --project $P --region $R --format='value(status.url)'
if (-not $ApiSa -or $ChUrl -notmatch '^https://[a-z0-9.-]+\.run\.app$' -or $ApiUrl -notmatch '^https://[a-z0-9.-]+\.run\.app$') { throw 'URLs or service account missing; stop' }
```

### 6.1 tilo-channels: web push

`TILO_PUSH_AUDIENCE` and tilo-api's `TILO_CHANNELS_URL` must be the same string (the token's audience). The contact is
the address push services may write to about Tilo's pushes: a Tilo address, not a person's mailbox.

```powershell
$Subject = Read-Host 'Tilo contact for push services, as mailto:name@domain'
if ($Subject -notmatch '^mailto:[^\s@]{1,64}@[^\s@]{1,190}$') { throw 'must look like mailto:name@domain; stop' }
gcloud run services update tilo-channels --project $P --region $R `
  --update-secrets 'WEBPUSH_VAPID_PRIVATE_KEY=webpush-vapid-private-key:latest' `
  --update-env-vars "^#^TILO_WEBPUSH_VAPID_SUBJECT=$Subject#TILO_PUSH_AUDIENCE=$ChUrl#TILO_PUSH_CALLER=$ApiSa"
if ($LASTEXITCODE -ne 0) { throw 'channels update failed; stop' }
```

### 6.2 The public key, derived without printing the private key

`scripts/vapid_public_key.py` parses the secret exactly as tilo-channels does (PEM, base64url raw or DER) and prints only
the 87-character public point. The private key travels in a pipe and is never written or shown.

```powershell
$Pub = gcloud secrets versions access latest --secret=webpush-vapid-private-key --project $P |
  uv run --package tilo-channels --frozen python -I scripts/vapid_public_key.py
if ($LASTEXITCODE -ne 0 -or $Pub -notmatch '^[A-Za-z0-9_-]{87}$') { throw 'could not derive the public key; stop (nothing was printed from the secret)' }
"public key length: $($Pub.Length)"
```

### 6.3 tilo-api: push, uploads, link signing, skills store

* `TILO_SKILLS_STORE=firestore` (with `TILO_FIRESTORE_PROJECT`, already set): **done** (set on tilo-api, revision
  `tilo-api-00048-hzq`; `--update-env-vars` keeps it, so the command below may repeat it or leave it out). Before it,
  `GET /v1/skills` answered 503 `not_configured` (`SkillStoreNotConfigured`, `deps.get_skill_store`). Documents live at `orgs/{org}/taught_skills/{id}` in
  the `(default)` database with single-field queries only, so no index is needed and tilo-api's existing
  `datastore.user` (conditioned to `(default)`) covers it. Roll back with `--remove-env-vars TILO_SKILLS_STORE`.
* `TILO_ARTIFACTS_STORE` / `TILO_ARCHIVE_STORE` = `gcs` with the two real buckets. The code refuses the same bucket for both,
  and refuses `GOOGLE_CLOUD_PROJECT` differing from `TILO_FIRESTORE_PROJECT` (both are already set and equal).
  Setting these makes run archives and artifacts durable and opens uploads; uploads were `503 not_configured` before.
* Link signing: the key is a secret reference. `TILO_LINK_BASE_URL` is the **API's own https origin**, not the hosted web
  address: Hosting rewrites everything unknown to `index.html`, so `/l/<token>` only reaches the route on the API. With the
  key set, `GET` and `POST /l/<token>` are configured; the route is public by the owner's 13 Oct decision (BQ-PA06B-4). No
  mail is sent: `TILO_PLATE_DIGEST` stays off (6.4).

```powershell
gcloud run services update tilo-api --project $P --region $R `
  --update-secrets 'TILO_LINK_SIGNING_KEY=tilo-link-signing-key:latest' `
  --update-env-vars "^#^TILO_WEBPUSH_VAPID_PUBLIC_KEY=$Pub#TILO_CHANNELS_URL=$ChUrl#TILO_ARTIFACTS_STORE=gcs#TILO_ARTIFACTS_BUCKET=$P-artifacts#TILO_ARCHIVE_STORE=gcs#TILO_ARCHIVE_BUCKET=$P-archive#TILO_LINK_KEY_ID=key_a#TILO_LINK_BASE_URL=$ApiUrl#TILO_SKILLS_STORE=firestore"
if ($LASTEXITCODE -ne 0) { throw 'api update failed; stop' }
```

### 6.4 Left off on purpose: `TILO_PLATE_DIGEST`

Do not set it in this sitting. The plate mail needs, and today lacks: (1) the owner's standing L3 `send_email` policy pinned
to their own address, which no route creates (BQ-CHN18B-1, "needs product decision"); (2) PR #704 (quiet hours fail closed
when a zone cannot be resolved, digest `policy.applied` only after the enqueue), which is open, so today an unresolvable
zone means "not quiet" and the send proceeds; (3) connectors' live switch, because the digest sends through the live Gmail
connector. #876 and #890 cleared the mail builder and the link route, not the activation. The send is real mail to the
owner's own address and is the user's call once those three exist.

### 6.5 Meet bot wiring (no live switch yet)

The audience must equal the URL tilo-api calls: both are the bot's `status.url`. The bot answers 503 "not enabled" until
it carries its own live switch (section 10); tilo-api already carries its live switch, so setting `TILO_MEET_BOT_URL` arms
only the API half.

```powershell
$Bot = gcloud run services describe tilo-meet-bot --project $P --region $R --format='value(status.url)'
if ($Bot -notmatch '^https://[a-z0-9.-]+\.run\.app$') { throw 'bot URL unavailable; stop' }
gcloud run services update tilo-meet-bot --project $P --region $R `
  --update-env-vars "^#^BOT_JOIN_MODE=guest#GOOGLE_CLOUD_PROJECT=$P#GOOGLE_LOCATION=$R#TILO_MEET_BOT_AUDIENCE=$Bot#TILO_MEET_BOT_CALLER=$ApiSa"
if ($LASTEXITCODE -ne 0) { throw 'bot env failed; stop' }
gcloud run services update tilo-api --project $P --region $R --update-env-vars "TILO_MEET_BOT_URL=$Bot"
if ($LASTEXITCODE -ne 0) { throw 'api bot url failed; stop' }
```

Terraform manages the bot's env in full (`ignore_env = false`): a later apply resets these settings. Re-run 6.5 after any
apply that touches `tilo-meet-bot`.

## 7. Verification (read-only)

```powershell
# Ready, revision and image per service.
foreach ($s in 'tilo-api', 'tilo-channels', 'tilo-meet-bot') {
  $d = gcloud run services describe $s --project $P --region $R --format=json | ConvertFrom-Json
  $ready = ($d.status.conditions | Where-Object { $_.type -eq 'Ready' }).status
  "$s  Ready=$ready  rev=$($d.status.latestReadyRevisionName)  ingress=$($d.metadata.annotations.'run.googleapis.com/ingress')"
}
```

Env drift check: names only, never a value. Flags names that must not exist and names that are missing.

```powershell
function Test-Env($Service, [string[]]$Expect, [string[]]$Never) {
  $d = gcloud run services describe $Service --project $P --region $R --format=json | ConvertFrom-Json
  $names = @($d.spec.template.spec.containers[0].env | ForEach-Object { $_.name })
  $bad = @()
  $bad += $Never | Where-Object { $_ -in $names } | ForEach-Object { "FORBIDDEN: $_" }
  $bad += $Expect | Where-Object { $_ -notin $names } | ForEach-Object { "MISSING: $_" }
  $bad += $names | Where-Object { $_ -notin $Expect -and $_ -notin $Never } | ForEach-Object { "EXTRA (check it is yours): $_" }
  if ($bad) { $bad | ForEach-Object { Write-Host "$Service $_" -ForegroundColor Yellow } } else { Write-Host "$Service env OK ($($names.Count) names)" }
}
$ApiNames = 'TILO_SCHEDULE_TICK_AUDIENCE', 'TILO_SCHEDULE_TICK_CALLER', 'TILO_RUNS_QUEUE', 'TILO_API_CORS_ORIGINS', 'TILO_FIRESTORE_PROJECT',
  'TILO_TASKS_CALLER', 'TILO_SCHEDULES_STORE', 'TILO_TEAM_STORE', 'TILO_API_STORE', 'TILO_PEOPLE_STORE', 'TILO_OUTBOX_STORE', 'TILO_CONNECTORS_URL',
  'LIVE', 'GOOGLE_CLOUD_PROJECT', 'GOOGLE_LOCATION',
  'TILO_WEBPUSH_VAPID_PUBLIC_KEY', 'TILO_CHANNELS_URL', 'TILO_ARTIFACTS_STORE', 'TILO_ARTIFACTS_BUCKET', 'TILO_ARCHIVE_STORE', 'TILO_ARCHIVE_BUCKET',
  'TILO_LINK_SIGNING_KEY', 'TILO_LINK_KEY_ID', 'TILO_LINK_BASE_URL', 'TILO_MEET_BOT_URL', 'TILO_SKILLS_STORE'
$Emul = 'API_ENDPOINT_OVERRIDE', 'FIRESTORE_EMULATOR_HOST', 'STORAGE_EMULATOR_HOST', 'TILO_API_DEV', 'TILO_JUDGE_LIVE', 'TILO_MODELS_FILE', 'TILO_RECORD', 'TILO_PLATE_DIGEST'
Test-Env 'tilo-api' ($ApiNames + @('TILO_NUDGES')) $Emul   # TILO_NUDGES shows MISSING until 6.6; that is expected
Test-Env 'tilo-channels' @('WEBPUSH_VAPID_PRIVATE_KEY', 'TILO_WEBPUSH_VAPID_SUBJECT', 'TILO_PUSH_AUDIENCE', 'TILO_PUSH_CALLER') ($Emul + 'LIVE')
Test-Env 'tilo-meet-bot' @('BOT_JOIN_MODE', 'GOOGLE_CLOUD_PROJECT', 'GOOGLE_LOCATION', 'TILO_MEET_BOT_AUDIENCE', 'TILO_MEET_BOT_CALLER') $Emul
```

(`TILO_RECORD` and the live switch on the bot are expected to be absent now; the bot gets its switch only in section 10.)
Also, the next Terraform plan on this branch must show no change for tilo-channels env (it is `ignore_env`). Quick proof:
`gcloud run services describe tilo-channels --format='value(spec.template.spec.containers[0].env[].name)'` before and
after a plan-only run lists the same names.

### 6.6 Optional: nudges (in-app only, no mail, no push)

`TILO_NUDGES` makes the schedule tick raise `alert.raised` nudges in each person's own Desk world inside their working
window, capped, once per item, with snooze (`nudge_sweep.py`, PR #892 merged). It sends nothing outside the app and the
push kinds exclude nudges. It adds a few Firestore reads per tick per in-window person. Do it last, after section 7 is
clean, so a problem is attributable.

```powershell
gcloud run services update tilo-api --project $P --region $R --update-env-vars 'TILO_NUDGES=1'
```

Undo: `--remove-env-vars TILO_NUDGES`.

## 8. Android Chrome push test

On your Android phone, in Chrome (not an in-app browser), with a second device (desktop) signed in as the same owner:

1. Phone: open `https://essential-wares-510320-f0.web.app`, sign in, Profile, Notifications, Browser notifications. Read the consent
   line, accept, and allow the browser permission when Chrome asks.
2. Phone: lock the screen (or switch to another app). Confirm the page shows one device registered.
3. Desktop: start a task that raises a gate card (any send that needs your approval) so the card appears on the desktop.
4. Time it: run the stopwatch below on the desktop at the moment you trigger the card, and press Enter when the phone shows
   the notice. The notice reads "A send is waiting for your approval" with no content; tapping it opens the card.

```powershell
Read-Host 'Press Enter at the moment the card is raised' | Out-Null
$sw = [Diagnostics.Stopwatch]::StartNew()
Read-Host 'Press Enter when the notice shows on the phone' | Out-Null
"{0:N1} s (the bound is 10 s)" -f $sw.Elapsed.TotalSeconds
```

5. Server side (read-only): the send reached channels and was answered:

```powershell
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="tilo-channels" AND httpRequest.requestUrl:"/internal/push/send"' `
  --project $P --freshness 15m --limit 10 --format='table(timestamp,httpRequest.status)'
```

200 = delivered or reported gone. 401/403 = the audience, the caller email or the secret is wrong (compare `TILO_PUSH_AUDIENCE`
with `TILO_CHANNELS_URL`, `TILO_PUSH_CALLER` with the tilo-api service account). 503 = a setting is missing.
6. Phone: turn Browser notifications off in the same place; the device is removed and no further notice arrives.

### Network: what is already allowed, and what is not

* **Egress from tilo-channels (push hosts)**: nothing to change for channels itself. `channels` has no VPC egress in
  `main.tf`, so it uses Cloud Run's default direct egress to the internet, and the environment has no firewall rule or egress
  allow-list. HTTPS to `fcm.googleapis.com`, `push.services.mozilla.com`, `notify.windows.com`, `web.push.apple.com` and
  `www.googleapis.com` is therefore already open and does not use the NAT. The sender still checks the host list in
  `config/web_push.yaml`, and that every resolved address is public, per request.
* **Egress from tilo-api and tilo-harness: this was broken, and the plan fixes it.** (An earlier version of this runbook and
  of BQ-INFRA-S2-1 said "egress needs no change"; that holds for channels only.) Both send ALL_TRAFFIC into
  `tilo-vpc/tilo-run-egress`, which had Private Google Access but **no Cloud Router or Cloud NAT**. Private Google Access
  reaches Google's global API VIPs and `*.run.app`; it does not reach the regional Model Armor endpoint
  (`modelarmor.asia-southeast1.rep.googleapis.com`) or any non-Google host (NVIDIA NIM, Canva, Lovable, vendor sites), so those
  calls hung until the client timed out (the Home 503 after about 10.9 s). `network.tf` now adds `tilo-nat-router` and the NAT
  `tilo-run-egress-nat` for that one subnet. ALL_TRAFFIC stays: calls to internal-only services need it.
* **tilo-api to tilo-channels**: api's egress is `ALL_TRAFFIC` through the subnet, and `*.run.app` is reached with Private Google
  Access (the same path api uses to reach connectors and harness), not through the NAT. Channels has ingress `all`, so the
  call passes.
* **Ingress from tilo-api only**: NOT what is deployed, and not changeable by a firewall entry. `tilo-channels` must stay
  public (`INGRESS_TRAFFIC_ALL`, `allUsers` invoker): the Gmail push subscription and WhatsApp webhooks call it from outside
  the VPC. `POST /internal/push/send` is protected by the route itself: a Google-signed ID token for
  `TILO_PUSH_AUDIENCE` and a verified email equal to `TILO_PUSH_CALLER`, refused (503) while either is unset. That is the
  same pattern `infra/ACCESS.md` requires of every channels `/internal/` route. Splitting push into an internal-only service
  would be a design change: open question BQ-INFRA-S2-1.

## 9. Test-only gate identity: when you want to use it

Not changed here (`scripts/gate_cloud.py` and `cloudbuild.tests.yaml` are untouched). To switch the cloud test gate, change
the one `serviceAccount:` line of `cloudbuild.tests.yaml` to `tilo-cloudbuild-tests@essential-wares-510320-f0.iam.gserviceaccount.com`,
and run one gate. You, as Owner, already hold `iam.serviceAccounts.actAs` on it; the identity can read the staging bucket and
write build logs, and cannot deploy, push images, read secrets or act as another account.

## 10. Owner-led bot test and switch-off

Preconditions: sections 4 to 7 are green, your own Firebase session works, and you have read the price section of
`MEETING-OPTIONAL-BOT-PLAN-14OCT.md` (about INR 7 of bot compute per ten minutes, plus Chirp output at 400 characters a
reply; STT and model prices are not yet quoted there). Use synthetic meeting content and a test meeting you host.

**Baseline, recorded 14 Oct 01:30 IST (read-only):** `tilo-api` already carries the live switch (production go-live,
revision 00045); `tilo-connectors` and `tilo-meet-bot` do not. "Switch-off" below therefore restores the baseline: it
removes the switch from the bot and connectors only and **leaves tilo-api as it was**. (The switch-off block in the details
file removes it from `tilo-api` too; do not run that part, it would turn production's live paths off.)

1. Capture the baseline again just before you start:

```powershell
foreach ($s in 'tilo-api', 'tilo-connectors', 'tilo-meet-bot') {
  $names = gcloud run services describe $s --project $P --region $R --format='value(spec.template.spec.containers[0].env[].name)'
  "$s has LIVE: " + (($names -split ';') -contains 'LIVE')
}
```

2. Take the two live-switch commands from `agy-bridge/tasks/USER-INFRA-SITTING-2-DETAILS-20261012.md`, section 4: the
   `tilo-connectors` command and the `tilo-meet-bot` command. Run those two only. Skip its `tilo-api` command (the API already
   has the switch, and `TILO_MEET_BOT_URL` and the bot settings were set in 6.5). Their literal text is not repeated here on
   purpose: the repository guard blocks it, and the switch is yours. Gemini Live stays off: `config/voice.yaml`
   `live.enabled` and `live.price_approved` remain false and nothing in this sitting touches them.
3. Run the attendance from the owner's side with the existing script (it asks for your Firebase ID and App Check tokens
   without echo; keep the window connected, a disconnect cancels the capture):

```powershell
$meetingId = Read-Host 'Your owner meeting ID (mt_...)'
& ./meet-bot/scripts/attend-owner.ps1 -ApiUrl $ApiUrl -MeetingId $meetingId
```

4. In the meeting: admit "Tilo notetaker" as host (guest admission is human-led), check the disclosure before capture, say
   a synthetic decision, ask Tilo a question, and **listen for the spoken reply** (chat text is not enough). Say or type
   "Tilo leave". Then, as owner, open the saved transcript; check no Meet URL is stored and that another account is refused.
   Do not retry a launch automatically; look at the owner meeting state first.
5. Switch off, restoring the baseline (bot and connectors only):

```powershell
foreach ($s in 'tilo-meet-bot', 'tilo-connectors') {
  gcloud run services update $s --project $P --region $R --remove-env-vars=LIVE
  if ($LASTEXITCODE -ne 0) { throw "Could not switch off $s; stop and report" }
}
```

Then re-run the baseline capture: bot and connectors must say `False`, api `True`. The bot scales to zero on its own
(min 0, no idle instance).

## 11. Rollback

Settings (each is a merge; nothing else is touched):

```powershell
gcloud run services update tilo-channels --project $P --region $R `
  --remove-env-vars 'TILO_WEBPUSH_VAPID_SUBJECT,TILO_PUSH_AUDIENCE,TILO_PUSH_CALLER' --remove-secrets 'WEBPUSH_VAPID_PRIVATE_KEY'
gcloud run services update tilo-api --project $P --region $R `
  --remove-env-vars 'TILO_WEBPUSH_VAPID_PUBLIC_KEY,TILO_CHANNELS_URL,TILO_ARTIFACTS_STORE,TILO_ARTIFACTS_BUCKET,TILO_ARCHIVE_STORE,TILO_ARCHIVE_BUCKET,TILO_LINK_KEY_ID,TILO_LINK_BASE_URL,TILO_NUDGES,TILO_MEET_BOT_URL,TILO_SKILLS_STORE' `
  --remove-secrets 'TILO_LINK_SIGNING_KEY'
gcloud run services update tilo-meet-bot --project $P --region $R `
  --remove-env-vars 'BOT_JOIN_MODE,TILO_MEET_BOT_AUDIENCE,TILO_MEET_BOT_CALLER'
```

Removing the store settings returns uploads to `503 not_configured` and the run archive to its previous door. Documents
already written in Firestore, objects already written to the buckets and anything the TTL policies already deleted are not
restored by any of this.

Infrastructure: the additions are removable, but only by a reviewed plan, never by editing the state:

* Take the previous commit of `infra/` for the three storage grants, `sitting2.tf` and the `logWriter` entry, and **keep the
  `ignore_env` flag and the `moved` block for tilo-channels** (removing only the `moved` block would plan a destroy and
  create of the channels service). Plan with the same variables as section 2 and read it: the only destroys allowed are the
  resources of this sitting (custom role, three TTL fields, accessor, test identity and its two grants, the three storage
  grants and, if you also set `meet_bot_enabled=false`, the bot's ten resources). Any other destroy: stop. Do not roll the
  NAT back unless you accept that Home's safety screen (Model Armor) and every non-Google call from api and harness hang
  again; if you must, it is two resources (`tilo-run-egress-nat`, `tilo-nat-router`) and removing them changes nothing else.
* A deleted custom role is soft-deleted for 7 days; recreate it within that window with `gcloud iam roles undelete`.
* Destroying a TTL field config only stops deletion; it does not restore deleted documents.
