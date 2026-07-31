from __future__ import annotations

import os
from urllib.parse import urlsplit

import requests


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


SIMBAD_CONNECT_TIMEOUT_SECONDS = _positive_float(
    "SIMBAD_CONNECT_TIMEOUT_SECONDS", 10
)
SIMBAD_READ_TIMEOUT_SECONDS = _positive_float(
    "SIMBAD_READ_TIMEOUT_SECONDS", 20
)
MAST_CONNECT_TIMEOUT_SECONDS = _positive_float(
    "MAST_CONNECT_TIMEOUT_SECONDS", 10
)
MAST_READ_TIMEOUT_SECONDS = _positive_float(
    "MAST_READ_TIMEOUT_SECONDS", 90
)

_SIMBAD_HOST_SUFFIXES = (
    "simbad.cds.unistra.fr",
    "simbad.u-strasbg.fr",
)
_MAST_HOST_SUFFIXES = (
    "mast.stsci.edu",
    "archive.stsci.edu",
)


def default_timeout_for_url(url: str) -> tuple[float, float] | None:
    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    if any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in _SIMBAD_HOST_SUFFIXES
    ):
        return (
            SIMBAD_CONNECT_TIMEOUT_SECONDS,
            SIMBAD_READ_TIMEOUT_SECONDS,
        )
    if any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in _MAST_HOST_SUFFIXES
    ):
        return (
            MAST_CONNECT_TIMEOUT_SECONDS,
            MAST_READ_TIMEOUT_SECONDS,
        )
    return None


def install_service_timeouts() -> None:
    current_request = requests.sessions.Session.request
    if getattr(current_request, "_collectstarinfo_service_timeouts", False):
        return

    def request_with_service_timeout(
        session: requests.Session,
        method: str,
        url: str,
        **kwargs,
    ):
        if kwargs.get("timeout") is None:
            timeout = default_timeout_for_url(url)
            if timeout is not None:
                kwargs["timeout"] = timeout
        return current_request(session, method, url, **kwargs)

    request_with_service_timeout._collectstarinfo_service_timeouts = True
    requests.sessions.Session.request = request_with_service_timeout
