"""tilo_providers: the model/search/safety/speech/render/hands provider layer
(PRD 6.4, 12.5). Business code never imports a model id directly — only
through this package, driven by `config/models.yaml` (PL-01). P0-04 shipped
interfaces/config/prompts; P0-05 ships the adapters, `fake`, `replay`,
`errors` and the role -> provider `factory`. P0-06: `router`, `conformance`.
CC-SP-47: `safety` (SafetyProvider fake, record-and-replay, factory).
"""
