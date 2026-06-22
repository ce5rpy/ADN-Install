"""Config variable metadata for menus and wizards."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VarMeta:
    key: str
    label: str
    hint: str = ""


SERVICE_LABELS: dict[str, str] = {
    "adn-server": "Server (DMR peer)",
    "adn-monitor": "Monitor / web panel",
    "adn-echo": "Echo (PEER playback)",
    "daprs": "D-APRS (GPS/APRS gateway)",
}

COMMON_VARS: dict[str, list[VarMeta]] = {
    "adn-server": [
        VarMeta("GLOBAL.SERVER_ID", "Server ID (numeric)", "0"),
        VarMeta("GLOBAL.URL_SECURITY", "Key download URL (empty = no remote)", ""),
        VarMeta("GLOBAL.PORT_SECURITY", "Key download port", ""),
        VarMeta("GLOBAL.PASS_SECURITY", "Key download password", ""),
        VarMeta("ALIASES.PEER_URL", "Peer list URL", "https://servers.adn.systems/peer_ids.json"),
        VarMeta("REPORTS.REPORT_PORT", "Reports TCP port", "4321"),
    ],
    "adn-echo": [
        VarMeta("SYSTEMS.ECHO.MASTER_IP", "Echo master IP (adn-server)", "127.0.0.1"),
        VarMeta("SYSTEMS.ECHO.MASTER_PORT", "Echo master port", "54917"),
        VarMeta("ALIASES.PEER_URL", "Peer list URL", "https://servers.adn.systems/peer_ids.json"),
    ],
    "adn-monitor": [
        VarMeta("ADN_CONNECTION.ADN_IP", "Peer server IP", "127.0.0.1"),
        VarMeta("ADN_CONNECTION.ADN_PORT", "Peer reports port", "4321"),
        VarMeta("MONITOR_APP.LISTEN_PORT", "Monitor API + WebSocket port", "8080"),
        VarMeta("ALIASES.PEER_URL", "Peer list URL", "https://servers.adn.systems/peer_ids.json"),
    ],
    "daprs": [
        VarMeta(
            "DAPRS_APRS_CALLSIGN",
            "APRS callsign (base only)",
            "CE5RPY",
        ),
        VarMeta("DAPRS_APRS_SERVER", "APRS-IS server", "rotate.aprs2.net"),
        VarMeta(
            "DAPRS_DATA_DMR_ID",
            "Gateway DMR ID (must match peer RADIO_ID)",
            "900999",
        ),
        VarMeta("DAPRS_PEER_PORT", "Local hbnet peer UDP port", "54871"),
    ],
    "deploy": [
        VarMeta("NGINX_SERVER_NAMES", "Panel domains (space-separated)", "example.adn.systems"),
        VarMeta("WEB_SSL", "HTTPS enabled (0=HTTP only, 1=TLS)", "0"),
        VarMeta("CERTBOT_EMAIL", "Let's Encrypt email", ""),
        VarMeta("CERTBOT_PRIMARY_DOMAIN", "Primary TLS domain", ""),
        VarMeta("MONITOR_APP_PORT", "Monitor API port (nginx upstream)", "8080"),
        VarMeta("MONITOR_APP_UPSTREAM", "Monitor upstream IP", "127.0.0.1"),
        VarMeta("MYSQL_DB_NAME", "MySQL database name", "hbmon"),
        VarMeta("MYSQL_DB_USER", "MySQL application user", "self_service_user"),
        VarMeta("MYSQL_DB_PASSWORD", "MySQL application password", ""),
        VarMeta("MYSQL_ROOT_PASSWORD", "MySQL root password (if required)", ""),
    ],
}


def service_unit(service_id: str) -> str:
    if service_id in ("adn-server", "adn-monitor", "adn-echo", "daprs"):
        return service_id
    raise ValueError(f"unknown service: {service_id}")
