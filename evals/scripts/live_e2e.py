"""`just live-e2e`: one bank case through the real pipeline, live only with the user's own LIVE=1 (issue #340).

Thin entry point; everything is in `tilo_evals.live_e2e`. `--help` and `--replay` need no live switch."""

from tilo_evals.live_e2e import main

if __name__ == "__main__":
    raise SystemExit(main())
