"""Offline image smoke: no Meet URL, account, provider call or persistent profile."""

import asyncio
import math
import os
import struct
import urllib.error
import urllib.request

from playwright.async_api import async_playwright

from bot.audio_out import Player, setup_virtual_mic


async def main():
    assert os.environ.get("LIVE") != "1"
    assert urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3).status == 200
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                "http://127.0.0.1:8080/internal/meetings/mt_smoke/attend",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            ),
            timeout=3,
        )
    except urllib.error.HTTPError as error:
        assert error.code == 503
    else:
        raise AssertionError("Unconfigured attendance launched")
    assert setup_virtual_mic(), "Virtual microphone unavailable"

    async def silence():
        yield bytes(960)  # 20ms synthetic silence, no microphone recording

    assert await Player().play(silence(), 24000, lambda: False)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False, args=["--no-sandbox"])
        try:
            context = await browser.new_context(permissions=["microphone"])
            page = await context.new_page()
            await page.goto("about:blank")
            assert await page.evaluate("1 + 1") == 2
            await page.goto("http://127.0.0.1:8080/health")
            await page.evaluate("""async () => {
              const stream = await navigator.mediaDevices.getUserMedia({audio: {
                echoCancellation: false, noiseSuppression: false, autoGainControl: false
              }});
              const audio = new AudioContext();
              await audio.resume();
              const source = audio.createMediaStreamSource(stream);
              const analyser = audio.createAnalyser();
              analyser.fftSize = 2048;
              source.connect(analyser);
              window.smokeAudio = {stream, audio, analyser};
            }""")

            async def tone():
                # A synthetic 880Hz tone proves the actual input route, independent of device labels.
                block = b"".join(
                    struct.pack("<h", int(8000 * math.sin(2 * math.pi * 880 * n / 24000))) for n in range(24000)
                )
                yield block

            async def receive():
                return await page.evaluate("""async () => {
                  const {stream, audio, analyser} = window.smokeAudio;
                  let peak = 0;
                  const samples = new Float32Array(analyser.fftSize);
                  try {
                    for (let i = 0; i < 80; i++) {
                      analyser.getFloatTimeDomainData(samples);
                      const rms = Math.sqrt(samples.reduce((sum, x) => sum + x*x, 0) / samples.length);
                      peak = Math.max(peak, rms);
                      await new Promise(resolve => setTimeout(resolve, 25));
                    }
                    return peak;
                  } finally {
                    stream.getTracks().forEach(track => track.stop());
                    await audio.close();
                    delete window.smokeAudio;
                  }
                }""")

            played, level = await asyncio.gather(Player().play(tone(), 24000, lambda: False), receive())
            assert played and level > 0.02, "Chromium did not receive the synthetic virtual-microphone tone"
            await context.close()
        finally:
            await browser.close()
    print("Guest image startup, auth refusal, virtual microphone and Chromium passed (offline)")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=45))
