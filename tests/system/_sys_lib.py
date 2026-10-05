"""Helpers for the whole-stack system tests (tests/system): real `uvicorn` processes, real sockets.

The service tests elsewhere call the apps in-process. These start each service the way its Dockerfile
does (`uvicorn <module>:app`) and talk to it over HTTP, so they also cover process start-up, the
middleware stack and the wire format. No paid call and no cloud: the dev API runs on the fake Director
and runner (`config/models.dev.yaml`, `TILO_API_DEV=1`), the others have no provider at all."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_API_PORT = 8080  # fixed by tilo_api.dev: its Host check only accepts the loopback address on this port
DEV_API_URL = f"http://localhost:{DEV_API_PORT}"
# Variables that would make a service refuse dev mode or go live: the system tests never inherit them.
_STRIPPED = ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV", "TILO_MODELS_FILE")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


class Server:
    """One `uvicorn <app>` child process, logging to a file (an undrained pipe stalls the child)."""

    def __init__(self, app: str, port: int, env: dict[str, str] | None = None) -> None:
        self.app, self.port = app, port
        self.url = f"http://127.0.0.1:{port}"
        self._env = {k: v for k, v in os.environ.items() if k not in _STRIPPED} | (env or {})
        self._log = tempfile.NamedTemporaryFile(prefix="tilo-system-", suffix=".log", delete=False)
        self._proc: subprocess.Popen[bytes] | None = None

    def log_tail(self, chars: int = 1500) -> str:
        return Path(self._log.name).read_text(encoding="utf-8", errors="replace")[-chars:]

    def start(self, ready_path: str = "/openapi.json", timeout: float = 60.0) -> Server:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", self.app, "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=REPO_ROOT,
            env=self._env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"{self.app} exited with {self._proc.returncode}:\n{self.log_tail()}")
            try:
                host = {"Host": f"localhost:{self.port}"} if self.port == DEV_API_PORT else {}
                if httpx.get(self.url + ready_path, headers=host, timeout=2).status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.25)
        self.stop()
        raise RuntimeError(f"{self.app} was not ready after {timeout}s:\n{self.log_tail()}")

    def stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._log.close()
        try:
            Path(self._log.name).unlink(missing_ok=True)
        except OSError:  # Windows keeps the file locked a moment after the child exits; the temp dir is cleaned later
            pass


def dev_api_env() -> dict[str, str]:
    return {
        "TILO_API_DEV": "1",
        "TILO_MODELS_FILE": str(REPO_ROOT / "config" / "models.dev.yaml"),  # a deterministic fake Director
        "TILO_DEV_UNIT_DELAY_S": "0.3",
    }


def wait_for(read, what: str, timeout: float = 30.0, every: float = 0.1):
    """Polls `read` until it returns something truthy; a recorded fact, never a fixed sleep."""
    deadline = time.monotonic() + timeout
    while not (value := read()):
        assert time.monotonic() < deadline, f"timed out after {timeout}s waiting for {what}"
        time.sleep(every)
    return value


def start_run(client: httpx.Client, text: str = "Prepare the weekly supplier summary.") -> tuple[str, str]:
    """Request -> clarifying questions -> approach and budget; returns (task_id, world_id)."""
    intake = client.post("/intake", data={"text": text})
    assert intake.status_code == 201, intake.text
    task = intake.json()
    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]
    assert (
        client.post(f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}}).status_code
        == 200
    )
    approaches = client.get(f"/tasks/{task['task_id']}/approaches").json()
    approve = client.post(
        f"/tasks/{task['task_id']}/approve",
        json={"approach_id": approaches["recommended"], "budget_cap": 50},
    )
    assert approve.status_code == 200, approve.text
    return task["task_id"], approve.json()["world_id"]


def event_types(client: httpx.Client, world_id: str) -> list[str]:
    return [e["type"] for e in client.get(f"/worlds/{world_id}/events").json()["events"]]


def gate_card(client: httpx.Client, world_id: str) -> dict:
    def read():
        cards = [c for c in client.get(f"/worlds/{world_id}/cards").json() if c["kind"] == "gate"]
        return cards[0] if cards else None

    return wait_for(read, "the approval card")
