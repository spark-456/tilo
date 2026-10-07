"""Live Vertex AI schema probe (PL-02): one tiny Director-profile call per request variant; needs the live switch
(`just vertex-probe-schema`; `--dry-run` prints the plan and sends nothing)."""

from tilo_planning.brief import output_schema
from tilo_providers.schema_probe import main

raise SystemExit(main(schema=output_schema()))
