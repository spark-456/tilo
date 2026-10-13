"""Getting synthesized speech into the meeting: a virtual microphone and a player that can be cut off mid-word.

PulseAudio layout (created at start when voice replies are on, before Chromium launches):
    paplay --device=tilo_mic_sink   ->  tilo_mic_sink (null sink)  ->  tilo_mic (source)  ->  Chromium/Meet "microphone"
Meet's own audio still goes to tilo_out (see the container entrypoint), which is what we transcribe.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from .hybrid import parec_command, wav_header

log = logging.getLogger("bot.audio_out")
MIC_SINK = "tilo_mic_sink"
MIC_SOURCE = "tilo_mic"


def setup_virtual_mic() -> bool:
    """Create the virtual microphone and make it the default input. Safe to call twice."""
    if not shutil.which("pactl"):
        log.warning("pactl not found: no virtual microphone")
        return False

    def pactl(*args: str) -> str:
        r = subprocess.run(["pactl", *args], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    if MIC_SOURCE not in pactl("list", "short", "sources"):
        pactl(
            "load-module", "module-null-sink", f"sink_name={MIC_SINK}", "sink_properties=device.description=TiloMicSink"
        )
        pactl(
            "load-module",
            "module-remap-source",
            f"master={MIC_SINK}.monitor",
            f"source_name={MIC_SOURCE}",
            "source_properties=device.description=Tilo",
        )
    pactl("set-default-source", MIC_SOURCE)
    ok = MIC_SOURCE in pactl("list", "short", "sources")
    log.info("virtual microphone %s", "ready" if ok else "could not be created")
    return ok


class Player:
    """Plays PCM chunks into the virtual microphone; `should_stop` is polled so a human can interrupt."""

    on_level: Callable[[float], None] | None = None

    async def play(self, chunks: AsyncIterator[bytes], rate: int, should_stop: Callable[[], bool]) -> bool:
        """True if everything was played, False if cut off."""
        proc = await asyncio.create_subprocess_exec(
            "paplay",
            "--raw",
            f"--rate={rate}",
            "--channels=1",
            "--format=s16le",
            f"--device={MIC_SINK}",
            "--latency-msec=60",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdin
        cut = False
        try:
            async for chunk in chunks:
                if should_stop():
                    cut = True
                    break
                proc.stdin.write(chunk)
                await proc.stdin.drain()
                if self.on_level and len(chunk) >= 2:
                    samples = memoryview(chunk[: len(chunk) // 2 * 2]).cast("h")[::32]
                    self.on_level((sum(float(x) ** 2 for x in samples) / len(samples)) ** 0.5 / 32768)
            proc.stdin.close()
            while not cut and proc.returncode is None:  # the tail is still playing: keep watching for interruptions
                if should_stop():
                    cut = True
                    break
                try:
                    await asyncio.wait_for(proc.wait(), timeout=0.05)
                except TimeoutError:
                    pass
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        return not cut


class WavTap:
    """What the bot actually sent into the meeting (the virtual mic's monitor) saved as bot.wav. It starts close to
    audio.wav, and `audio_clock.json` records both start times so `audit` can line the two up."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._f = None
        self._bytes = 0
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self.started_at = 0.0

    def command(self) -> list[str]:
        return parec_command(f"{MIC_SINK}.monitor")

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("wb")
        self._f.write(wav_header(0))

    def write(self, chunk: bytes) -> None:
        if self._f:
            self._f.write(chunk)
            self._bytes += len(chunk)

    def close(self) -> None:
        if self._f:
            self._f.seek(0)
            self._f.write(wav_header(self._bytes))
            self._f.close()
            self._f = None

    def start(self) -> bool:
        if not shutil.which("parec"):
            return False
        self.open()
        self._proc = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.started_at = time.monotonic()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self) -> None:
        assert self._proc and self._proc.stdout
        while chunk := self._proc.stdout.read(3200):
            self.write(chunk)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread:
            self._thread.join(timeout=3)
        self.close()
