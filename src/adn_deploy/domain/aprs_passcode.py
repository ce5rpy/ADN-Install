"""APRS-IS passcode from base callsign (public hash used by aprslib and UI-View)."""

from __future__ import annotations

import re

_PLACEHOLDER_LOGINS = frozenset({"N0CALL", "N0CALL-0", "N0CALL-1"})


def aprs_passcode(base_callsign: str) -> int:
    """Return APRS-IS passcode for the base callsign (no SSID)."""
    base = base_callsign.split("-")[0].strip().upper()
    if not base:
        raise ValueError("empty callsign")
    code = 0x73E2
    for i, char in enumerate(base):
        code ^= ord(char) << (8 if i % 2 == 0 else 0)
    return code & 0x7FFF


def normalize_base_callsign(value: str) -> str:
    """Validate and return the base callsign (no SSID suffix)."""
    raw = value.strip().upper().replace(" ", "")
    if not raw:
        raise ValueError("APRS callsign required")
    base = raw.split("-", 1)[0]
    if not re.fullmatch(r"[A-Z0-9]{3,8}", base):
        raise ValueError(f"invalid callsign: {value!r}")
    return base


def aprs_base_callsign(value: str) -> str:
    """Return base callsign for prompts; empty if placeholder or missing."""
    raw = value.strip().upper()
    if not raw or is_placeholder_aprs_login(raw):
        return ""
    return raw.split("-", 1)[0]


def parse_aprs_login(value: str, *, default_ssid: str = "10") -> tuple[str, int]:
    """
    Parse base callsign and return (login call with gateway SSID, passcode).

    Input is the base callsign only; ``-10`` is appended for APRS-IS login.
    A trailing ``-SSID`` in input is ignored (only the base is used).
    """
    base = normalize_base_callsign(value)
    ssid = default_ssid.strip() or "10"
    login = f"{base}-{ssid}"
    return login, aprs_passcode(base)


def is_placeholder_aprs_login(value: str) -> bool:
    login = value.strip().upper()
    return not login or login in _PLACEHOLDER_LOGINS or login.startswith("N0CALL")
