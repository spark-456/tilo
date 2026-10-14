"""Cloud Run screen/audio bootstrap. No VNC, login UI or profile volume."""

import os
import subprocess
import time
from pathlib import Path


def main() -> None:
    runtime = "/tmp/runtime-pwuser"
    os.makedirs(runtime, mode=0o700, exist_ok=True)
    os.environ.update(XDG_RUNTIME_DIR=runtime, DISPLAY=":99", PULSE_SERVER=f"unix:{runtime}/pulse/native")
    subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-nolisten", "tcp", "-ac"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    end = time.monotonic() + 15
    while not Path("/tmp/.X11-unix/X99").exists():
        if time.monotonic() >= end:
            raise SystemExit("Display startup failed")
        time.sleep(0.2)
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
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["pactl", "set-default-sink", "tilo_out"], check=True)
    os.execvp(
        "python3",
        [
            "python3",
            "-m",
            "uvicorn",
            "bot.cloud_run:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            os.environ.get("PORT", "8080"),
            "--workers",
            "1",
            "--no-access-log",
        ],
    )


if __name__ == "__main__":
    main()
