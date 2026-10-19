# FR-MTG-09 operator rehearsal

Status: Cloud Build's image startup, auth refusal, guest Chromium and synthetic
virtual-microphone tone checks have passed with LIVE off. This is not a demonstrated
live Meet. The user completed the production infrastructure sitting and Workspace
OAuth secret versions on 12 October. The optional bot infrastructure still needs
its reviewed opt-in apply. No paid model calls have run in this implementation.
The current acceptance checklist is
`agy-bridge/tasks/MEETING-GO-LIVE-13OCT.md` in the coordination checkout. It tracks
the exact reviewed heads, image certification, minutes/index and human acceptance
holds. Infrastructure apply and live switches stay with the user; CX-MERGE-A alone
deploys cleared images. Source instructions are not deployment evidence.

## Prerequisites

- Review/merge the Meet boundary and deployment PRs through CX-MERGE. The final
  spoken image also needs #705's character pricing and #719's Chirp streaming adapter,
  or the CX voice integration branch containing those unchanged upstream commits.
  Approve the price sheet and its regional setting before enabling live calls.
- Use the actual dev GCP project ID for `$P`; `tilo-dev` is the environment name.
  Existing Terraform variables and backend must already identify that project.
- Deploy the current API and connectors images through the existing
  `just deploy-dev-cloudbuild api dev` and `just deploy-dev-cloudbuild connectors dev`
  flow. The coordinator is resolving the production wiring PRs and uses this
  route; `just deploy dev` is a refusing stub and should not be used.
- The authenticated API needs its existing durable world/people/artifact stores,
  owner sign-in, App Check and screening configuration. Preserve those settings;
  this bot change does not replace the existing production rollout.
- In the owner's Tilo session, connect the meeting-host grant using the **confirmed
  bot Google account**, then host a scheduled bot meeting through the existing
  owner host route. The user completes OAuth/password entry. The invitation receipt
  must be stored in that meeting's owner world. A human participant admits the bot.

## User-run infrastructure and verified image

After the bot PRs are reviewed and merged, add `-var=meet_bot_enabled=true` to
CX-MERGE's complete saved-plan command for the optional bot follow-up. Keep every
existing variable/backend setting; do not plan with only the bot flag. The flag
is already defined in `infra/envs/dev/variables.tf` and defaults to false. If the
plan contains any destroy or replacement, stop and ask before applying. Only the
user applies the reviewed saved plan.

After the optional bot infrastructure has been applied, A must supply the exact
cleared source head, certified digest and passed offline image-gate report. The
historical image below lacks the Gemini Live adapter and cannot certify the current
replay/Live chain. Once the current image is certified, A uses these dev-only commands:

```powershell
$P = 'essential-wares-510320-f0'
$R = 'asia-southeast1'
$Digest = Read-Host 'A-certified current bot image digest (sha256:...)'
if ($Digest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Invalid certified digest; stop' }
$Image = "$R-docker.pkg.dev/$P/tilo/meet-bot@$Digest"
gcloud run services update tilo-meet-bot --project=$P --region=$R --image=$Image
if ($LASTEXITCODE -ne 0) { throw 'Deployment failed; stop' }
$Bot = gcloud run services describe tilo-meet-bot --project=$P --region=$R --format='value(status.url)'
$Api = gcloud run services describe tilo-api --project=$P --region=$R --format='value(status.url)'
```

Historical Cloud Build `a2b73e0f-c1a1-4945-8e7b-ae9a2ba29769` verified digest
`sha256:2f8ab6057a801462219d0fa219fcf81fb70b8cba288a4e4330ddac7969736d2f`
from runtime source `be6cbc43`. That evidence applies only to that older image.
Do not enable LIVE before the user's price review.

The optional service has internal ingress, only the API's invoker grant, zero idle
instances, one active request/instance, 2 CPUs/4 GiB and a 3600-second deadline. It
holds ADC permissions for Vertex inference and service usage, not OAuth tokens,
Firestore or artifact buckets. Never make it public to simplify testing.

The **user** enables the live switch after reviewing the configured prices:

```powershell
gcloud run services update tilo-meet-bot --project=$P --region=$R --update-env-vars="^#^LIVE=1#GOOGLE_CLOUD_PROJECT=$P#GOOGLE_LOCATION=$R#BOT_JOIN_MODE=guest#TILO_MEET_BOT_AUDIENCE=$Bot#TILO_MEET_BOT_CALLER=tilo-api@$P.iam.gserviceaccount.com"
if ($LASTEXITCODE -ne 0) { throw 'Bot activation failed; stop' }
gcloud run services update tilo-api --project=$P --region=$R --update-env-vars="^#^LIVE=1#TILO_MEET_BOT_URL=$Bot"
if ($LASTEXITCODE -ne 0) { throw 'API activation failed; stop' }
```

Preserve the API's existing model location, including its user-approved global
Gemini setting, Model Armor region and durable-store environment. The API command
changes only LIVE and the bot URL. Keep `voice.live.enabled: false` and
`voice.live.price_approved: false` for Chirp acceptance. The optional Live adapter
passes offline fake/recorded lifecycle tests; this does not prove heard voice or
approve its live price.

The bot has no persistent browser profile. Terraform manages its environment in
full; a later apply can reset these runtime variables, which safely disables it.
Recheck configuration after an apply. Keep `TILO_RECORD` unset on both services.

## One real acceptance meeting

Use the direct `$Api` Cloud Run endpoint, not the Firebase Hosting rewrite:
[Hosting requests time out after 60 seconds](https://firebase.google.com/docs/hosting/cloud-run).
The attendance request stays open until capture ends (maximum 45 minutes); closing
it cancels the browser and does not attach partial notes. There is no automatic
launch retry. Do not launch attendance from a demo session or with fake providers.

The bot leaves earlier when: 60 s after the last other person leaves; 900 s after joining when nobody arrives; or
300 s (`UNREADABLE_LEAVE_SECONDS`) after the People panel and head count both became unreadable with no caption in
that time. It makes no model call while nobody speaks (FR-MTG-09), so the 200-call meeting budget goes to answers.
The host form and `meeting_host.max_duration_min` are capped at 45 minutes to match (BQ-MEETBOT-1).

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
An already-running synchronous provider SDK call can finish after cancellation;
cloud content-log filters and per-capture counters isolate its late completion.

Minutes/follow-up routes are a separate default-off integration. Activation needs
same-head independent acceptance and final delta security review, all seven
retention indexes provisioned/READY, and the exact API rollout. The coordination
checklist supplies the analyze, inspect, confirm and draft sequence. A durable
T3 preview needs owner approval; worker acceptance performs no real send. The
transcript alone does not prove minutes/follow-up publication. A web attendance
button is not included. The existing join limiter is per API process.
A crash or owner edit during failed capture can leave `joining` needing operator
recovery; this slice does not add a durable lease/reaper. Cloud anti-automation,
admission selectors, microphone routing and heard audio remain unverified live.

## Live voice meter (ADR-0042, BQ-M2-4; INERT until you set the settings and flip the voice)

The Gemini Live voice speaks a reply only if tilo-api reserves SEC-16 spend for it first. The bot holds no ledger, uid
or org: per reply it names its meeting id, the claim nonce tilo-api put in the attend call (header
`X-Tilo-Meeting-Claim`) and a key of its own to `POST /internal/meeting-voice/reserve` and `/close` on tilo-api, with an
ID token its metadata server mints for audience `TILO_API_URL`. Anything but a 200 `live` is the local voice.
With `TILO_API_URL` unset, or `voice.live.enabled: false` (the shipped value), the Live voice is never built and the bot
speaks as it does today. The settings are `gcloud` env, not Terraform: tilo-api has `ignore_env`, and the service module
declares no env for the bot, so a later apply clears the bot's (which only turns the Live voice off).

| Service | Setting | Value |
| --- | --- | --- |
| `tilo-meet-bot` | `TILO_API_URL` | tilo-api's service URL, `https://host`, no path, query or trailing slash |
| `tilo-api` | `TILO_VOICE_METER` | `1` (exactly; anything else leaves both routes a plain 404) |
| `tilo-api` | `TILO_VOICE_METER_AUDIENCE` | the same URL string as `TILO_API_URL`, character for character |
| `tilo-api` | `TILO_VOICE_METER_CALLER` | `tilo-meet-bot@$P.iam.gserviceaccount.com`; never the tick's or the Tasks account |

```powershell
$Api = gcloud run services describe tilo-api --project=$P --region=$R --format='value(status.url)'
$BotSa = "tilo-meet-bot@$P.iam.gserviceaccount.com"
gcloud run services update tilo-api --project=$P --region=$R --update-env-vars="^#^TILO_VOICE_METER=1#TILO_VOICE_METER_AUDIENCE=$Api#TILO_VOICE_METER_CALLER=$BotSa"
gcloud run services update tilo-meet-bot --project=$P --region=$R --update-env-vars="TILO_API_URL=$Api"
```

Unchanged: the bot keeps its two project roles, no Firestore or ledger access and no new secret; tilo-api stays one
instance (the claim and nonce live in its process); the bot's ingress stays internal only and only tilo-api may invoke
it; `LIVE=1` stays the user's, set on the bot for the sitting and removed after (the meter routes never read it). The ordered steps, the checks and the
rollback (`--remove-env-vars TILO_VOICE_METER` on tilo-api) are in `docs/deploy-dev.md` ("The meeting bot's Live voice
meter"). Do not deploy or change tilo-api settings during an attended meeting: its claim ends with the old process,
so that meeting answers 409 and the rest of it is spoken with the local voice.

## End the acceptance test — user only

Limit the acceptance sitting to ten minutes. After **Tilo leave**, remove LIVE
even if attendance failed; use a second terminal if the attendance command is
still open. Restore `$P` and `$R` from the deployment block above, then run:

```powershell
foreach ($serviceName in @('tilo-meet-bot', 'tilo-api', 'tilo-connectors')) {
  gcloud run services update $serviceName --project=$P --region=$R --remove-env-vars=LIVE
  if ($LASTEXITCODE -ne 0) { throw "Could not disable $serviceName; stop and report" }
}
```

API LIVE is process-wide; include connectors if it was activated for hosting.
Confirm each service is Ready and has no LIVE variable, then check the bot has no
active attendance and scales to zero. Keep the transcript reference and human-heard
result. A failed launch needs state inspection before another attendance request.

## Local account fallback

Only the dedicated demo machine may keep a signed-in profile (ADR-0017/0024).
Set `BOT_GOOGLE_EMAIL` to the confirmed bot account; never reuse the owner's profile.
The user signs in once. The inherited local noVNC/profile setup still needs its
separate hardening review before use. Never mount this profile into Cloud Run.
