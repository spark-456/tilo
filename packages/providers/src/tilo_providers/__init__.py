"""tilo_providers: the model/search/safety/speech/render/hands provider layer
(PRD 6.4, 12.5).

Ticket P0-04 ships interfaces (`tilo_providers.interfaces`), the config
loader (`tilo_providers.config`) and the prompt template loader
(`tilo_providers.prompts`). Ticket P0-05 ships the `google` adapter
(`tilo_providers.google_adapter`), the generic OpenAI-compatible adapter
(`tilo_providers.openai_compat_adapter`), the fake provider
(`tilo_providers.fake`), record-and-replay (`tilo_providers.replay`), the
error types every adapter maps onto (`tilo_providers.errors`) and the
role -> provider factory (`tilo_providers.factory`). The
capability/budget-aware router lands in P0-06. Business code must never
import a model id directly — only through this package, driven by
`config/models.yaml` (PL-01).
"""
