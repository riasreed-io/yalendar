from __future__ import annotations

import os
import secrets
from pathlib import Path

from .config import PASSWORD_PATH


def dashboard_password() -> str:
    env = os.environ.get("YALE_TODAY_PASSWORD", "").strip()
    if env:
        return env
    if PASSWORD_PATH.exists():
        stored = PASSWORD_PATH.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    token = secrets.token_urlsafe(12)
    PASSWORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    PASSWORD_PATH.write_text(token + "\n", encoding="utf-8")
    os.chmod(PASSWORD_PATH, 0o600)
    return token


def password_file() -> Path:
    dashboard_password()
    return PASSWORD_PATH
