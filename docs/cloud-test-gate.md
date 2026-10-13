# Test-only Cloud Build merge gate

The user approved this gate on 12 Oct with INR500 maximum spend and STOP/QUESTION
at INR400. On 13 Oct at 21:56 IST, the user lifted that stop to a total INR500
cap, including reservations; the supervisor sanctioned the guard update at 22:09.
It runs the repository suite and the full web Vitest suite in parallel,
plus TypeScript. Per-PR affected tests and touched-file lint/type checks stay local
(14:10 ruling). Browser acceptance and emulator tests keep the laptop heavy lock.
The gate never deploys. Deployment waits for a SUCCESS result on the group ref.

Run `just gate-cloud <local-ref>`. The recipe validates the ref before invoking
the runner. Project `essential-wares-510320-f0`, `asia-southeast1`, the existing
regional staging bucket and `tilo-cloudbuild` identity are pinned. There is no
infra apply, credential upload, live model call or new service account.

Source is a filtered Git archive of the resolved commit, not the working tree.
The separate test archive includes tracked web/repo inputs; deployment's
`.gcloudignore` is unchanged. Secret/state patterns, local dependencies and Git
metadata are excluded. Cloud checks initialize local Git metadata for the same
tracked-file checks. Only package/tool installation needs external downloads.

`agy-bridge/reports/CLOUD-GATE-SPEND.json` and `.md` in the primary checkout record
every reservation and completed run, ref, machine, minutes, estimated INR and log
URL. An exclusive ledger lock prevents competing reservations. An unknown result
keeps its full reservation; never refund it without checking the actual build.

E2_HIGHCPU_8 is USD0.0156 per minute in the published base table. The ledger uses
INR3.2/min, conservatively doubling that rate at INR100/USD for regional/overhead
uncertainty. A 30-minute timeout reserves 32 minutes (INR102.40). The current guard
refuses a run when existing spend/reservations are >= INR500 or adding the new
reservation would reach or exceed INR500. A projected INR500.01 is refused before
any cloud command; even exactly INR500 is refused by the strict stop boundary.
The user cap remains INR500 total, including reservations; the earlier INR400
stop above is historical. Sources: [pricing](https://cloud.google.com/build/pricing)
and [supported machine configuration](https://docs.cloud.google.com/build/docs/optimize-builds/increase-vcpu-for-builds).

Local gates remain the fallback; they do not authorize deployment after a red
cloud result. Fix forward or revert the affected group, preserving assertions.
