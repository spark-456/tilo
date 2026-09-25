"""tilo_providers: the model/search/safety/speech/render/hands provider layer
(PRD 6.4, 12.5). Business code never imports a model id directly — only
through this package, driven by `config/models.yaml` (PL-01), and never
names a model or profile: it asks `router.Router` for a role. P0-04 shipped
interfaces/config/prompts; P0-05 shipped the adapters, `fake`, `replay`,
`errors` and the role -> provider `factory`; P0-06 ships `router` (PL-03,
EFF-02, EFF-03) and `conformance` (PL-05).
"""
