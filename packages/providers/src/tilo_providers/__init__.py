"""tilo_providers: the model/search/safety/speech/render/hands provider layer
(PRD 6.4, 12.5).

Ticket P0-04 ships interfaces (`tilo_providers.interfaces`), the config
loader (`tilo_providers.config`) and the prompt template loader
(`tilo_providers.prompts`). Adapters (google, OpenAI-compatible,
record-and-replay) land in P0-05, the role-based router in P0-06. Business
code must never import a model id directly — only through this package,
driven by `config/models.yaml` (PL-01).
"""
