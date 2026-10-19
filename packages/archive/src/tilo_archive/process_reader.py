"""I4 resource-isolated reader. No route, credentials or safety verdict.

Memory is enforced before reading stdin; parent timeout kills and reaps the
worker. Uploaded content is parsed as data, never used as a command or filename.
"""

import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

from tilo_archive.document_parsers import DocumentRead, Limits, Refused, read_document

MAX_RESPONSE = 8 * 1024 * 1024
CODES = frozenset(
    """input_size expanded_size entry_count cell_count paragraph_count output_size unsafe_path
path_depth nesting duplicate_path special_entry encrypted_zip compression_method compression_ratio invalid_zip
xml_nodes xml_depth xml_attributes xml_part_size external_reference active_content xml_declaration invalid_xml
unknown_type invalid_spreadsheet invalid_presentation invalid_encoding invalid_csv parser_limits_unavailable
parser_memory expat_version""".split()
)


@dataclass(frozen=True)
class ProcessLimits:
    memory_bytes: int = 256 * 1024 * 1024
    wall_seconds: float = 10.0

    def validate(self) -> None:
        if (
            type(self.memory_bytes) is not int
            or not 64 * 1024 * 1024 <= self.memory_bytes <= 256 * 1024 * 1024
            or type(self.wall_seconds) not in (int, float)
            or not math.isfinite(self.wall_seconds)
            or not 0 < self.wall_seconds <= 10
        ):
            raise ValueError("invalid_process_limits")


def _limit_memory(size: int) -> Any:
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (size, size))
        return None
    if os.name != "nt":
        raise OSError("unsupported_memory_limit")
    import ctypes as c

    class Basic(c.Structure):
        _fields_ = [
            ("process_time", c.c_int64),
            ("job_time", c.c_int64),
            ("flags", c.c_uint32),
            ("min_working", c.c_size_t),
            ("max_working", c.c_size_t),
            ("active", c.c_uint32),
            ("affinity", c.c_size_t),
            ("priority", c.c_uint32),
            ("scheduling", c.c_uint32),
        ]

    class Extended(c.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", c.c_uint64 * 6),
            ("process_memory", c.c_size_t),
            ("job_memory", c.c_size_t),
            ("peak_process", c.c_size_t),
            ("peak_job", c.c_size_t),
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, c.c_wchar_p]
    kernel.CreateJobObjectW.restype = c.c_void_p
    kernel.SetInformationJobObject.argtypes = [c.c_void_p, c.c_int, c.c_void_p, c.c_uint32]
    kernel.SetInformationJobObject.restype = c.c_int
    kernel.GetCurrentProcess.restype = c.c_void_p
    kernel.AssignProcessToJobObject.argtypes = [c.c_void_p, c.c_void_p]
    kernel.AssignProcessToJobObject.restype = c.c_int
    kernel.CloseHandle.argtypes = [c.c_void_p]
    job = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY (committed bytes, not working set)
    info.process_memory = size
    if not job or not kernel.SetInformationJobObject(job, 9, c.byref(info), c.sizeof(info)):
        if job:
            kernel.CloseHandle(job)
        raise OSError("memory_limit_unavailable")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise OSError("memory_limit_unavailable")
    return job  # retained until child exits; no kill-on-close flag


def _command(kind: str, limits: Limits, process: ProcessLimits) -> list[str]:
    return [
        sys.executable,
        "-I",
        "-m",
        "tilo_archive.process_reader",
        str(process.memory_bytes),
        kind,
        json.dumps(asdict(limits)),
    ]


def read_isolated(
    data: bytes, *, kind: str, limits: Limits = Limits(), process: ProcessLimits = ProcessLimits()
) -> DocumentRead:
    limits.validate()
    process.validate()
    if len(data) > limits.input_bytes:
        raise Refused("input_size")
    if kind not in ("docx", "xlsx", "pptx", "csv"):
        raise Refused("unknown_type")
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
    code = "parser_failed"
    try:
        done = subprocess.run(
            _command(kind, limits, process),
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=process.wall_seconds,
            env=env,
            creationflags=0x08000000 if os.name == "nt" else 0,
            check=False,
        )
        if done.returncode == 0 and len(done.stdout) <= MAX_RESPONSE:
            payload = json.loads(done.stdout)
            if type(payload) is dict and payload.get("error") in CODES:
                code = payload["error"]
            elif type(payload) is dict and set(payload) == {"fragments", "read", "skipped"}:
                fragments, read, skipped = payload["fragments"], payload["read"], payload["skipped"]
                if (
                    type(fragments) is list
                    and all(
                        type(pair) is list and len(pair) == 2 and all(type(value) is str for value in pair)
                        for pair in fragments
                    )
                    and all(
                        type(values) is list and all(type(value) is str for value in values)
                        for values in (read, skipped)
                    )
                ):
                    return DocumentRead(tuple((pair[0], pair[1]) for pair in fragments), tuple(read), tuple(skipped))
    except subprocess.TimeoutExpired:
        code = "parser_timeout"  # subprocess.run kills and waits before raising
    except (OSError, ValueError, TypeError):
        pass
    raise Refused(code)


def _worker() -> int:
    try:
        process = ProcessLimits(memory_bytes=int(sys.argv[1]))
        process.validate()
        handle = _limit_memory(process.memory_bytes)
    except (OSError, ValueError):
        return 2  # fail closed before reading input; parent exposes only parser_failed
    try:
        import pyexpat

        if sys.argv[2] != "csv" and pyexpat.version_info < (2, 6, 0):
            raise Refused("expat_version")
        limits = Limits(**json.loads(sys.argv[3]))
        limits.validate()
        data = sys.stdin.buffer.read(limits.input_bytes + 1)
        result = read_document(data, kind=sys.argv[2], limits=limits)
        output = json.dumps(asdict(result)).encode()
        if len(output) > MAX_RESPONSE:
            raise Refused("output_size")
    except Refused as exc:
        output = json.dumps({"error": str(exc) if str(exc) in CODES else "unknown_type"}).encode()
    except MemoryError:
        output = b'{"error":"parser_memory"}'
    except (ValueError, TypeError, IndexError):
        return 2
    sys.stdout.buffer.write(output)
    _ = handle  # keep the Windows job handle alive through parsing/output
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker())
