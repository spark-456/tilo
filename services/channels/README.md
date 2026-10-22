# tilo-channels

How Tilo reaches a person outside the web app: web push, email digests, signed approval links, Email Autopilot,
reschedule replies and nudges. Most of this package is **library code** that `tilo-api` imports; the deployed service
itself has one working route.

## The deployed service

`uvicorn tilo_channels.app:app` on `$PORT`.

| Route | Purpose |
| --- | --- |
| `GET /health`, `/healthz` | liveness |
| `POST /internal/push/send` | send a Web Push notice. Needs a Google ID token for audience `TILO_PUSH_AUDIENCE` from the account `TILO_PUSH_CALLER`, which is `tilo-api` |

The real sender exists only on Cloud Run with the VAPID private key mounted (secret `webpush-vapid-private-key`, env
`WEBPUSH_VAPID_PRIVATE_KEY`) and `TILO_WEBPUSH_VAPID_SUBJECT` set; anywhere else it is a fake, and the route answers 503.

No webhook route is mounted: `GmailPushEndpoint` in `gmail_watch.py` is a class only, and Terraform's Gmail topic, push
subscription and two Scheduler jobs point at `/internal/gmail/*` routes that do not exist yet (`infra/ACCESS.md`).

## The library

| Module | What it does |
| --- | --- |
| `web_push.py`, `web_push_sender.py`, `push_routes.py` | subscription store, notice kinds (gate, blocked, spend, finished, digest, weekly), VAPID sender |
| `links.py` | HMAC-SHA256 signed links: key ring, 24 h lifetime, single-use nonce, actions `open` and `answer`. The `/l/{token}` routes that redeem them live in `tilo-api` (`plate_links.py`) |
| `digest.py`, `plate_digest.py` | daily emails to the person's own mailbox, sent through the outbox `send_email` action |
| `autopilot*.py`, `triage.py`, `drafting.py`, `drafting_check.py` | Email Autopilot. L1: the owner presses Send, Edit or Cancel. L2: only a clean, ready T2 draft the owner asked for, with a 60 s undo window. Any modifier makes it T3, and T3 is never scheduled |
| `meeting_followup.py`, `reschedule_intent.py`, `reschedule_reply.py` | follow-up drafts after a meeting and replies to "can we move it" |
| `nudges.py`, `quiet_hours.py` | due-today and overdue nudges and the quiet-hours rules |

The package holds no Firestore, bucket or KMS code. Stores are injected ports that `tilo-api` implements (for example
`push_firestore.py`), and mail goes through the outbox to the Gmail adapter in `tilo-connectors`; there is no SMTP code.
WhatsApp is out of scope (ADR-0019): Terraform still declares its secret slots, but no code reads them.

## Config

`config/web_push.yaml`, `mail_trust.yaml`, `move_request.yaml`, `personal.yaml`, `reschedule_reply.yaml`.

## Tests

```sh
uv run --package tilo-channels pytest services/channels
```

See [CLAUDE.md](CLAUDE.md) for the requirement IDs and local rules.
