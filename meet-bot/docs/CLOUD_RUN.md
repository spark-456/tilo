# FR-MTG-09 operator rehearsal

Status: offline implementation, not a demonstrated live Meet. No infrastructure has
been applied and no paid calls have run. The bot image has not built locally because
Docker Desktop's daemon does not respond. Cloud Build below is an alternative **the
user runs**, with its normal build charges. Review the PRs first.

## Prerequisites

- Review/merge the Meet boundary and deployment PRs through CX-MERGE. The final
  spoken image also needs #705's character pricing and #719's Chirp streaming adapter,
  or the CX voice integration branch containing those unchanged upstream commits.
  Approve the price sheet and its regional setting before enabling live calls.
- Use the actual dev GCP project ID for `$P`; `tilo-dev` is the environment name.
  Existing Terraform variables and backend must already identify that project.
- Deploy the current API and connectors images through the existing
  `just deploy-dev-cloudbuild api dev` and `just deploy-dev-cloudbuild connectors dev`
  flow after infrastructure is applied. The coordinator's deployment stub and held
  production wiring PRs must be resolved before these commands can work.
- The authenticated API needs its existing durable world/people/artifact stores,
  owner sign-in, App Check and screening configuration. Preserve those settings;
  this bot change does not replace the existing production rollout.
- In the owner's Tilo session, connect the meeting-host grant using the **confirmed
  bot Google account**, then host a scheduled bot meeting through the existing
  owner host route. The user completes OAuth/password entry. The invitation receipt
  must be stored in that meeting's owner world. A human participant admits the bot.

## User-run infrastructure and image

From the reviewed repository checkout, use your existing dev variables/backend:

```powershell
terraform -chdir=infra/envs/dev plan -var-file=<existing-dev-vars> -var=meet_bot_enabled=true -out=meet-bot.tfplan
# Review the plan; the user applies it, never the agent.
terraform -chdir=infra/envs/dev apply meet-bot.tfplan
$P = '<actual dev project ID>'
$R = 'asia-southeast1'
$Tag = git rev-parse --short HEAD
$Image = "$R-docker.pkg.dev/$P/tilo/meet-bot:$Tag"
gcloud builds submit . --project=$P --region=$R --config=meet-bot/docker/cloudbuild.yaml --ignore-file=meet-bot/docker/cloudbuild.gcloudignore --substitutions="_BOT_IMAGE=$Image"
gcloud run services update tilo-meet-bot --project=$P --region=$R --image=$Image
$Bot = gcloud run services describe tilo-meet-bot --project=$P --region=$R --format='value(status.url)'
$Api = gcloud run services describe tilo-api --project=$P --region=$R --format='value(status.url)'
```

The optional service has internal ingress, only the API's invoker grant, zero idle
instances, one active request/instance, 2 CPUs/4 GiB and a 3600-second deadline. It
holds ADC permissions for Vertex inference and service usage, not OAuth tokens,
Firestore or artifact buckets. Never make it public to simplify testing.

The **user** enables the live switch after reviewing the configured prices:

```powershell
gcloud run services update tilo-meet-bot --project=$P --region=$R --update-env-vars="^#^LIVE=1#GOOGLE_CLOUD_PROJECT=$P#GOOGLE_LOCATION=$R#BOT_JOIN_MODE=guest#TILO_MEET_BOT_AUDIENCE=$Bot#TILO_MEET_BOT_CALLER=tilo-api@$P.iam.gserviceaccount.com"
gcloud run services update tilo-api --project=$P --region=$R --update-env-vars="^#^LIVE=1#GOOGLE_CLOUD_PROJECT=$P#GOOGLE_LOCATION=$R#TILO_MEET_BOT_URL=$Bot"
```

The bot has no persistent browser profile. Terraform manages its environment in
full; a later apply can reset these runtime variables, which safely disables it.
Recheck configuration after an apply. Keep `TILO_RECORD` unset on both services.

## One real acceptance meeting

Use the direct `$Api` Cloud Run endpoint, not the Firebase Hosting rewrite:
[Hosting requests time out after 60 seconds](https://firebase.google.com/docs/hosting/cloud-run).
The attendance request stays open until capture ends (maximum 45 minutes); closing
it cancels the browser and does not attach partial notes. There is no automatic
launch retry. Do not launch attendance from a demo session or with fake providers.

Run `meet-bot/scripts/attend-owner.ps1 -ApiUrl $Api -MeetingId <owner-meeting-id>`.
It prompts locally for the owner's Firebase ID token and App Check token, without
echoing them or recording them in command history. Obtain those tokens from your
own authenticated client; never paste them into chat. Keep this terminal connected.

1. Admit **Tilo notetaker** to the Meet; guest entry must be permitted by the host.
2. Confirm the disclosure appears before notes are captured. No disclosure means
   refusal and browser cleanup.
3. Say a short decision, then ask a question addressed to Tilo. Confirm a human hears
   a Chirp reply and its chat mirror. A chat reply alone does not prove speech.
4. A participant sends **Tilo leave**. Confirm the bot leaves and the attendance
   request completes with an ended meeting and transcript artifact reference.
5. Read the transcript as the owner; verify the spoken decision and no Meet URL.
   Verify another owner receives 404. Check the bot instance/browser has stopped.

Cloud worker logs suppress participant/provider content. Transient capture files
are deleted. The API screens/redacts and attaches a scoped Transcript artifact with
30-day retention. A join GET starts no bot or world event. Owner deletion or a
concurrent conflicting attachment prevents the transcript from being attached.

Known limits: minutes summarization and a web attendance button are not included;
the transcript is the saved notes. The existing join limiter is per API process.
A crash or owner edit during failed capture can leave `joining` needing operator
recovery; this slice does not add a durable lease/reaper. Cloud anti-automation,
admission selectors, microphone routing and heard audio remain unverified live.

## Local account fallback

Only the dedicated demo machine may keep a signed-in profile (ADR-0017/0024).
Set `BOT_GOOGLE_EMAIL` to the confirmed bot account; never reuse the owner's profile.
The user signs in once. The inherited local noVNC/profile setup still needs its
separate hardening review before use. Never mount this profile into Cloud Run.
