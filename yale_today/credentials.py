from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .config import DEFAULT_NETID_PDF


class CredentialError(RuntimeError):
    pass


def load_netid_credentials(pdf_path: Path | None = None) -> tuple[str, str]:
    """Read NetID and password from the local PDF. Never persist the values."""
    path = Path(pdf_path or DEFAULT_NETID_PDF).expanduser()
    if not path.is_file():
        raise CredentialError(f"NetID PDF not found at {path}")

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    netid_match = re.search(r"NetID\s*:\s*(\S+)", text, re.I)
    password_match = re.search(r"password\s*:\s*(\S+)", text, re.I)
    if not netid_match or not password_match:
        raise CredentialError("Could not parse NetID and password from the PDF")
    return netid_match.group(1).strip(), password_match.group(1).strip()
