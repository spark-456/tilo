"""Live Vertex AI smoke (PL-02): one capped call per role; needs the live switch (`just vertex-smoke`)."""

from tilo_providers.vertex_smoke import main

raise SystemExit(main())
