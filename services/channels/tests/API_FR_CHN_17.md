# FR-CHN-17 web push: API for the tilo-api wiring (not built here)

- `SubscriptionStore.add(user_id, body)`: `body` is the browser's `PushSubscription.toJSON()` (`endpoint`, `keys.p256dh`, `keys.auth`). Raises `SubscriptionRefused` (never echo the endpoint). `user_id` comes from the verified session, never the body.
- `PushNotifier.notify(user_id, {id, kind, title, body})` -> `PushResult(status, in_app, outbox_id)`. `kind` is `gate`, `blocked`, `spend`, `finished`, `digest`, `weekly`, `info`. Statuses: queued, duplicate, quiet, off, no_subscription, no_policy, refused. The card is shown in the app whatever the status.
- Wire `WebPushAdapter` into the world's `Outbox(connectors={"web_push": adapter})`; the real `PushSender` reads the secret named by `load_config().vapid` (`webpush-vapid-private-key`) and maps HTTP 404/410 to `SubscriptionGone`.
- Needs the owner's standing L3 policy for `send_push` on connector `web_push` (BQ-CHN17-1).
