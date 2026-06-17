import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from webcaldav.i18n import DEFAULT, SUPPORTED, load_catalog, resolve_language

_LOCALES = Path(__file__).resolve().parent.parent / "webcaldav" / "locales"


def _flatten_keys(d, prefix=""):
    keys = set()
    for k, v in d.items():
        keys.add(prefix + k)
        if isinstance(v, dict):
            keys |= _flatten_keys(v, prefix + k + ".")
    return keys


def test_resolve_language_concrete_setting_wins():
    # A concrete setting ignores the browser header entirely.
    assert resolve_language("english", "cs,sk;q=0.8") == "en"
    assert resolve_language("czech", "en-US,en;q=0.9") == "cs"


def test_resolve_language_autodetect_uses_header_by_q():
    assert resolve_language("autodetect", "cs-CZ,cs;q=0.9,en;q=0.5") == "cs"
    # Highest-q supported tag wins even when listed after a higher-q unsupported one.
    assert resolve_language("autodetect", "de;q=1.0,cs;q=0.8") == "cs"


def test_resolve_language_falls_back_to_default():
    assert resolve_language("autodetect", None) == DEFAULT
    assert resolve_language("autodetect", "de-DE,fr;q=0.7") == DEFAULT
    # Unknown setting is treated like autodetect.
    assert resolve_language("martian", None) == DEFAULT


def test_load_catalog_has_expected_sections():
    cat = load_catalog("en")
    for section in ("ui", "dyn", "errors", "fc", "units", "ordinals"):
        assert section in cat
    # Unknown code falls back to the default catalog rather than raising.
    assert load_catalog("xx") == load_catalog(DEFAULT)


@pytest.mark.parametrize("code", sorted(SUPPORTED))
def test_catalog_is_valid_json(code):
    json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def test_catalogs_have_identical_keys():
    """Every shipped catalog must define the exact same keys as English, so no
    string silently falls back to its key in another language."""
    base = _flatten_keys(load_catalog("en"))
    for code in SUPPORTED - {"en"}:
        other = _flatten_keys(load_catalog(code))
        assert other == base, f"{code}.json key mismatch: {base ^ other}"


# The visible UI text is swapped client-side from window.__I18N__ (which Jinja
# emits as ASCII-escaped JSON), so the render tests assert on the resolved
# language code injected into the page rather than on translated glyphs.
@pytest.mark.asyncio
async def test_root_autodetect_resolves_czech_from_header(client: AsyncClient, db_engine):
    r = await client.get("/", headers={"Accept-Language": "cs-CZ,cs;q=0.9"})
    assert r.status_code == 200
    assert 'lang="cs"' in r.text
    assert 'window.__LANG__ = "cs"' in r.text


@pytest.mark.asyncio
async def test_root_defaults_to_english(client: AsyncClient, db_engine):
    r = await client.get("/", headers={"Accept-Language": "de-DE,de;q=0.9"})
    assert r.status_code == 200
    assert 'lang="en"' in r.text
    assert 'window.__LANG__ = "en"' in r.text
