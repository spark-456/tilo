"""Container entrypoint: start the 'spare laptop' (screen, audio, VNC), then exec the requested command.

Python rather than a shell script so line-ending problems on Windows checkouts cannot break it.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

SCREEN = os.environ.get("SCREEN_GEOMETRY", "1280x720x24")
VNC_FPS_DELAY_MS = os.environ.get("VNC_DEFER_MS", "150")  # higher = fewer screen updates = less CPU


def wait_for(path: str, seconds: float = 15) -> None:
    end = time.time() + seconds
    while time.time() < end:
        if Path(path).exists():
            return
        time.sleep(0.2)
    sys.exit(f"entrypoint: {path} did not appear; the display server failed to start")


def spawn(cmd: list[str], log: str) -> None:
    subprocess.Popen(cmd, stdout=open(f"/tmp/{log}.log", "w"), stderr=subprocess.STDOUT)


def main() -> None:
    runtime = "/tmp/runtime-pwuser"
    os.makedirs(runtime, mode=0o700, exist_ok=True)
    os.environ.update(XDG_RUNTIME_DIR=runtime, DISPLAY=":99", PULSE_SERVER=f"unix:{runtime}/pulse/native")

    spawn(["Xvfb", ":99", "-screen", "0", SCREEN, "-nolisten", "tcp", "-ac"], "xvfb")
    wait_for("/tmp/.X11-unix/X99")
    spawn(["openbox"], "openbox")

    # -n: skip the default script (it probes D-Bus, which does not exist here); load only what we need.
    subprocess.run(
        [
            "pulseaudio",
            "-D",
            "-n",
            "--exit-idle-time=-1",
            "--log-target=file:/tmp/pulse.log",
            "--load=module-native-protocol-unix",
            "--load=module-null-sink sink_name=tilo_out",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    subprocess.run(["pactl", "set-default-sink", "tilo_out"], check=False)  # Meet audio lands here

    # VNC listens only inside the container; only noVNC (published on 127.0.0.1) can reach it.
    spawn(
        [
            "x11vnc",
            "-display",
            ":99",
            "-forever",
            "-shared",
            "-nopw",
            "-localhost",
            "-rfbport",
            "5900",
            "-noxdamage",
            "-wait",
            "50",
            "-defer",
            VNC_FPS_DELAY_MS,
        ],
        "x11vnc",
    )
    spawn(["websockify", "--web", "/usr/share/novnc", "6080", "localhost:5900"], "novnc")

    cmd = sys.argv[1:] or ["python", "-m", "bot.main", "--help"]
    os.execvp(cmd[0], cmd)  # the command becomes PID 1's process and receives docker stop signals directly


if __name__ == "__main__":
    main()
