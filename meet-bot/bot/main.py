"""Small CLI. Same commands on the host and inside the container.

On the host (stdlib only) `login`, `start` and `join` re-run themselves inside the Docker container.
Inside the container (TILO_IN_CONTAINER=1) they do the real work with Playwright.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import IN_CONTAINER, ROOT, Config, load_dotenv, setup_logging

IMAGE = "tilo-meet-bot:latest"
CONTAINER = "tilo-meet-bot"
NOVNC_URL = "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
GOOGLE_SESSION_COOKIES = ("SID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID")


# ---------------------------------------------------------------------------------------------------------------
# Host side: Docker orchestration
# ---------------------------------------------------------------------------------------------------------------
def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, **kw)


def _docker_ok() -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "Docker is not installed or not on PATH. Install Docker Desktop (WSL2 backend on Windows)."
    r = _run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True)
    if r.returncode != 0:
        return False, "Docker is installed but not running. Start Docker Desktop and wait until it says running."
    return True, f"Docker {r.stdout.strip()} is running"


def _image_exists() -> bool:
    return _run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


def _compose_run(args: list[str]) -> int:
    ok, msg = _docker_ok()
    if not ok:
        print(msg)
        return 1
    if not _image_exists():
        print("Building the image (first run only, a few minutes)...", flush=True)
        if _run(["docker", "compose", "build"]).returncode != 0:
            return 1
    _run(["docker", "rm", "-f", CONTAINER], capture_output=True)  # stale container from a crashed run
    cmd = ["docker", "compose", "run", "--rm", "--service-ports", "--name", CONTAINER]
    if not sys.stdin.isatty():
        cmd.append("-T")
    cmd += ["bot", "python", "-m", "bot.main", *args]
    try:
        return _run(cmd).returncode
    except KeyboardInterrupt:
        _run(["docker", "stop", "-t", "20", CONTAINER], capture_output=True)  # lets the bot leave cleanly
        return 130


def cmd_doctor(args: argparse.Namespace) -> int:
    load_dotenv()
    problems = 0

    def line(ok: bool | None, text: str) -> None:
        nonlocal problems
        print(("[ok]   " if ok else "[warn] " if ok is None else "[FAIL] ") + text)
        problems += ok is False

    docker_ok, msg = _docker_ok()
    line(docker_ok, msg)
    env = ROOT / ".env"
    line(env.is_file(), ".env found" if env.is_file() else ".env missing: copy .env.example to .env")
    line(
        True if os.environ.get("BOT_GOOGLE_EMAIL") else None,
        f"BOT_GOOGLE_EMAIL = {os.environ.get('BOT_GOOGLE_EMAIL') or '(unset)'}",
    )
    live = os.environ.get("LIVE") == "1"
    line(
        True,
        "models and speech: live providers (the user set the live switch)"
        if live
        else "models and speech: fake providers (offline; the live switch is not set)",
    )
    agenda = ROOT / os.environ.get("AGENDA_PATH", "agenda.md")
    line(
        True if agenda.is_file() else None,
        f"{agenda.name} "
        + ("found" if agenda.is_file() else "missing (copy agenda.example.md to agenda.md for the brain)"),
    )
    if sys.platform == "win32":
        wsl = Path.home() / ".wslconfig"
        line(
            True if wsl.is_file() else None,
            ".wslconfig found (WSL2 memory cap in place)"
            if wsl.is_file()
            else "no ~/.wslconfig: WSL2 may take most of your RAM. See README 'Capping WSL2 memory'.",
        )
    if docker_ok:
        has_image = _image_exists()
        line(True if has_image else None, "image built" if has_image else "image not built yet (`login` builds it)")
        if has_image:
            r = _run(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "bot",
                    "python",
                    "-m",
                    "bot.main",
                    "_check-login",
                ],
                capture_output=True,
            )
            out = (r.stdout or "").strip().splitlines()
            line(r.returncode == 0, out[-1] if out else "could not check the login state")
        running = _run(
            ["docker", "ps", "--filter", f"name={CONTAINER}", "--format", "{{.Names}}"], capture_output=True
        ).stdout.strip()
        if running:
            _print_stats()
            while args.watch:
                time.sleep(5)
                _print_stats()
        elif args.watch:
            line(None, "no bot container running, nothing to watch")
    print("\nAll good." if not problems else f"\n{problems} problem(s) to fix.")
    return 1 if problems else 0


def _print_stats() -> None:
    r = _run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.Name}}  CPU {{.CPUPerc}}  RAM {{.MemUsage}} ({{.MemPerc}})",
            CONTAINER,
        ],
        capture_output=True,
    )
    print("[stat] " + (r.stdout.strip() or "container not running"), flush=True)


# ---------------------------------------------------------------------------------------------------------------
# Container side
# ---------------------------------------------------------------------------------------------------------------
def _cookie_db(profile: Path) -> Path | None:
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        if (profile / rel).is_file():
            return profile / rel
    return None


def is_logged_in(profile: Path) -> bool:
    db = _cookie_db(profile)
    if db is None:
        return False
    with tempfile.TemporaryDirectory() as tmp:  # copy: Chromium may hold the live file open
        for suffix in ("", "-wal", "-journal"):
            src = Path(str(db) + suffix)
            if src.is_file():
                shutil.copy(src, Path(tmp) / (db.name + suffix))
        try:
            con = sqlite3.connect(str(Path(tmp) / db.name))
            marks = ",".join("?" * len(GOOGLE_SESSION_COOKIES))
            row = con.execute(
                f"SELECT 1 FROM cookies WHERE host_key LIKE '%google.com' AND name IN ({marks}) LIMIT 1",
                GOOGLE_SESSION_COOKIES,
            ).fetchone()
            con.close()
            return row is not None
        except sqlite3.Error:
            return False


def cmd_check_login(_: argparse.Namespace) -> int:
    cfg = Config.from_env()
    if is_logged_in(cfg.profile_dir):
        print(f"profile is signed in to Google (expected account: {cfg.bot_email or 'unset'})")
        return 0
    print("profile is NOT signed in: run `login` and sign in through noVNC")
    return 1


def cmd_login(_: argparse.Namespace) -> int:
    if not IN_CONTAINER:
        print(
            "Starting the browser container. When you see 'READY', open this in your own browser:\n"
            f"  {NOVNC_URL}\n"
            "Then sign in as the bot account by typing its password yourself (expect a verification prompt).\n"
            "Close the Chromium window or press Ctrl+C here when you are done.\n",
            flush=True,
        )
        return _compose_run(["login"])
    cfg = Config.from_env()
    from playwright.sync_api import sync_playwright

    from .browser import clean_singleton_locks

    with sync_playwright() as p:
        exe = p.chromium.executable_path
    cfg.profile_dir.mkdir(parents=True, exist_ok=True)
    clean_singleton_locks(cfg.profile_dir)
    # Plain Chromium (no automation, no DevTools port): Google is much less likely to refuse sign-in.
    proc = subprocess.Popen(
        [
            exe,
            f"--user-data-dir={cfg.profile_dir}",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--lang=en-US",
            "--start-maximized",
            "https://accounts.google.com/",
        ]
    )
    print(f"READY: open {NOVNC_URL}\nSign in as {cfg.bot_email or 'the bot account'}. Waiting...", flush=True)
    signed = False
    try:
        while proc.poll() is None:
            time.sleep(3)
            if not signed and is_logged_in(cfg.profile_dir):
                signed = True
                print(
                    "Signed in detected. Give it a few seconds, then close the Chromium window "
                    "(or Ctrl+C) so the login is saved.",
                    flush=True,
                )
    except KeyboardInterrupt:
        proc.terminate()
    time.sleep(2)
    print("Login saved." if is_logged_in(cfg.profile_dir) else "No Google login found in the profile.")
    return 0 if is_logged_in(cfg.profile_dir) else 1


def _live(mode: str, args: argparse.Namespace) -> int:
    if not IN_CONTAINER:
        if args.api_create:
            print(
                "--api-create is not implemented: it needs a Google Cloud project and OAuth consent. See DECISIONS.md."
            )
            return 2
        forward = [mode] + ([args.url] if mode == "join" else [])
        if args.agenda:
            forward += ["--agenda", args.agenda]
        if args.duration:
            forward += ["--duration", str(args.duration)]
        if args.auto_admit:
            forward.append("--auto-admit")
        if args.record_audio:
            forward.append("--record-audio")
        if args.reply:
            forward += ["--reply", args.reply]
        if args.stt:
            forward += ["--stt", args.stt]
        elif args.hybrid:
            forward.append("--hybrid")
        for route in args.context or []:
            forward += ["--context", route]
        if args.require:
            forward += ["--require", args.require]
        return _compose_run(forward)
    from .browser import JoinFailed, NotLoggedIn
    from .session import run_live

    cfg = Config.from_env()
    agenda = Path(args.agenda) if args.agenda else None
    if agenda and not agenda.is_absolute():
        agenda = ROOT / agenda
    task_holder: dict = {}

    async def runner() -> None:
        task_holder["t"] = asyncio.current_task()
        require = [n.strip() for n in (args.require or "").split(",") if n.strip()]
        await run_live(
            cfg,
            mode,
            getattr(args, "url", None),
            agenda,
            args.duration,
            auto_admit=args.auto_admit,
            require=require,
            record_audio=args.record_audio,
            hybrid=args.hybrid,
            context=args.context or [],
            stt=args.stt,
            reply=args.reply,
        )

    loop = asyncio.new_event_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: task_holder["t"].cancel())
    except (NotImplementedError, KeyError):
        pass
    try:
        loop.run_until_complete(runner())
        return 0
    except asyncio.CancelledError:
        print("Stopped; left the meeting.")
        return 0
    except NotLoggedIn as e:
        print(f"ERROR: {e}")
        return 3
    except JoinFailed as e:
        print(f"ERROR: could not join: {e}. Screenshots are in ./debug/")
        return 4
    finally:
        loop.close()


def cmd_run_mock(args: argparse.Namespace) -> int:
    from .brain import LLM, Agenda
    from .mock import load_transcript, run_mock
    from .mock_llm import KeywordStubLLM

    cfg = Config.from_env()
    agenda = Agenda.load(Path(args.agenda))
    duration = agenda.resolve_duration(args.duration)
    llm: LLM = KeywordStubLLM()
    if args.live_llm:
        from .providers import ProviderLLM

        llm = ProviderLLM()
    out = cfg.out_dir / ("mock-" + time.strftime("%Y%m%d-%H%M%S"))
    res = run_mock(
        agenda, load_transcript(Path(args.transcript)), llm, duration, cfg.brain_interval_s, cfg.window_minutes, out
    )
    print(res.brain.summary_markdown())
    print(f"{res.steps} brain steps, {len(res.messages)} chat message(s). Files in {out}")
    return 0


def cmd_retranscribe(args: argparse.Namespace) -> int:
    if not IN_CONTAINER:
        return _compose_run(["retranscribe"] + ([args.run] if args.run else []))
    from .brain import LLMUnavailable
    from .providers import ProviderSpeech
    from .retranscribe import retranscribe

    cfg = Config.from_env()
    runs = sorted(p for p in cfg.out_dir.glob("2*") if p.is_dir())
    run = Path(args.run) if args.run else (runs[-1] if runs else None)
    if run is None:
        print("no run folder under out/")
        return 1
    try:
        print(f"wrote {retranscribe(run, ProviderSpeech().segments)}")
        return 0
    except (LLMUnavailable, FileNotFoundError) as e:
        print(e)
        return 1


def cmd_playback(args: argparse.Namespace) -> int:
    from .playback import write_playback

    out = ROOT / "out"
    runs = sorted(p for p in out.glob("2*") if p.is_dir()) if out.is_dir() else []
    run = Path(args.run) if args.run else (runs[-1] if runs else None)
    if run is None or not run.is_dir():
        print("no run folder found under out/")
        return 1
    page = write_playback(run)
    print(f"wrote {page}" if page else f"no transcript in {run}")
    return 0 if page else 1


def _latest_run(arg: str | None) -> Path | None:
    out = ROOT / "out"
    runs = sorted(p for p in out.glob("2*") if p.is_dir()) if out.is_dir() else []
    run = Path(arg) if arg else (runs[-1] if runs else None)
    return run if run is not None and run.is_dir() else None


def cmd_report(args: argparse.Namespace) -> int:
    from .report import render_report

    run = _latest_run(args.run)
    if run is None:
        print("no run folder found (give the path of a folder under out/)")
        return 1
    print(render_report(run))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .report import audit, render_audit

    run = _latest_run(args.run)
    if run is None:
        print("no run folder found (give the path of a folder under out/)")
        return 1
    print(render_audit(audit(run)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bot", description="Google Meet note-taking bot (prototype)")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="check Docker, .env, login state, resources")
    d.add_argument("--watch", action="store_true", help="keep printing container CPU/RAM")
    sub.add_parser("login", help="open the container browser for the one-time manual sign-in")
    for name, helptext in (("start", "create a meeting as host and join it"), ("join", "join an existing meeting")):
        s = sub.add_parser(name, help=helptext)
        if name == "join":
            s.add_argument("url")
        s.add_argument("--agenda", help="agenda file (default agenda.md)")
        s.add_argument("--duration", type=float, help="planned meeting length in minutes")
        s.add_argument("--api-create", action="store_true", help="(not implemented) create via Meet REST API")
        s.add_argument(
            "--reply",
            choices=["chat", "voice", "both"],
            help="how answers go out: chat only, voice (chat only as backup), or both (default)",
        )
        s.add_argument(
            "--stt",
            choices=["captions", "gemini"],
            help="transcript source: captions (default) or gemini (audio, batch, through the speech provider)",
        )
        s.add_argument(
            "--hybrid",
            action="store_true",
            help="accurate transcript: the speech provider transcribes the audio, captions supply speaker names",
        )
        s.add_argument(
            "--context",
            action="append",
            help="extra project knowledge: a file, folder or https URL (repeatable; context/ is always loaded)",
        )
        s.add_argument(
            "--record-audio",
            action="store_true",
            help="record the meeting audio to out/<run>/audio.wav (local only) and build playback.html",
        )
        s.add_argument(
            "--auto-admit",
            action="store_true",
            help="admit people from the waiting room (limit with ADMIT_ALLOWED_NAMES in .env)",
        )
        s.add_argument("--require", help="comma-separated names that must be present before the bot speaks/starts")
    m = sub.add_parser("run-mock", help="replay a recorded transcript through the brain (no browser, no key needed)")
    m.add_argument("--agenda", default=str(ROOT / "agenda.example.md"))
    m.add_argument("--transcript", default=str(ROOT / "tests/fixtures/mock_meeting.jsonl"))
    m.add_argument("--duration", type=float)
    m.add_argument(
        "--live-llm",
        action="store_true",
        help="use the provider layer's model (real only if the user set the live switch)",
    )
    rt = sub.add_parser(
        "retranscribe", help="transcribe a run's recorded audio with the speech provider (needs --record-audio run)"
    )
    rt.add_argument("run", nargs="?")
    pb = sub.add_parser("playback", help="rebuild playback.html for a run (default: the latest)")
    pb.add_argument("run", nargs="?")
    rp = sub.add_parser("report", help="per-turn latency waterfall and p50/p90 for a run (default: the latest)")
    rp.add_argument("run", nargs="?")
    au = sub.add_parser("audit", help="measure end of question -> first bot sound from the recordings (needs bot.wav)")
    au.add_argument("run", nargs="?")
    sub.add_parser("_check-login")
    return p


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    handlers = {
        "doctor": cmd_doctor,
        "login": cmd_login,
        "run-mock": cmd_run_mock,
        "_check-login": cmd_check_login,
        "playback": cmd_playback,
        "report": cmd_report,
        "audit": cmd_audit,
        "retranscribe": cmd_retranscribe,
        "start": lambda a: _live("start", a),
        "join": lambda a: _live("join", a),
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
