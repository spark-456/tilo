"""Public configuration inventory; no clients, readiness probes or environment values."""

import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/health/deps")
@router.get("/healthz/deps")
def dependency_configuration() -> dict[str, str | bool]:
    def kind(variable: str, allowed: tuple[str, ...]) -> str:
        value = os.environ.get(variable, "")
        return value if value in allowed else "invalid" if value else "unconfigured"

    def present(variable: str) -> bool:
        return bool(os.environ.get(variable, "").strip())

    return {
        "api_store": kind("TILO_API_STORE", ("firestore", "memory")),
        "artifacts_store": kind("TILO_ARTIFACTS_STORE", ("gcs",)),
        "archive_store": kind("TILO_ARCHIVE_STORE", ("gcs",)),
        "skills_store": kind("TILO_SKILLS_STORE", ("firestore", "memory")),
        "firestore_project_configured": present("TILO_FIRESTORE_PROJECT"),
        "artifacts_bucket_configured": present("TILO_ARTIFACTS_BUCKET"),
        "archive_bucket_configured": present("TILO_ARCHIVE_BUCKET"),
        "connectors_url_configured": present("TILO_CONNECTORS_URL"),
        "live_mode": os.environ.get("LIVE") == "1",
    }
