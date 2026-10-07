"""Live Vertex AI schema probe (PL-02): the exact Director brief request (from the real builder, with a short synthetic
task) and its one-field-removed variants, then the older tiny Director-profile variants; needs the live switch
(`just vertex-probe-schema`; `--dry-run` prints the plan and sends nothing)."""

from tilo_planning.brief import brief_request, output_schema
from tilo_providers.schema_probe import main

PROBE_TOPIC = "Plan a two-day offsite for a team of twelve, with an agenda and a budget sheet."  # synthetic

raise SystemExit(main(schema=output_schema(), director=brief_request(PROBE_TOPIC)))
