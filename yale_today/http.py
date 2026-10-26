from __future__ import annotations

import ssl

import certifi
import httpx

from .config import USER_AGENT, network_allowed

_CTX = ssl.create_default_context(cafile=certifi.where())


class OfflineMode(RuntimeError):
    """Raised when demo mode tries to fetch. Every outbound request in the
    app goes through client(), so this is the one place that has to hold."""


def client(timeout: float = 45.0) -> httpx.Client:
    if not network_allowed():
        raise OfflineMode(
            "This build serves the frozen demo snapshot and does not fetch "
            "anything. Unset YALENDAR_MODE=demo to pull live events."
        )
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        verify=_CTX,
        trust_env=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/calendar, */*"},
    )
