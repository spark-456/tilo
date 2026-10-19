"""The meeting wake config must travel with both bot images."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_P0_MEET_JOIN_images_include_wake_config():
    config = ROOT / "config/meeting-wake.json"
    assert config.is_file()
    for name in ("Dockerfile", "CloudRun.Dockerfile"):
        dockerfile = ROOT / "meet-bot/docker" / name
        ignore = dockerfile.with_name(name + ".dockerignore")
        assert "COPY config/meeting-wake.json /opt/tilo/config/" in dockerfile.read_text(encoding="utf-8")
        assert "!config/meeting-wake.json" in ignore.read_text(encoding="utf-8")
    cloud_ignore = ROOT / "meet-bot/docker/cloudbuild.gcloudignore"
    assert "!/config/meeting-wake.json" in cloud_ignore.read_text(encoding="utf-8")
