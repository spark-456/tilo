"""Offline image smoke: no Meet URL, account, provider call or persistent profile."""

import asyncio
import os
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
            label = await page.evaluate("""async () => {
              const stream = await navigator.mediaDevices.getUserMedia({audio: true});
              try { return stream.getAudioTracks()[0].label; }
              finally { stream.getTracks().forEach(track => track.stop()); }
            }""")
            assert "Tilo" in label, "Chromium did not select the virtual microphone"
            await context.close()
        finally:
            await browser.close()
    print("Guest image startup, auth refusal, virtual microphone and Chromium passed (offline)")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=45))
