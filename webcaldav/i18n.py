"""UI language resolution and translation catalog loading.

The app stores a per-user ``language`` setting of ``autodetect`` / ``english``
/ ``czech``. At page render time we resolve that to a concrete language *code*
(``en`` / ``cs``): a concrete setting wins outright, otherwise we parse the
browser ``Accept-Language`` header and fall back to English. The matching JSON
catalog under ``locales/`` is injected into the page for the frontend to use.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# Concrete language codes the app ships catalogs for.
SUPPORTED = {"en", "cs"}
DEFAULT = "en"

# Maps the persisted user setting to a concrete code, or None for autodetect.
SETTING_TO_CODE: dict[str, str | None] = {
    "autodetect": None,
    "english": "en",
    "czech": "cs",
}

_LOCALES_DIR = Path(__file__).parent / "locales"


@lru_cache(maxsize=None)
def load_catalog(code: str) -> dict[str, Any]:
    """Return the translation catalog for ``code`` (falls back to DEFAULT)."""
    if code not in SUPPORTED:
        code = DEFAULT
    path = _LOCALES_DIR / f"{code}.json"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def _parse_accept_language(header: str) -> list[tuple[str, float]]:
    """Parse an Accept-Language header into (lang, q) pairs sorted by q desc."""
    parsed: list[tuple[str, float]] = []
    for part in header.split(","):
        part = part.strip()
        if not part:
            continue
        if ";" in part:
            tag, _, params = part.partition(";")
            q = 1.0
            for param in params.split(";"):
                key, _, value = param.partition("=")
                if key.strip() == "q":
                    try:
                        q = float(value.strip())
                    except ValueError:
                        q = 0.0
            parsed.append((tag.strip().lower(), q))
        else:
            parsed.append((part.lower(), 1.0))
    parsed.sort(key=lambda item: item[1], reverse=True)
    return parsed


def resolve_language(setting_value: str, accept_language: str | None) -> str:
    """Resolve the effective language code from the setting and the header.

    A concrete ``english``/``czech`` setting wins. For ``autodetect`` (or any
    unknown setting), pick the highest-q Accept-Language tag whose primary
    subtag is supported; otherwise return ``DEFAULT``.
    """
    code = SETTING_TO_CODE.get(setting_value, None)
    if code is not None and code in SUPPORTED:
        return code

    if accept_language:
        for tag, _q in _parse_accept_language(accept_language):
            primary = tag.split("-", 1)[0]
            if primary in SUPPORTED:
                return primary

    return DEFAULT
