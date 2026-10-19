"""COST-AUDIT: compute the p90 output tokens per role from real model recordings (`python -m tilo_evals.live_usage_p90
evals/bank/live/<case>/model-recordings ... [--write]`). A recording folder marked SYNTHETIC (fake provider) is refused:
its usage is made up. `--write` rewrites `evals/live_usage_p90.json` with the roles it found and its provenance."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_FILE = Path(__file__).resolve().parents[2] / "live_usage_p90.json"


def p90(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def collect(folders: list[Path]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for folder in folders:
        if (folder.parent / "SYNTHETIC").exists():
            raise SystemExit(f"{folder}: written by a fake provider, its usage is not real")
        for path in folder.glob("*/*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            usage = (record.get("response") or {}).get("usage") or {}
            if isinstance(usage.get("output_tokens"), int):
                found.setdefault(str(record["role"]), []).append(usage["output_tokens"])
    return found


def main(argv: list[str]) -> int:
    write = "--write" in argv
    found = collect([Path(a) for a in argv if not a.startswith("--")])
    table = {role: p90(values) for role, values in sorted(found.items())}
    print(json.dumps({role: [len(found[role]), value] for role, value in table.items()}))
    if write and table:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        data["output_tokens_p90"] |= table
        data["provenance"] = (
            f"Measured p90 of output_tokens per role over {sum(map(len, found.values()))} recorded calls."
        )
        _FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
