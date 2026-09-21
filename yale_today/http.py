from __future__ import annotations

import ssl

import certifi
import httpx

from .config import USER_AGENT

_CTX = ssl.create_default_context(cafile=certifi.where())


def client(timeout: float = 45.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        verify=_CTX,
        trust_env=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/calendar, */*"},
    )
