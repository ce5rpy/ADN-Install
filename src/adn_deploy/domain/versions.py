"""App versions (adn-server, adn-monitor): one vocabulary for bare metal and Docker.

    ADN_VERSION          both apps (default: stable)
    ADN_SERVER_VERSION   adn-server only (wins over ADN_VERSION)
    ADN_MONITOR_VERSION  adn-monitor only (wins over ADN_VERSION)

Values: ``stable`` (latest release), ``develop`` (development branch) or a release
``X.Y.Z``. Bare metal checks out master / develop / vX.Y.Z; Docker pulls the images
:latest / :develop / :X.Y.Z.
"""

from __future__ import annotations

import re

VERSION_KEYS = ("ADN_VERSION", "ADN_SERVER_VERSION", "ADN_MONITOR_VERSION")
COMPONENTS = ("server", "monitor")

_RELEASE = re.compile(r"^v?(\d+\.\d+\.\d+)$")
_STABLE_ALIASES = ("stable", "latest", "master")


def normalize_version(value: str) -> str:
    """Canonical form: stable | develop | X.Y.Z. Raises ValueError otherwise."""
    v = (value or "").strip().lower()
    if v in _STABLE_ALIASES:
        return "stable"
    if v == "develop":
        return "develop"
    m = _RELEASE.match(v)
    if m:
        return m.group(1)
    raise ValueError(f"version must be stable, develop or X.Y.Z (got {value!r})")


def git_ref(version: str) -> str:
    """Git ref to check out for a version (bare metal)."""
    v = normalize_version(version)
    if v == "stable":
        return "master"
    if v == "develop":
        return "develop"
    return f"v{v}"


def image_tag(version: str) -> str:
    """Docker image tag for a version."""
    v = normalize_version(version)
    return "latest" if v == "stable" else v


def effective_version(specific: str, common: str) -> str:
    """The version that applies to one app: its own setting, else ADN_VERSION, else ''."""
    for value in (specific, common):
        if (value or "").strip():
            return normalize_version(value)
    return ""
