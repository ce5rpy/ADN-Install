"""Configuration init, set, wizard, and deploy.conf helpers."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from adn_deploy.core.env import Settings, init_env, apply_docker_cli_container_paths, parse_deploy_conf
from adn_deploy.domain.aprs_passcode import (
    aprs_base_callsign,
    is_placeholder_aprs_login,
    normalize_base_callsign,
    parse_aprs_login,
)
from adn_deploy.core.paths import deploy_overrides_manifest, mandatory_setup_done_marker
from adn_deploy.core.subprocess_runner import is_dry_run, run
from adn_deploy.infra import yaml_store


_PASSPHRASE_PLACEHOLDER = re.compile(r"^<set-in-[^>]+>\s*$", re.IGNORECASE)
_PLACEHOLDER_NGINX = frozenset({"example.adn.systems", "example.com", "test.example.adn.systems"})
_PLACEHOLDER_ACME_EMAIL = frozenset({"admin@example.com", "ssl@example.com"})
_PLACEHOLDER_DASHTITLE = frozenset({"ADN Systems", "ADN Systems Dashboard"})

SERVICE_FILES = {
    "adn-server": lambda s: s.adn_dmr_server_path / "adn-server.yaml",
    "server": lambda s: s.adn_dmr_server_path / "adn-server.yaml",
    "adn-echo": lambda s: s.adn_dmr_server_path / "adn-echo.yaml",
    "echo": lambda s: s.adn_dmr_server_path / "adn-echo.yaml",
    "adn-monitor": lambda s: s.adn_monitor_path / "monitor" / "adn-monitor.yaml",
    "monitor": lambda s: s.adn_monitor_path / "monitor" / "adn-monitor.yaml",
    "env": lambda s: s.adn_monitor_path / ".env",
    ".env": lambda s: s.adn_monitor_path / ".env",
    "deploy": lambda s: s.adn_deploy_conf,
    "deploy.conf": lambda s: s.adn_deploy_conf,
    "daprs": lambda s: daprs_path(s) / "gps_data.cfg",
}


def service_file(settings: Settings, svc: str) -> Path:
    fn = SERVICE_FILES.get(svc)
    if not fn:
        raise ValueError(f"unknown service: {svc}")
    path = fn(settings)
    if path is None:
        raise ValueError(f"no path for service: {svc}")
    return path


def yaml_get_path(path: Path, key: str):
    return yaml_store.yaml_get(path, key)


def yaml_set_path(settings: Settings, path: Path, key: str, value: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if is_dry_run(settings):
        print(f"[dry-run] set {key} in {path}")
        return
    yaml_store.yaml_set(path, key, value)


def apply_deploy_overrides(settings: Settings, cfg_path: Path) -> None:
    manifest = deploy_overrides_manifest(settings.adn_deploy_home)
    if not manifest.is_file() or not cfg_path.is_file():
        return
    if is_dry_run(settings):
        print(f"[dry-run] apply deploy overrides -> {cfg_path}")
        return
    yaml_store.apply_overrides(
        manifest,
        variables={
            "ADN_DMR_SERVER_PATH": str(settings.adn_dmr_server_path),
            "ADN_MONITOR_PATH": str(settings.adn_monitor_path),
            "ADN_LOG_DIR": str(settings.adn_log_dir),
            "ADN_ROOT": str(settings.adn_root),
        },
        filter_path=cfg_path,
    )


def copy_if_missing(settings: Settings, src: Path, dest: Path) -> bool:
    if dest.is_file():
        print(f"  keep existing: {dest}")
        return False
    if not src.is_file():
        print(f"  missing example: {src}", file=sys.stderr)
        return False
    run(settings, "mkdir", "-p", str(dest.parent))
    run(settings, "cp", str(src), str(dest))
    if not settings.docker:
        run(settings, "chown", f"{settings.adn_user}:{settings.adn_user}", str(dest), check=False)
    print(f"  created: {dest}")
    return True


def passphrase_default(settings: Settings) -> str:
    if settings.adn_deploy_conf and settings.adn_deploy_conf.is_file():
        conf = parse_deploy_conf(settings.adn_deploy_conf)
        if conf.get("HBP_PASSPHRASE"):
            return conf["HBP_PASSPHRASE"]
    return os.environ.get("HBP_PASSPHRASE", "passw0rd")


def normalize_server_id(settings: Settings, cfg: Path | None = None) -> None:
    cfg = cfg or (settings.adn_dmr_server_path / "adn-server.yaml")
    if not cfg.is_file():
        return
    sid = yaml_store.yaml_get(cfg, "GLOBAL.SERVER_ID")
    if sid is None:
        return
    sid_str = str(sid).strip()
    if not sid_str:
        return
    if is_dry_run(settings):
        print(f"[dry-run] normalize GLOBAL.SERVER_ID -> integer in {cfg}")
        return
    yaml_set_path(settings, cfg, "GLOBAL.SERVER_ID", sid_str)


def normalize_passphrases(settings: Settings, cfg: Path | None = None) -> None:
    cfg = cfg or (settings.adn_dmr_server_path / "adn-server.yaml")
    if not cfg.is_file():
        return
    val = passphrase_default(settings)
    if is_dry_run(settings):
        print(f"[dry-run] normalize PASSPHRASE placeholders -> {val} in {cfg}")
        return
    yaml_store.normalize_passphrases(cfg, val)


def sync_echo_passphrase(settings: Settings) -> None:
    server = settings.adn_dmr_server_path / "adn-server.yaml"
    echo_cfg = settings.adn_dmr_server_path / "adn-echo.yaml"
    if not server.is_file() or not echo_cfg.is_file():
        return
    if is_dry_run(settings):
        print(f"[dry-run] sync SYSTEMS.ECHO.PASSPHRASE from server into {echo_cfg}")
        return
    try:
        yaml_store.sync_echo_passphrase(server, echo_cfg)
    except (FileNotFoundError, ValueError):
        pass


def init_peer(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    peer = cfg.adn_dmr_server_path
    dest = peer / "adn-server.yaml"
    copy_if_missing(cfg, peer / "adn-server.example.yaml", dest)
    if dest.is_file():
        apply_deploy_overrides(cfg, dest)
        normalize_passphrases(cfg, dest)
        normalize_server_id(cfg, dest)
        sync_echo_passphrase(cfg)


def init_echo(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    peer = cfg.adn_dmr_server_path
    dest = peer / "adn-echo.yaml"
    examples = (
        peer / "adn-echo.example.yaml",
        peer / "adn-echo.yaml.example",
        peer / "adn-parrot.example.yaml",
        peer / "adn-parrot.yaml.example",
    )
    if not dest.is_file():
        for example in examples:
            if copy_if_missing(cfg, example, dest):
                break
    if dest.is_file():
        apply_deploy_overrides(cfg, dest)
        normalize_passphrases(cfg, dest)
        sync_echo_passphrase(cfg)


def init_monitor(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    mon = cfg.adn_monitor_path / "monitor"
    example = mon / "adn-monitor.yaml.example"
    if not example.is_file():
        example = mon / "adn-monitor.example.yaml"
    dest = mon / "adn-monitor.yaml"
    copy_if_missing(cfg, example, dest)
    if dest.is_file():
        apply_deploy_overrides(cfg, dest)
    copy_if_missing(cfg, cfg.adn_monitor_path / ".env.example", cfg.adn_monitor_path / ".env")
    normalize_env(cfg)


def normalize_env(settings: Settings) -> None:
    envf = settings.adn_monitor_path / ".env"
    if not envf.is_file():
        return
    if is_dry_run(settings):
        print(f"[dry-run] normalize ADN_CONFIG_PATH in {envf}")
        return
    text = envf.read_text(encoding="utf-8")
    text = text.replace("adn-mon.yaml", "adn-monitor.yaml")
    text = re.sub(
        r"ADN_CONFIG_PATH=.*",
        f"ADN_CONFIG_PATH={settings.adn_monitor_path}/monitor/adn-monitor.yaml",
        text,
    )
    envf.write_text(text, encoding="utf-8")




def daprs_path(settings: Settings) -> Path:
    return settings.adn_root / "D-APRS"


def daprs_cfg_path(settings: Settings) -> Path:
    """gps_data.cfg location: docker bind-mount uses state/daprs/; bare metal uses D-APRS/."""
    if settings.docker:
        return settings.adn_root / "daprs" / "gps_data.cfg"
    return daprs_path(settings) / "gps_data.cfg"


def _daprs_master_host(settings: Settings) -> str:
    if settings.docker:
        return (os.environ.get("ADN_SERVER_HOST") or "adn-server").strip() or "adn-server"
    return "127.0.0.1"


def _daprs_master_port(settings: Settings) -> str:
    server = settings.adn_dmr_server_path / "adn-server.yaml"
    if server.is_file():
        port = yaml_store.yaml_get(server, "SYSTEMS.D-APRS.PORT")
        if port is not None:
            return str(port)
    return "52555"


def _daprs_aprs_server(settings: Settings) -> str:
    return (settings.daprs_aprs_server or "rotate.aprs2.net").strip() or "rotate.aprs2.net"


def _daprs_aprs_credentials(settings: Settings) -> tuple[str, str, str]:
    """Return (login call, passcode, aprs server) for gps_data.cfg."""
    server = _daprs_aprs_server(settings)
    raw = (settings.daprs_aprs_callsign or "").strip()
    if raw and not is_placeholder_aprs_login(raw):
        login, passcode = parse_aprs_login(raw)
        return login, str(passcode), server
    return "N0CALL", "12345", server


def _read_gps_aprs_login(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("APRS_LOGIN_CALL:"):
            return line.split(":", 1)[1].strip()
    return ""


def _patch_gps_data_aprs(
    path: Path,
    login_call: str,
    passcode: str,
    *,
    server: str | None = None,
) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    changed = False
    for line in lines:
        if line.startswith("APRS_LOGIN_CALL:"):
            new = f"APRS_LOGIN_CALL: {login_call}"
            if line != new:
                changed = True
            out.append(new)
        elif line.startswith("APRS_LOGIN_PASSCODE:"):
            new = f"APRS_LOGIN_PASSCODE: {passcode}"
            if line != new:
                changed = True
            out.append(new)
        elif server and line.startswith("APRS_SERVER:"):
            new = f"APRS_SERVER: {server}"
            if line != new:
                changed = True
            out.append(new)
        else:
            out.append(line)
    if changed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def _apply_daprs_aprs_from_deploy_conf(settings: Settings, dest: Path) -> None:
    raw = (settings.daprs_aprs_callsign or "").strip()
    if not raw or is_placeholder_aprs_login(raw):
        return
    login, passcode = parse_aprs_login(raw)
    server = _daprs_aprs_server(settings)
    if is_dry_run(settings):
        print(f"[dry-run] patch APRS login in {dest}")
        return
    if _patch_gps_data_aprs(dest, login, str(passcode), server=server):
        if not settings.docker:
            run(settings, "chown", f"{settings.adn_user}:{settings.adn_user}", str(dest), check=False)
        print(f"  updated: {dest} (APRS login {login})")


def _render_daprs_gps_cfg(settings: Settings) -> str:
    tpl = settings.adn_deploy_home / "templates/daprs/gps_data.cfg.in"
    if not tpl.is_file():
        raise FileNotFoundError(tpl)
    content = tpl.read_text(encoding="utf-8")
    dmr_id = str(settings.daprs_data_dmr_id or "900999")
    peer_port = str(settings.daprs_peer_port or "54871")
    aprs_login, aprs_pass, aprs_server = _daprs_aprs_credentials(settings)
    if settings.docker:
        adn_root = "/docker-state"
        dmr_path = "/docker-state/peer"
        log_dir = "/docker-state/logs"
    else:
        adn_root = str(settings.adn_root)
        dmr_path = str(settings.adn_dmr_server_path)
        log_dir = str(settings.adn_log_dir)
    mapping = {
        "${ADN_ROOT}": adn_root,
        "${ADN_DMR_SERVER_PATH}": dmr_path,
        "${ADN_LOG_DIR}": log_dir,
        "${HBP_PASSPHRASE}": passphrase_default(settings),
        "${DAPRS_MASTER_PORT}": _daprs_master_port(settings),
        "${DAPRS_PEER_PORT}": peer_port,
        "${DAPRS_DATA_DMR_ID}": dmr_id,
        "APRS_LOGIN_CALL: N0CALL": f"APRS_LOGIN_CALL: {aprs_login}",
        "APRS_LOGIN_PASSCODE: 12345": f"APRS_LOGIN_PASSCODE: {aprs_pass}",
        "APRS_SERVER: rotate.aprs2.net": f"APRS_SERVER: {aprs_server}",
        "MASTER_IP: 127.0.0.1": f"MASTER_IP: {_daprs_master_host(settings)}",
    }
    for key, val in mapping.items():
        content = content.replace(key, val)
    if settings.docker:
        content = content.replace("/docker-state/D-APRS/", "/docker-state/daprs/")
    return content


_DAPRS_IGATE_KEYS = (
    "IGATE_BEACON_TIME: 45",
    "IGATE_BEACON_ICON: /I",
    "IGATE_BEACON_COMMENT: ADN D-APRS Gateway",
    "IGATE_LATITUDE: 0000.00N",
    "IGATE_LONGITUDE: 00000.00W",
)


def _gps_cfg_missing_igate_keys(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return any(key.split(":")[0] not in text for key in _DAPRS_IGATE_KEYS)


def _patch_daprs_gps_cfg_igate(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if line.startswith("APRS_PORT:") and not inserted:
            out.extend(_DAPRS_IGATE_KEYS)
            inserted = True
    if not inserted:
        out.extend(["", "[GPS_DATA]", *_DAPRS_IGATE_KEYS])
    path.write_text("\n".join(out) + "\n", encoding="utf-8")



def _sync_daprs_gps_cfg(settings: Settings, path: Path) -> bool:
    """Align co-located peer block with ADN defaults (IGATE section, ports, IDs)."""
    dmr_id = str(settings.daprs_data_dmr_id or "900999")
    peer_port = str(settings.daprs_peer_port or "54871")
    master_port = _daprs_master_port(settings)
    passphrase = passphrase_default(settings)
    options = f"TS2={dmr_id};DIAL=0;VOICE=0;LANG=es_ES;SINGLE=1;TIMER=10;"
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    changed = False
    in_peer = False
    peer_header = False
    for line in lines:
        stripped = line.strip()
        if stripped in ("[D-APRS]", "[IGATE]"):
            in_peer = True
            peer_header = True
            if stripped != "[IGATE]":
                changed = True
            out.append("[IGATE]")
            continue
        if in_peer and stripped.startswith("[") and stripped.endswith("]"):
            in_peer = False
        if not in_peer:
            if line.startswith("DATA_DMR_ID:"):
                new = f"DATA_DMR_ID: {dmr_id}"
                if line != new:
                    changed = True
                out.append(new)
                continue
            out.append(line)
            continue
        # peer / igate section
        replacements = {
            "PORT:": f"PORT: {peer_port}",
            "MASTER_IP:": f"MASTER_IP: {_daprs_master_host(settings)}",
            "MASTER_PORT:": f"MASTER_PORT: {master_port}",
            "PASSPHRASE:": f"PASSPHRASE: {passphrase}",
            "RADIO_ID:": f"RADIO_ID: {dmr_id}",
            "LOOSE:": "LOOSE: False",
            "OPTIONS:": f"OPTIONS: {options}",
        }
        matched = False
        for prefix, new in replacements.items():
            if line.startswith(prefix):
                if line != new:
                    changed = True
                out.append(new)
                matched = True
                break
        if not matched:
            if peer_header and stripped.startswith("IP:"):
                if line.strip() not in ("IP:", "IP: 127.0.0.1"):
                    changed = True
                out.append("IP:")
                matched = True
        peer_header = False
        if not matched:
            out.append(line)
    if changed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed

def _ensure_daprs_hblink_symlink(settings: Settings, tree: Path) -> None:
    target = tree / "gps_data.cfg"
    link = tree / "hblink.cfg"
    if not target.is_file():
        return
    if link.is_symlink() and link.resolve() == target.resolve():
        return
    if is_dry_run(settings):
        print(f"[dry-run] symlink {link} -> gps_data.cfg")
        return
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to("gps_data.cfg")
    if not settings.docker:
        run(settings, "chown", "-h", f"{settings.adn_user}:{settings.adn_user}", str(link), check=False)
    print(f"  linked: {link} -> gps_data.cfg")


def init_daprs(settings: Settings | None = None) -> None:
    from adn_deploy.domain.plugins import is_plugin_enabled

    cfg = settings or init_env()
    if not is_plugin_enabled(cfg.paths.plugins, cfg.adn_root, "daprs"):
        return
    tree = daprs_path(cfg)
    dest = daprs_cfg_path(cfg)
    if not cfg.docker and not (tree / "gps_data.py").is_file():
        print(f"  daprs: skip gps_data.cfg (tree missing at {tree})")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        if _gps_cfg_missing_igate_keys(dest):
            if is_dry_run(cfg):
                print(f"[dry-run] patch IGATE keys in {dest}")
            else:
                _patch_daprs_gps_cfg_igate(dest)
                if not cfg.docker:
                    run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(dest), check=False)
                print(f"  updated: {dest} (IGATE keys)")
        else:
            if _sync_daprs_gps_cfg(cfg, dest):
                if not cfg.docker:
                    run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(dest), check=False)
                print(f"  updated: {dest} (co-located peer defaults)")
            else:
                print(f"  keep existing: {dest}")
    elif is_dry_run(cfg):
        print(f"[dry-run] render {dest}")
    else:
        dest.write_text(_render_daprs_gps_cfg(cfg), encoding="utf-8")
        if not cfg.docker:
            run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(dest), check=False)
        print(f"  created: {dest}")
    if cfg.docker:
        _ensure_daprs_hblink_symlink(cfg, dest.parent)
    else:
        _ensure_daprs_hblink_symlink(cfg, tree)
    if dest.is_file():
        _apply_daprs_aprs_from_deploy_conf(cfg, dest)


def init_all(settings: Settings | None = None) -> None:
    init_peer(settings)
    init_echo(settings)
    init_monitor(settings)
    init_daprs(settings)
    ensure_alias_files(settings)


def _alias_file_usable(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return bool(text) and text not in ("{}", "[]")


def ensure_alias_files(settings: Settings | None = None) -> bool:
    """Ensure peer/subscriber/tgid alias files exist under the DMR server tree."""
    import urllib.error
    import urllib.request

    cfg = settings or init_env()
    if cfg.docker or cfg.filegen or cfg.skip_os_packages:
        return True
    peer_yaml = cfg.adn_dmr_server_path / "adn-server.yaml"
    if not peer_yaml.is_file():
        return False
    pairs = (
        ("ALIASES.PEER_FILE", "ALIASES.PEER_URL"),
        ("ALIASES.SUBSCRIBER_FILE", "ALIASES.SUBSCRIBER_URL"),
        ("ALIASES.TGID_FILE", "ALIASES.TGID_URL"),
    )
    ok = True
    for file_key, url_key in pairs:
        fname = yaml_store.yaml_get(peer_yaml, file_key)
        url = yaml_store.yaml_get(peer_yaml, url_key)
        if not fname or not url:
            continue
        dest = cfg.adn_dmr_server_path / str(fname)
        if _alias_file_usable(dest):
            continue
        if is_dry_run(cfg):
            print(f"[dry-run] download alias {url} -> {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(str(url), timeout=90) as resp:
                data = resp.read()
            if not data.strip():
                raise ValueError("empty response")
            dest.write_bytes(data)
            run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(dest), check=False)
            print(f"  aliases: downloaded {dest.name}")
        except (OSError, urllib.error.URLError, ValueError) as exc:
            print(f"  WARN: alias download failed ({url}): {exc}", file=sys.stderr)
            dest.write_text("{}\n", encoding="utf-8")
            run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(dest), check=False)
            print(f"  aliases: wrote empty JSON placeholder {dest.name}")
            ok = False
    return ok


def _docker_compose_env_path(settings: Settings) -> Path | None:
    raw = os.environ.get("ADN_DOCKER_ENV_FILE", "").strip()
    if raw:
        return Path(raw)
    if settings.docker:
        return settings.adn_deploy_home / "install-docker" / "compose" / ".env"
    return None


def _set_compose_env_kv(path: Path, key: str, value: str) -> bool:
    if not value or not path.parent.exists():
        return False
    line = f"{key}={value}"
    lines: list[str] = []
    found = False
    if path.is_file():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.startswith(f"{key}="):
                lines.append(line)
                found = True
            else:
                lines.append(ln)
    if not found:
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _sync_docker_compose_env(settings: Settings) -> None:
    """Mirror deploy.conf values that compose.yml interpolates into compose/.env."""
    env_path = _docker_compose_env_path(settings)
    conf = settings.adn_deploy_conf
    if env_path is None or conf is None or not conf.is_file():
        return
    if is_dry_run(settings):
        print(f"[dry-run] sync compose env -> {env_path}")
        return
    changed = False
    for key in ("HBP_PASSPHRASE",):
        val = get_deploy_kv(conf, key) or os.environ.get(key, "")
        if val and _set_compose_env_kv(env_path, key, val):
            changed = True
    if changed:
        print(f"  docker: synced deploy.conf -> {env_path}")


def sync_docker_wizard_config(settings: Settings | None = None) -> None:
    """Docker only: materialize deploy.conf wizard fields into state YAMLs and compose .env."""
    cfg = settings or init_env()
    if not cfg.docker:
        return
    conf = cfg.adn_deploy_conf
    if conf and conf.is_file():
        cfg.apply_deploy_conf(parse_deploy_conf(conf))
    apply_docker_cli_container_paths(cfg)

    if is_dry_run(cfg):
        print("[dry-run] sync_docker_wizard_config")
        return

    init_peer(cfg)
    init_echo(cfg)
    init_monitor(cfg)

    peer = cfg.adn_dmr_server_path / "adn-server.yaml"
    mon = cfg.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    echo = cfg.adn_dmr_server_path / "adn-echo.yaml"

    if peer.is_file():
        apply_deploy_overrides(cfg, peer)
    if echo.is_file():
        apply_deploy_overrides(cfg, echo)
    if mon.is_file():
        apply_deploy_overrides(cfg, mon)

    sid = (cfg.adn_server_id or (get_deploy_kv(conf, "ADN_SERVER_ID") if conf else "")).strip()
    if not sid and peer.is_file():
        sid = str(yaml_store.yaml_get(peer, "GLOBAL.SERVER_ID") or "").strip()
    if sid and not server_id_invalid(sid):
        yaml_set_path(cfg, peer, "GLOBAL.SERVER_ID", sid)
        normalize_server_id(cfg, peer)
        if conf:
            set_kv(cfg, conf, "ADN_SERVER_ID", sid)

    title = (cfg.adn_dashtitle or (get_deploy_kv(conf, "ADN_DASHTITLE") if conf else "")).strip()
    if not title and mon.is_file():
        title = str(yaml_store.yaml_get(mon, "DASHBOARD.DASHTITLE") or "").strip()
    if title and not is_placeholder_dashtitle(title):
        yaml_set_path(cfg, mon, "DASHBOARD.DASHTITLE", title)
        if conf:
            set_kv(cfg, conf, "ADN_DASHTITLE", title)

    domain = (cfg.traefik_host_names or cfg.nginx_server_names or "").strip()
    if domain and not is_placeholder_nginx_names(domain) and conf:
        set_kv(cfg, conf, "TRAEFIK_HOST_NAMES", domain)
        set_kv(cfg, conf, "NGINX_SERVER_NAMES", domain)
        set_kv(cfg, conf, "CERTBOT_PRIMARY_DOMAIN", domain.split()[0])

    if peer.is_file():
        normalize_passphrases(cfg, peer)
    if echo.is_file():
        normalize_passphrases(cfg, echo)
        sync_echo_passphrase(cfg)

    init_daprs(cfg)
    daprs_cfg = daprs_cfg_path(cfg)
    if daprs_cfg.is_file():
        _apply_daprs_aprs_from_deploy_conf(cfg, daprs_cfg)

    _sync_docker_compose_env(cfg)
    print("  docker: wizard config synced (deploy.conf -> state + compose .env)")


def escape_deploy_val(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def get_deploy_kv(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            val = line.split("=", 1)[1].strip().strip('"')
            return val
    return ""


def set_kv(settings: Settings, file: Path, key: str, value: str) -> None:
    if is_dry_run(settings):
        print(f"[dry-run] set {key} in {file}")
        return
    if not file.is_file():
        deploy_conf_init(settings)
    esc = escape_deploy_val(value)
    line = f'{key}="{esc}"'
    lines: list[str] = []
    found = False
    if file.is_file():
        for ln in file.read_text(encoding="utf-8").splitlines():
            if ln.startswith(f"{key}="):
                lines.append(line)
                found = True
            else:
                lines.append(ln)
    if not found:
        lines.append(line)
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if file == settings.adn_deploy_conf:
        deploy_conf_fix_perms(settings, file)


def deploy_conf_fix_perms(settings: Settings, conf: Path | None = None) -> None:
    conf = conf or settings.adn_deploy_conf
    if conf is None or not conf.is_file():
        return
    user = settings.adn_user
    if settings.docker:
        run(settings, "chmod", "644", str(conf), check=False)
        return
    if is_dry_run(settings):
        print(f"[dry-run] chown root:{user} chmod 640 {conf}")
        return
    try:
        import pwd

        pwd.getpwnam(user)
    except KeyError:
        print(f"  deploy.conf: skip permissions (user {user} missing)", file=sys.stderr)
        return
    if run(settings, "chown", f"root:{user}", str(conf), check=False).returncode == 0:
        run(settings, "chmod", "640", str(conf))
    else:
        if os.geteuid() != 0:
            print(
                f"  WARN: deploy.conf must be root:{user} mode 640 for systemd "
                f"(run: sudo adn-deploy doctor)",
                file=sys.stderr,
            )
        run(settings, "chown", f"{user}:{user}", str(conf), check=False)
        run(settings, "chmod", "600", str(conf), check=False)


def deploy_conf_init(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    conf = cfg.adn_deploy_conf
    assert conf is not None
    if not conf.is_file():
        for ex in (
            cfg.adn_deploy_home / "deploy.conf.example",
            cfg.adn_deploy_home / "templates" / "deploy.conf.example",
        ):
            if ex.is_file():
                run(cfg, "cp", str(ex), str(conf))
                print(f"Created {conf}")
                break
    from adn_deploy.application import users

    users.fix_permissions(cfg)
    deploy_conf_fix_perms(cfg, conf)


def persist_pyenv_python(settings: Settings) -> bool:
    py = settings.pyenv_python()
    if not py.is_file():
        print(f"ERROR: cannot persist ADN_PYENV_PYTHON — not executable: {py}", file=sys.stderr)
        return False
    settings.adn_pyenv_python = py
    conf = settings.adn_deploy_conf
    assert conf is not None
    run(settings, "mkdir", "-p", str(conf.parent))
    if not conf.is_file():
        deploy_conf_init(settings)
    set_kv(settings, conf, "ADN_PYENV_PYTHON", str(py))
    print(f"  pyenv: wrote ADN_PYENV_PYTHON to {conf}")
    return True


def passphrase_is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True
    return bool(_PASSPHRASE_PLACEHOLDER.match(v))


def server_id_invalid(sid: str | None) -> bool:
    sid = str(sid or "").strip()
    if not sid or sid == "0":
        return True
    return not sid.isdigit()


def is_placeholder_nginx_names(names: str) -> bool:
    return names.strip() in _PLACEHOLDER_NGINX


def is_placeholder_dashtitle(title: str | None) -> bool:
    if title is None:
        return True
    t = str(title).strip().strip('"')
    return not t or t in _PLACEHOLDER_DASHTITLE


def server_id_incomplete(settings: Settings) -> bool:
    f = settings.adn_dmr_server_path / "adn-server.yaml"
    if not f.is_file():
        return True
    sid = yaml_store.yaml_get(f, "GLOBAL.SERVER_ID")
    return server_id_invalid(str(sid) if sid is not None else "")


def dashtitle_incomplete(settings: Settings) -> bool:
    f = settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    if not f.is_file():
        return True
    title = yaml_store.yaml_get(f, "DASHBOARD.DASHTITLE")
    return is_placeholder_dashtitle(str(title) if title is not None else "")


def nginx_hosts_incomplete(settings: Settings) -> bool:
    if settings.docker:
        return False
    names = settings.nginx_server_names.strip()
    if not names:
        return False
    return is_placeholder_nginx_names(names)


def traefik_acme_email_value(settings: Settings) -> str:
    from adn_deploy.core.env import get_deploy_kv

    conf = settings.adn_deploy_conf
    if conf and conf.is_file():
        return (get_deploy_kv(conf, "TRAEFIK_ACME_EMAIL") or "").strip()
    return ""


def traefik_acme_incomplete(settings: Settings) -> bool:
    if not settings.docker:
        return False
    email = traefik_acme_email_value(settings)
    return not email or email in _PLACEHOLDER_ACME_EMAIL


def daprs_plugin_enabled(settings: Settings) -> bool:
    from adn_deploy.domain.plugins import is_plugin_enabled, list_plugins

    plugin_ids = {p.id for p in list_plugins(settings.paths.plugins, settings.profile)}
    if "daprs" not in plugin_ids:
        return False
    return is_plugin_enabled(settings.paths.plugins, settings.adn_root, "daprs")


def daprs_aprs_incomplete(settings: Settings) -> bool:
    """True until DAPRS_APRS_CALLSIGN is set in deploy.conf (wizard / adn-deploy setup).

    Do not treat gps_data.cfg alone as complete — templates and hbnet clones may
    ship N0CALL or a sample callsign before the operator confirms in the wizard.
    """
    if not daprs_plugin_enabled(settings):
        return False
    raw = (settings.daprs_aprs_callsign or "").strip()
    return not raw or is_placeholder_aprs_login(raw)


def daprs_aprs_default(settings: Settings) -> str:
    raw = (settings.daprs_aprs_callsign or "").strip()
    if raw and not is_placeholder_aprs_login(raw):
        return aprs_base_callsign(raw)
    return aprs_base_callsign(_read_gps_aprs_login(daprs_cfg_path(settings)))


def mandatory_fields_incomplete(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    return (
        server_id_incomplete(cfg)
        or dashtitle_incomplete(cfg)
        or nginx_hosts_incomplete(cfg)
        or daprs_aprs_incomplete(cfg)
    )


def mandatory_missing_labels(settings: Settings | None = None) -> list[str]:
    cfg = settings or init_env()
    missing: list[str] = []
    if server_id_incomplete(cfg):
        missing.append("SERVER_ID")
    if dashtitle_incomplete(cfg):
        missing.append("DASHTITLE")
    if nginx_hosts_incomplete(cfg):
        missing.append("NGINX_SERVER_NAMES")
    if daprs_aprs_incomplete(cfg):
        missing.append("DAPRS_APRS_CALLSIGN")
    return missing


def mandatory_setup_mark_done(settings: Settings) -> None:
    if is_dry_run(settings):
        print(f"[dry-run] touch {mandatory_setup_done_marker(settings.adn_deploy_home)}")
        return
    marker = mandatory_setup_done_marker(settings.adn_deploy_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(datetime.now().isoformat() + "\n", encoding="utf-8")


def wizard_filegen_defaults(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    conf = cfg.adn_deploy_conf
    assert conf is not None
    defaults = {
        "NGINX_SERVER_NAMES": cfg.nginx_server_names or "test.example.adn.systems",
        "CERTBOT_EMAIL": cfg.certbot_email or "test@example.adn.systems",
        "CERTBOT_PRIMARY_DOMAIN": cfg.certbot_primary_domain or "test.example.adn.systems",
        "WEB_SSL": cfg.web_ssl or "0",
        "MONITOR_APP_PORT": cfg.monitor_app_port or "8080",
        "MONITOR_APP_UPSTREAM": cfg.monitor_app_upstream or "127.0.0.1",
    }
    for k, v in defaults.items():
        set_kv(cfg, conf, k, v)
    print(f"  wizard: filegen test defaults -> {conf}")


def wizard_user(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.filegen:
        return True
    from adn_deploy.application import users

    return users.ensure_user_adn(cfg)


def install_first_run_setup(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    if mandatory_fields_incomplete(cfg):
        print("  config: mandatory fields incomplete — install wizard runs next")


def set_cmd(settings: Settings | None, svc: str, key: str, value: str) -> int:
    cfg = settings or init_env()
    if svc == "daprs":
        return 0 if set_daprs_setting(cfg, key, value) else 1
    if svc in ("deploy", "deploy.conf"):
        conf = cfg.adn_deploy_conf
        assert conf is not None
        set_kv(cfg, conf, key, value)
        cfg.apply_deploy_conf(parse_deploy_conf(conf))
        if key in ("MYSQL_DB_NAME", "MYSQL_DB_USER", "MYSQL_DB_PASSWORD"):
            mysql_sync_yaml(cfg)
        return 0
    path = service_file(cfg, svc)
    yaml_set_path(cfg, path, key, value)
    if svc in ("adn-server", "server") and key == "GLOBAL.SERVER_ID":
        normalize_server_id(cfg, path)
    return 0


def mysql_persist(settings: Settings) -> None:
    conf = settings.adn_deploy_conf
    assert conf is not None
    set_kv(settings, conf, "MYSQL_DB_NAME", settings.mysql_db_name or "hbmon")
    set_kv(settings, conf, "MYSQL_DB_USER", settings.mysql_db_user or "self_service_user")
    if settings.mysql_db_password:
        set_kv(settings, conf, "MYSQL_DB_PASSWORD", settings.mysql_db_password)
    if settings.mysql_root_password:
        set_kv(settings, conf, "MYSQL_ROOT_PASSWORD", settings.mysql_root_password)


def _mysql_credentials(settings: Settings) -> tuple[str, str, str]:
    """Resolve db name, user, password (deploy.conf, then monitor yaml)."""
    db = settings.mysql_db_name or "hbmon"
    user = settings.mysql_db_user or "self_service_user"
    password = settings.mysql_db_password or ""
    if not password:
        mon = settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"
        if mon.is_file():
            from adn_deploy.infra.yaml_store import yaml_get

            pw = yaml_get(mon, "SELF_SERVICE.DB_PASSWORD")
            if pw and str(pw).strip() and "<" not in str(pw):
                password = str(pw).strip()
    return db, user, password


def mysql_sync_yaml(settings: Settings) -> None:
    db, user, password = _mysql_credentials(settings)
    mon = settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    if mon.is_file():
        yaml_set_path(settings, mon, "SELF_SERVICE.DB_NAME", db)
        yaml_set_path(settings, mon, "SELF_SERVICE.DB_USERNAME", user)
        if password:
            yaml_set_path(settings, mon, "SELF_SERVICE.DB_PASSWORD", password)
        yaml_set_path(settings, mon, "SELF_SERVICE.DB_SERVER", "localhost")
        yaml_set_path(settings, mon, "SELF_SERVICE.DB_PORT", "3306")
        print(f"  mysql: synced SELF_SERVICE credentials -> {mon}")

    peer = settings.adn_dmr_server_path / "adn-server.yaml"
    if peer.is_file():
        yaml_set_path(settings, peer, "DATABASE.DB_NAME", db)
        yaml_set_path(settings, peer, "DATABASE.DB_USERNAME", user)
        if password:
            yaml_set_path(settings, peer, "DATABASE.DB_PASSWORD", password)
        yaml_set_path(settings, peer, "DATABASE.DB_SERVER", "localhost")
        yaml_set_path(settings, peer, "DATABASE.DB_PORT", "3306")
        print(f"  mysql: synced DATABASE credentials -> {peer}")


def wizard_scalars(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    if cfg.filegen:
        wizard_filegen_defaults(cfg)
        return
    try:
        import questionary
    except ImportError:
        print("  wizard: install questionary or use adn-deploy menu", file=sys.stderr)
        return
    conf = cfg.adn_deploy_conf
    assert conf is not None
    domain = questionary.text(
        "Panel domain(s), space-separated",
        default=cfg.nginx_server_names or "",
    ).ask()
    if domain:
        set_kv(cfg, conf, "NGINX_SERVER_NAMES", domain.strip())
        set_kv(cfg, conf, "CERTBOT_PRIMARY_DOMAIN", domain.strip().split()[0])
        cfg.apply_deploy_conf(parse_deploy_conf(conf))
    sid = questionary.text(
        "SERVER_ID (numeric)",
        default="",
    ).ask()
    if sid and not server_id_invalid(sid):
        peer = cfg.adn_dmr_server_path / "adn-server.yaml"
        init_peer(cfg)
        yaml_set_path(cfg, peer, "GLOBAL.SERVER_ID", sid.strip())
        normalize_server_id(cfg, peer)
    if daprs_plugin_enabled(cfg) and daprs_aprs_incomplete(cfg):
        default = cfg.daprs_aprs_callsign.strip() or _read_gps_aprs_login(
            daprs_path(cfg) / "gps_data.cfg"
        )
        aprs = questionary.text(
            "APRS callsign (base only, e.g. CE5RPY)",
            default=default,
        ).ask()
        if aprs:
            apply_daprs_aprs_login(cfg, aprs)


def wizard_server_required(settings: Settings) -> bool:
    if settings.non_interactive:
        return True
    init_peer(settings)
    peer = settings.adn_dmr_server_path / "adn-server.yaml"
    if not peer.is_file():
        return False
    sid = yaml_store.yaml_get(peer, "GLOBAL.SERVER_ID")
    if not server_id_invalid(str(sid) if sid is not None else ""):
        return True
    return False


def wizard_dashtitle_required(settings: Settings) -> bool:
    if settings.non_interactive:
        return True
    init_monitor(settings)
    mon = settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    if not mon.is_file():
        return False
    title = yaml_store.yaml_get(mon, "DASHBOARD.DASHTITLE")
    if not is_placeholder_dashtitle(str(title) if title is not None else ""):
        return True
    return False


def wizard_nginx_hosts_required(settings: Settings) -> bool:
    if settings.non_interactive:
        return True
    conf = settings.adn_deploy_conf
    if not conf:
        return False
    if not nginx_hosts_incomplete(settings):
        return True
    if not settings.nginx_server_names.strip() or is_placeholder_nginx_names(
        settings.nginx_server_names
    ):
        set_kv(settings, conf, "NGINX_SERVER_NAMES", "_")
        set_kv(settings, conf, "CERTBOT_PRIMARY_DOMAIN", "")
        if settings.docker:
            set_kv(settings, conf, "TRAEFIK_HOST_NAMES", "_")
        settings.apply_deploy_conf(parse_deploy_conf(conf))
        return True
    return False


def apply_server_id(settings: Settings, sid: str) -> bool:
    sid = sid.strip()
    if server_id_invalid(sid):
        return False
    init_peer(settings)
    peer = settings.adn_dmr_server_path / "adn-server.yaml"
    yaml_set_path(settings, peer, "GLOBAL.SERVER_ID", sid)
    normalize_server_id(settings, peer)
    if settings.docker:
        conf = settings.adn_deploy_conf
        if conf is not None:
            set_kv(settings, conf, "ADN_SERVER_ID", sid)
            settings.adn_server_id = sid
    return True


def apply_dashtitle(settings: Settings, title: str) -> bool:
    title = title.strip()
    if is_placeholder_dashtitle(title):
        return False
    init_monitor(settings)
    mon = settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    yaml_set_path(settings, mon, "DASHBOARD.DASHTITLE", title)
    if settings.docker:
        conf = settings.adn_deploy_conf
        if conf is not None:
            set_kv(settings, conf, "ADN_DASHTITLE", title)
            settings.adn_dashtitle = title
    return True


def apply_nginx_hosts(settings: Settings, domain: str) -> bool:
    domain = domain.strip()
    if not domain or is_placeholder_nginx_names(domain):
        return False
    conf = settings.adn_deploy_conf
    assert conf is not None
    set_kv(settings, conf, "NGINX_SERVER_NAMES", domain)
    set_kv(settings, conf, "CERTBOT_PRIMARY_DOMAIN", domain.split()[0])
    if settings.docker:
        set_kv(settings, conf, "TRAEFIK_HOST_NAMES", domain)
    settings.apply_deploy_conf(parse_deploy_conf(conf))
    return True


def apply_traefik_acme_email(settings: Settings, email: str) -> bool:
    email = email.strip()
    if not email or "@" not in email:
        return False
    conf = settings.adn_deploy_conf
    assert conf is not None
    set_kv(settings, conf, "TRAEFIK_ACME_EMAIL", email)
    settings.apply_deploy_conf(parse_deploy_conf(conf))
    return True



_DAPRS_CONFIG_KEYS = frozenset(
    {
        "DAPRS_APRS_CALLSIGN",
        "DAPRS_APRS_SERVER",
        "DAPRS_DATA_DMR_ID",
        "DAPRS_PEER_PORT",
    }
)


def get_daprs_setting(settings: Settings, key: str) -> str:
    if key == "DAPRS_APRS_CALLSIGN":
        return daprs_aprs_default(settings)
    if key == "DAPRS_APRS_SERVER":
        return _daprs_aprs_server(settings)
    if key == "DAPRS_DATA_DMR_ID":
        return str(settings.daprs_data_dmr_id or "900999")
    if key == "DAPRS_PEER_PORT":
        return str(settings.daprs_peer_port or "54871")
    return ""


def set_daprs_setting(settings: Settings, key: str, value: str) -> bool:
    value = value.strip()
    if not value or key not in _DAPRS_CONFIG_KEYS:
        return False
    if key == "DAPRS_APRS_CALLSIGN":
        return apply_daprs_aprs_login(settings, value)
    conf = settings.adn_deploy_conf
    assert conf is not None
    set_kv(settings, conf, key, value)
    settings.apply_deploy_conf(parse_deploy_conf(conf))
    init_daprs(settings)
    return True


def apply_daprs_aprs_login(settings: Settings, value: str) -> bool:
    try:
        base = normalize_base_callsign(value)
        login, passcode = parse_aprs_login(base)
    except ValueError:
        return False
    conf = settings.adn_deploy_conf
    assert conf is not None
    set_kv(settings, conf, "DAPRS_APRS_CALLSIGN", base)
    settings.daprs_aprs_callsign = base
    settings.apply_deploy_conf(parse_deploy_conf(conf))
    init_daprs(settings)
    dest = daprs_cfg_path(settings)
    if dest.is_file() and not is_dry_run(settings):
        _patch_gps_data_aprs(
            dest,
            login,
            str(passcode),
            server=_daprs_aprs_server(settings),
        )
        if not settings.docker:
            run(settings, "chown", f"{settings.adn_user}:{settings.adn_user}", str(dest), check=False)
    return True


def edit(settings: Settings | None, target: str) -> None:
    cfg = settings or init_env()
    path = service_file(cfg, target)
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(path)], check=False)
