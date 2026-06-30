"""
normalize.py
------------
Stage 3 (normalize). Pure functions that take a messy raw value and
return a normalized value or None if it can't be confidently parsed.
Never raises on bad input -- always degrades to None.
"""

import re
from datetime import datetime

try:
    import phonenumbers
except ImportError:
    phonenumbers = None

from dateutil import parser as dateparser

from .schema import SKILL_ALIASES

DEFAULT_REGION = "US"  # used as a fallback hint for phone parsing only


def normalize_phone(raw, default_region=DEFAULT_REGION):
    """Return E.164 string (e.g. +14155552671) or None."""
    if not raw:
        return None
    raw = raw.strip()
    if not phonenumbers:
        # Fallback: strip non-digits, prefix +
        digits = re.sub(r"\D", "", raw)
        return f"+{digits}" if digits else None
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
    except Exception:
        pass
    return None


def normalize_email(raw):
    if not raw:
        return None
    raw = raw.strip().lower()
    if re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", raw):
        return raw
    return None


def normalize_date(raw):
    """Return YYYY-MM string or None. Handles 'Present'/'Current' as None (open-ended)."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower() in ("present", "current", "now", "ongoing"):
        return None
    try:
        dt = dateparser.parse(raw, default=datetime(1900, 1, 1))
        return dt.strftime("%Y-%m")
    except Exception:
        return None


COUNTRY_MAP = {
    "united states": "US", "usa": "US", "u.s.a.": "US", "us": "US",
    "united kingdom": "GB", "uk": "GB",
    "india": "IN", "canada": "CA", "germany": "DE", "france": "FR",
    "australia": "AU", "singapore": "SG", "netherlands": "NL",
}


def normalize_country(raw):
    if not raw:
        return None
    key = raw.strip().lower()
    return COUNTRY_MAP.get(key, raw.strip()[:2].upper() if len(raw.strip()) <= 2 else raw.strip())


def normalize_skill(raw):
    """Map a raw skill token to its canonical name. Unknown skills are
    title-cased and kept (never invented, never silently dropped)."""
    if not raw:
        return None
    key = raw.strip().lower()
    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key]
    cleaned = raw.strip()
    return cleaned if cleaned.isupper() and len(cleaned) <= 5 else cleaned.title()


def normalize_name(raw):
    if not raw:
        return None
    return " ".join(w.capitalize() if not w.isupper() else w for w in raw.strip().split())
