import subprocess
import sys
from dataclasses import replace

import pytest


def test_I4_SEC_05_process_reader_returns_cited_text_and_coverage():
    from tilo_archive.process_reader import read_isolated

    result = read_isolated(b"a,b", kind="csv")
    assert result.fragments == (("csv#r1c1", "a"), ("csv#r1c2", "b"))
    assert "formula evaluation" in result.skipped


def test_I4_SEC_05_process_reader_enforces_custom_parser_limits():
    from tilo_archive.document_parsers import Limits, Refused
    from tilo_archive.process_reader import read_isolated

    with pytest.raises(Refused, match="^cell_count$"):
        read_isolated(b"a,b", kind="csv", limits=replace(Limits(), cells=1))


def test_I4_SEC_05_memory_limit_is_enforced_in_real_child():
    code = (
        "from tilo_archive.process_reader import _limit_memory; "
        "handle = _limit_memory(64 * 1024 * 1024); "
        "allocation = bytearray(128 * 1024 * 1024)"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, timeout=10)
    assert result.returncode != 0
    assert b"MemoryError" in result.stderr


def test_I4_SEC_05_real_worker_timeout_kills_and_reaps(monkeypatch):
    from tilo_archive import process_reader as reader
    from tilo_archive.document_parsers import Refused

    children = []
    original = subprocess.Popen

    def tracked(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(reader.subprocess, "Popen", tracked)
    monkeypatch.setattr(reader, "_command", lambda *args: [sys.executable, "-I", "-c", "import time; time.sleep(30)"])
    with pytest.raises(Refused, match="^parser_timeout$") as error:
        reader.read_isolated(b"a", kind="csv", process=reader.ProcessLimits(wall_seconds=0.1))
    assert error.value.__context__ is None
    assert len(children) == 1 and children[0].poll() is not None


def test_I4_SEC_05_worker_fails_closed_when_memory_limit_cannot_be_installed(monkeypatch):
    from tilo_archive import process_reader as reader

    def unavailable(*args):
        raise OSError("private runtime details")

    monkeypatch.setattr(reader, "_limit_memory", unavailable)
    monkeypatch.setattr(reader.sys, "argv", ["worker", str(256 * 1024 * 1024), "csv", "{}"])
    assert reader._worker() == 2  # must fail before reading the upload


@pytest.mark.parametrize("kind", ["docx", "xlsx", "pptx"])
def test_I4_FR_INT_02_real_worker_reads_office_citations(kind):
    from test_I4_output_limits import document, presentation
    from test_I4_xlsx_parser import xlsx
    from tilo_archive.process_reader import read_isolated

    data = {"docx": document(1), "xlsx": xlsx('<c r="A1"><v>x</v></c>'), "pptx": presentation(1)}[kind]
    assert read_isolated(data, kind=kind).fragments[0][1] == "x"


@pytest.mark.parametrize("version", [(2, 5, 0), (2, 6, 0)])
def test_I4_SEC_05_worker_checks_expat_before_reading_office(monkeypatch, version, capsys):
    import pyexpat

    from tilo_archive import process_reader as reader

    calls = []
    monkeypatch.setattr(reader, "_limit_memory", lambda *args: None)
    monkeypatch.setattr(reader.sys, "argv", ["worker", str(256 * 1024 * 1024), "docx", "{}"])
    monkeypatch.setattr(pyexpat, "version_info", version)

    class Input:
        def read(self, count):
            calls.append(count)
            return b"unreadable"

    monkeypatch.setattr(reader.sys, "stdin", type("Stdin", (), {"buffer": Input()})())
    assert reader._worker() == 0
    result = capsys.readouterr().out
    assert ("expat_version" in result) == (version < (2, 6, 0))
    assert bool(calls) == (version >= (2, 6, 0))


@pytest.mark.parametrize(
    "process",
    [
        {"memory_bytes": True},
        {"memory_bytes": 512 * 1024 * 1024},
        {"wall_seconds": float("nan")},
        {"wall_seconds": 0},
        {"wall_seconds": 11},
    ],
)
def test_I4_SEC_05_worker_process_limits_have_hard_ceilings(process):
    from tilo_archive.process_reader import ProcessLimits

    with pytest.raises(ValueError, match="^invalid_process_limits$"):
        ProcessLimits(**process).validate()


def test_I4_SEC_05_worker_does_not_inherit_credentials_or_echo_uploads(monkeypatch):
    from tilo_archive import process_reader as reader
    from tilo_archive.document_parsers import Refused

    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "private-credential-path")

    def completed(command, **kwargs):
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in kwargs["env"]
        assert "-I" in command
        assert kwargs["stderr"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(command, 1, b"private uploaded content")

    monkeypatch.setattr(reader.subprocess, "run", completed)
    with pytest.raises(Refused, match="^parser_failed$"):
        reader.read_isolated(b"private uploaded content", kind="csv")
