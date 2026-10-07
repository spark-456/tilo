"""`just live-run --topic "<any request>"`: one real end-to-end run on a typed topic, live only with the user's own
live switch (PL-LIVE-E2E, issue #340). Thin entry point; everything is in `tilo_evals.live_topic`."""

from tilo_evals.live_topic import main

if __name__ == "__main__":
    raise SystemExit(main())
