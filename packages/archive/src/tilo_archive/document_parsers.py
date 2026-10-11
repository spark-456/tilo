"""I4 deterministic byte-only intake primitives; no execution, extraction or I/O.

ZIP expansion returns inert bytes, not trusted content. Callers must still perform
scope, provenance and safety screening before using any returned text or bytes.
"""

import io
import stat
import zipfile
import zlib
from dataclasses import dataclass, field


class Refused(ValueError):
    """Stable refusal code only: never include uploaded names or content."""


@dataclass(frozen=True)
class Limits:
    input_bytes: int = 4 * 1024 * 1024
    expanded_bytes: int = 16 * 1024 * 1024
    entries: int = 256
    nesting: int = 2
    path_depth: int = 16
    ratio: int = 100

    def validate(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (self.input_bytes, self.expanded_bytes, self.entries, self.path_depth, self.ratio)
        ):
            raise ValueError("invalid_limits")
        if type(self.nesting) is not int or self.nesting < 0:
            raise ValueError("invalid_limits")


@dataclass
class _Budget:
    expanded: int = 0
    entries: int = 0
    paths: set[str] = field(default_factory=set)


def _path(name: str, limits: Limits) -> None:
    parts = name.rstrip("/").split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or any(character in name for character in ("\\", ":", "\x00"))
        or any(ord(character) < 32 for character in name)
    ):
        raise Refused("unsafe_path")
    if len(parts) > limits.path_depth:
        raise Refused("path_depth")


def _expand(data: bytes, limits: Limits, budget: _Budget, depth: int, prefix: str) -> list[tuple[str, bytes]]:
    if depth > limits.nesting:
        raise Refused("nesting")
    output: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        infos = handle.infolist()
        budget.entries += len(infos)
        if budget.entries > limits.entries:
            raise Refused("entry_count")
        names: set[str] = set()
        for info in infos:
            # orig_filename retains NULs that ZipInfo.filename otherwise truncates.
            _path(info.orig_filename, limits)
            label = prefix + info.filename.rstrip("/")
            _path(label, limits)
            if label in names:
                raise Refused("duplicate_path")
            names.add(label)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise Refused("special_entry")
            if info.flag_bits & 1:
                raise Refused("encrypted_zip")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise Refused("compression_method")
            budget.expanded += info.file_size
            if budget.expanded > limits.expanded_bytes:
                raise Refused("expanded_size")
            if info.file_size > limits.ratio * max(1, info.compress_size):
                raise Refused("compression_ratio")
        for info in infos:
            if info.is_dir():
                continue
            with handle.open(info) as source:
                content = source.read(min(info.file_size, limits.expanded_bytes) + 1)
            if len(content) != info.file_size:
                raise Refused("invalid_zip")
            label = prefix + info.filename
            if content.startswith(b"PK"):
                output.extend(_expand(content, limits, budget, depth + 1, label + "/"))
            else:
                if label in budget.paths:
                    raise Refused("duplicate_path")
                budget.paths.add(label)
                output.append((label, content))
    return output


def expand_zip(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, bytes], ...]:
    """Expand nested ZIPs in stored order under shared byte/entry/depth budgets.

    No paths are written. Every level counts toward the decompression budget,
    including nested ZIP containers. Unsupported/encrypted/corrupt ZIPs fail closed.
    """
    limits.validate()
    if len(data) > limits.input_bytes:
        raise Refused("input_size")
    try:
        return tuple(_expand(data, limits, _Budget(), 0, ""))
    except Refused:
        raise
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, ValueError, zlib.error):
        raise Refused("invalid_zip") from None
