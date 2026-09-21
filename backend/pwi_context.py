"""Live public-data context for the PWI engine (PS3).

Pulls REAL country-level water & WASH figures on demand from the World Bank Open
Data API (no key, CC-BY). NOTHING IS INGESTED/STORED — this is a live fetch with a
short in-process TTL cache (same pattern as news.py), so results are always current
and nothing lands in the database.

Why World Bank and not GEMStat: GEMStat (UN GEMS/Water) is registration/data-request
gated with no open API, so it cannot be queried live. FAO AQUASTAT exposes no clean
public API path. The World Bank API is genuinely open and returns real values, so it
is the honest "where possible" source for Availability/Access context. Factory
operational data and the 52-question self-assessment have NO public source — they
remain owner-supplied by design.
"""
import time

import httpx

# ISO2 (Nominatim) -> ISO3 (World Bank). Covers the apparel/manufacturing footprint
# in the sample data plus majors; unknown codes fall back to no-context.
ISO2_TO_ISO3 = {
    "in": "IND", "cn": "CHN", "vn": "VNM", "tr": "TUR", "kh": "KHM", "tw": "TWN",
    "th": "THA", "id": "IDN", "br": "BRA", "kr": "KOR", "jo": "JOR", "my": "MYS",
    "eg": "EGY", "us": "USA", "de": "DEU", "sa": "SAU", "bd": "BGD", "pk": "PAK",
    "lk": "LKA", "mm": "MMR", "ph": "PHL", "mx": "MEX", "it": "ITA", "es": "ESP",
    "pt": "PRT", "gb": "GBR", "fr": "FRA", "et": "ETH", "ke": "KEN", "ng": "NGA",
    "za": "ZAF", "au": "AUS", "ca": "CAN", "pe": "PER", "cl": "CHL", "ma": "MAR",
}

# World Bank indicators -> (label, unit, PWI relevance)
WB_INDICATORS = [
    ("SH.H2O.SMDW.ZS", "Safely managed drinking water", "% pop", "Access"),
    ("SH.H2O.BASW.ZS", "Basic drinking water", "% pop", "Access"),
    ("SH.STA.BASS.ZS", "Basic sanitation", "% pop", "Access"),
    ("ER.H2O.INTR.PC", "Renewable internal freshwater", "m³/capita", "Availability"),
    ("ER.H2O.FWTL.ZS", "Freshwater withdrawal (of internal)", "%", "Availability"),
]

_cache: dict = {}   # iso3 -> (ts, payload); ephemeral, per-process
TTL = 3600


def resolve_country(lat: float, lng: float) -> tuple[str | None, str | None]:
    """(country_name, iso3) via Nominatim reverse geocode — same service the app already uses."""
    try:
        from geopy.geocoders import Nominatim
        loc = Nominatim(user_agent="hydris-pwi-context").reverse((lat, lng), zoom=3, language="en")
        addr = (loc.raw or {}).get("address", {}) if loc else {}
        iso2 = (addr.get("country_code") or "").lower()
        return addr.get("country"), ISO2_TO_ISO3.get(iso2)
    except Exception:
        return None, None


def _wb_latest(iso3: str, code: str) -> tuple[float | None, str | None]:
    """Most-recent non-empty value for one indicator. Returns (value, year) or (None, None)."""
    try:
        r = httpx.get(f"https://api.worldbank.org/v2/country/{iso3}/indicator/{code}",
                      params={"format": "json", "mrnev": 1}, timeout=15)
        data = r.json()
        if isinstance(data, list) and len(data) > 1 and data[1]:
            row = data[1][0]
            if row.get("value") is not None:
                return float(row["value"]), row.get("date")
    except Exception:
        pass
    return None, None


def water_context(iso3: str, country_name: str | None = None) -> dict:
    """Live World Bank water/WASH context for a country. Real values, tagged with
    source + year + confidence='national (real)'. No-data indicators are kept as null,
    never guessed."""
    now = time.time()
    if iso3 in _cache and now - _cache[iso3][0] < TTL:
        return _cache[iso3][1]

    metrics = []
    for code, label, unit, dim in WB_INDICATORS:
        val, year = _wb_latest(iso3, code)
        metrics.append({
            "indicator": label, "code": code, "pwi_dimension": dim,
            "value": None if val is None else round(val, 1), "unit": unit, "year": year,
            "source": "World Bank Open Data (real, CC-BY)",
            "confidence": "national (real)" if val is not None else "no-data",
        })
    payload = {
        "country": country_name, "iso3": iso3,
        "metrics": metrics,
        "grade": "REAL-PUBLIC",
        "note": ("Live from World Bank Open Data — national scale, not site-specific; "
                 "not stored (fetched on demand). GEMStat is registration-gated so not live-queryable."),
    }
    _cache[iso3] = (now, payload)
    return payload
