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
from collections.abc import AsyncIterator, Callable

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
        return not cut
