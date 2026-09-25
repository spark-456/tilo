---
name: metering-loader-attack-patterns
description: Attacks that found bugs in packages/metering loaders (PriceBook, MeteringConfig) across P8-01a review rounds
metadata:
  type: project
---

Generated tilo_contracts models drop JSON-schema `const` and `if/then` (e.g. prices credit_usd const 0.005, set-file non-null date/source), so loaders must re-check them by hand. Pydantic lax mode also accepts strings ("0.005", "1.0") the schema rejects.

Round 3 (2026-09-25): the schema checks were fixed, but malformed YAML still escapes as yaml.ParserError from both loaders, and a missing prices file raises FileNotFoundError, not MeteringConfigError.

Round 4: read_yaml catches OSError and YAMLError, but a non-UTF-8 file raises UnicodeDecodeError (a ValueError). PriceBook happened to wrap it; MeteringConfig.load did not. Also still open: .inf prices and caps, lax bools and strings in MeteringConfig, and a truthy "false" string in InMemoryFlagStore.

Round 5 (b7408f5): loader wrapping and the shared number() check held against every input class. Left open (non-blocking): the token cap alone cannot stop credits() overflowing, because a price near float max (1.0e+308) still makes credits() return inf. The loaders also accept a Feb 31 effective_date (the pattern-only calendar_date), YAML 1.1 hex and sexagesimal ints (0x10, 1:30=90), and MeteringConfig.reconciliation.billing_services is a mutable list inside a frozen model.

**Why:** builders fix only the exact repro. Each round left a sibling input class open.
**How to apply:** for any config loader, try missing file, directory, non-UTF-8 bytes, malformed YAML, empty, list-root, const violations, string-typed numbers, NaN/inf, unquoted YAML dates, duplicate versions and mutation of the returned object. Related: [[eval-harness-recording-validation]].
