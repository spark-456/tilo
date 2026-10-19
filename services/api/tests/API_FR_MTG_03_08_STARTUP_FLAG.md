# Owner minutes startup flag (ACT-4)

`config/meeting.yaml` contains `meeting.minutes.enabled: false`. At API import/startup,
the loader sets only that flag in the existing process FlagStore, before installing routes.
It preserves replay_only, claims_frozen and their histories. Missing/unreadable/malformed
configuration or a non-boolean value disables minutes, including with an environment override.
For valid configuration, `TILO_MEETING_MINUTES_ENABLED=1` enables, `0` disables; every other
present value disables. Routes and their OpenAPI entries are absent while off. Registered
routes still reread the shared flag for each request; changing the environment requires a new revision.

Only after all ACT-1..4 heads pass the supervisor's delta security review and A deploys that
exact reviewed API image, the user may run this one PowerShell command:

```powershell
gcloud run services update tilo-api --project=essential-wares-510320-f0 --region=asia-southeast1 --update-env-vars=TILO_MEETING_MINUTES_ENABLED=1
```

This writes only the flag environment value, preserving LIVE, model location, NAT and stores.
Cost is ordinary Cloud Run revision startup; later explicit minutes requests may incur provider
charges according to the existing LIVE/mode and budget gates. Verify a Ready revision in Cloud
Run, then test authenticated owner analyze-minutes and draft-followup requests. Other-owner,
demo, App Check, pause, source, retention, allowance, T3 and OB-01/OB-05 guards still apply.
This document grants no activation approval and does not claim ACT-1..4 are complete.

Rollback uses the same command with `TILO_MEETING_MINUTES_ENABLED=0`, then verify Ready.
Both routes return 404 and are absent from the new process's route table/OpenAPI. It does not
erase already-created records or disable other LIVE work; cleanup is ACT-1's responsibility.

Offline acceptance: `uv run pytest services/api/tests/test_FR_MTG_03_08_startup_flag.py -q`.
