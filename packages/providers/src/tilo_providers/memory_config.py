"""RT-05: strictly checked passage-index settings from config/memory.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

DEFAULT_PATH = Path(__file__).resolve().parents[4] / "config/memory.yaml"


class VectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dimensions: StrictInt = Field(ge=64, le=2048)
    k: StrictInt = Field(ge=1, le=20)
    max_distance: float | None
    chunk_chars: StrictInt = Field(ge=1, le=1200)
    per_source: StrictInt = Field(ge=1, le=200)
    per_person: StrictInt = Field(ge=1, le=2000)


class EmbedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    batch_max: StrictInt = Field(ge=1, le=64)


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    vector: VectorConfig
    embed: EmbedConfig


def load_memory_config(path: Path | str = DEFAULT_PATH) -> MemoryConfig:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return MemoryConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise ValueError(f"RT-05: invalid config/memory.yaml: {error}") from error
