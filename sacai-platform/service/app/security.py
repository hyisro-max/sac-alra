"""Shared-token and filesystem-boundary checks for internal SACAI requests."""

import hmac
from pathlib import Path

from fastapi import Header, HTTPException, status

from .config import get_settings


def require_internal_token(x_sacai_token: str = Header(default="")) -> None:
    """Reject callers that do not present the configured service token.

    The header value is the input and successful validation returns nothing.
    This dependency protects every API route behind the Docker-private network.
    """

    expected = get_settings().internal_token
    if not hmac.compare_digest(x_sacai_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


def resolve_below(path_value: str, root: Path) -> Path:
    """Resolve a path and require it to stay below an approved root.

    The function receives an untrusted path string and approved root, returning
    the canonical path used by workers or raising before filesystem access.
    """

    candidate = Path(path_value).resolve()
    approved = root.resolve()
    try:
        candidate.relative_to(approved)
    except ValueError as error:
        raise ValueError(f"path is outside approved root: {approved}") from error
    return candidate

