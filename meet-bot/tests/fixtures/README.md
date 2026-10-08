# Caption fixtures

These are SYNTHETIC snapshots written from what is publicly known about Meet's captions region
(role="region", aria-label="Captions", one block per speaker: avatar, name, then text). They were not captured from
a live meeting, because none could be run while building. Class names are decoration and are ignored by the parser.

To replace them with real ones: set SAVE_CAPTION_SNAPSHOTS=1 in .env, run a short live meeting, and copy files from
debug/caption_snapshots/ here. Then extend tests/test_captions.py with the real speaker names and text.

`real_*.html` ARE real snapshots captured from a live Meet on 2026-09-29 (avatar URL removed, speaker renamed).
They show the actual structure: region role="region" aria-label="Captions" > block > (avatar img + name span) + text div,
plus a hidden "Jump to bottom" button that the parser must ignore. Captions revise themselves ("what is on the?" ->
"what is on the agenda?") and mishear words ("agenda" -> "accent"), so the tests treat them as noisy input.
