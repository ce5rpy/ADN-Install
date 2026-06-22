"""UFW rebuild from adn-server.yaml (ported from scripts/ufw_rebuild_safe.py)."""

from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.subprocess_runner import is_dry_run, run

_PROXY_UFW_COMMENT = "ADN-PROXY"
_UFW_BACKUP_FILES = ("user.rules", "before.rules", "after.rules")
_OBP_LOCAL_KEYS = ("IP", "BIND_IP", "BindIP", "LISTEN_IP", "ListenIP")
_OBP_PEER_KEYS = ("TARGET_IP", "TargetIp", "PEER_IP", "PeerIp", "REMOTE_IP", "RemoteIp")


def _is_public_bind_ip(ip: str) -> bool:
    ip = (ip or "").strip()
    if not ip or ip in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::"):
        return False
    return True


def _listen_udp_ports(sys_cfg: dict[str, Any]) -> list[int]:
    mode = sys_cfg.get("MODE", "")
    if mode not in ("MASTER", "PEER", "OPENBRIDGE"):
        return []
    base = int(sys_cfg.get("PORT", 0))
    gen = int(sys_cfg.get("GENERATOR", 1))
    if gen > 1:
        return list(range(base, base + gen))
    return [base]


def _first_cfg_str(sys_cfg: dict[str, Any], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = sys_cfg.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _peer_is_ipv4_literal(raw: str) -> bool:
    s = (raw or "").strip()
    if not s:
        return False
    try:
        ipaddress.IPv4Address(s)
        return True
    except ValueError:
        return False


def udp_rules_from_yaml(
    cfg: dict[str, Any],
) -> tuple[dict[str, set[int]], list[tuple[str, int, str]], list[tuple[str, int, str, str]]]:
    udp_any: dict[str, set[int]] = defaultdict(set)
    obp_any: list[tuple[str, int, str]] = []
    obp_rules: list[tuple[str, int, str, str]] = []
    systems = cfg.get("SYSTEMS") or {}
    if not isinstance(systems, dict):
        return {}, [], []
    for sys_name, sys_cfg in systems.items():
        if not isinstance(sys_cfg, dict) or not sys_cfg.get("ENABLED", True):
            continue
        dest_ip = _first_cfg_str(sys_cfg, _OBP_LOCAL_KEYS)
        if not _is_public_bind_ip(dest_ip):
            continue
        mode = str(sys_cfg.get("MODE", "") or "")
        ports = _listen_udp_ports(sys_cfg)
        if mode == "OPENBRIDGE":
            raw_peer = _first_cfg_str(sys_cfg, _OBP_PEER_KEYS)
            if not raw_peer:
                print(
                    f"Warning: OBP {sys_name}: no peer — skipping UDP rule.",
                    file=sys.stderr,
                )
                continue
            if _peer_is_ipv4_literal(raw_peer):
                peer_ip = raw_peer.strip()
                for p in ports:
                    obp_rules.append((dest_ip, p, peer_ip, sys_name))
            else:
                print(
                    f"Note: OBP {sys_name}: peer {raw_peer!r} is a hostname; "
                    f"UDP to {dest_ip} ports {ports} — allowing from any.",
                    file=sys.stderr,
                )
                for p in ports:
                    obp_any.append((dest_ip, p, sys_name))
        else:
            for p in ports:
                udp_any[dest_ip].add(p)
    seen: set[tuple[str, int, str]] = set()
    obp_unique: list[tuple[str, int, str, str]] = []
    for dest_ip, p, peer, label in obp_rules:
        key = (dest_ip, p, peer)
        if key in seen:
            continue
        seen.add(key)
        obp_unique.append((dest_ip, p, peer, label))
    obp_unique.sort(key=lambda x: (x[0], x[2], x[1], x[3]))
    seen_any: set[tuple[str, int]] = set()
    obp_any_u: list[tuple[str, int, str]] = []
    for dest_ip, p, label in obp_any:
        key = (dest_ip, p)
        if key in seen_any:
            continue
        seen_any.add(key)
        obp_any_u.append((dest_ip, p, label))
    obp_any_u.sort(key=lambda x: (x[0], x[1], x[2]))
    return dict(udp_any), obp_any_u, obp_unique


def unique_public_bind_ips_from_systems(cfg: dict[str, Any]) -> list[str]:
    systems = cfg.get("SYSTEMS") or {}
    if not isinstance(systems, dict):
        return []
    found: set[str] = set()
    for sys_cfg in systems.values():
        if not isinstance(sys_cfg, dict) or not sys_cfg.get("ENABLED", True):
            continue
        mode = str(sys_cfg.get("MODE", "") or "")
        if mode not in ("MASTER", "PEER", "OPENBRIDGE"):
            continue
        ip = _first_cfg_str(sys_cfg, _OBP_LOCAL_KEYS)
        if _is_public_bind_ip(ip):
            found.add(ip)
    return sorted(found)


def _proxy_ufw_dest(listen_ip: str) -> str | None:
    ip = (listen_ip or "").strip()
    if not ip or ip in ("0.0.0.0", "::"):
        return None
    return ip


def merge_monitor_proxy_udp(
    udp_any: dict[str, set[int]],
    monitor_path: Path | None,
    *,
    proxy_udp_bindall: set[int],
    proxy_udp_ports: set[int],
    adn_cfg: dict[str, Any] | None,
) -> None:
    if monitor_path is None or not monitor_path.is_file():
        return
    try:
        data = yaml.safe_load(monitor_path.read_text(encoding="utf-8")) or {}
    except OSError as err:
        print(f"Warning: could not read monitor config {monitor_path}: {err}", file=sys.stderr)
        return
    proxy = data.get("PROXY") or data.get("proxy") or {}
    if not isinstance(proxy, dict):
        return
    raw_port = proxy.get("LISTEN_PORT", proxy.get("ListenPort"))
    try:
        port = int(raw_port) if raw_port is not None else 62031
    except (TypeError, ValueError):
        port = 62031
    listen_ip = str(proxy.get("LISTEN_IP") or proxy.get("ListenIP") or "").strip()
    dest = _proxy_ufw_dest(listen_ip)
    if dest is None and adn_cfg is not None:
        candidates = unique_public_bind_ips_from_systems(adn_cfg)
        if len(candidates) == 1:
            dest = candidates[0]
            print(
                f"Note: monitor PROXY LISTEN_PORT={port} — LISTEN_IP unset; using {dest}",
                file=sys.stderr,
            )
        elif len(candidates) > 1:
            proxy_udp_bindall.add(port)
            print(
                f"Warning: PROXY LISTEN_PORT={port} — several bind IPs; using UFW 'to any'.",
                file=sys.stderr,
            )
            return
    if dest is None:
        proxy_udp_bindall.add(port)
        print(
            f"Note: monitor PROXY LISTEN_PORT={port} — using UFW rule 'to any'.",
            file=sys.stderr,
        )
        return
    udp_any.setdefault(dest, set()).add(port)
    proxy_udp_ports.add(port)


def _env_port_list(name: str) -> list[int]:
    raw = (os.environ.get(name) or "").strip()
    ports: list[int] = []
    for part in raw.split():
        try:
            ports.append(int(part))
        except ValueError:
            print(f"Warning: ignore invalid port in {name}: {part!r}", file=sys.stderr)
    return ports


def _env_source_list(name: str) -> list[str]:
    raw = (os.environ.get(name) or "").strip()
    return [p for p in raw.split() if p.strip()]


def _run_ufw(settings: Settings | None, args: list[str], *, dry_run: bool) -> None:
    cmd = ["ufw", *args]
    if dry_run:
        print("+", " ".join(cmd))
        return
    run(settings, *cmd)


def _backup_ufw(stamp: str, dry_run: bool) -> None:
    backup_dir = Path("/etc/ufw")
    for name in _UFW_BACKUP_FILES:
        src = backup_dir / name
        if not src.is_file():
            continue
        dest = backup_dir / f"{name}.bak.{stamp}"
        if dry_run:
            print(f"+ cp -a {src} {dest}")
        else:
            shutil.copy2(src, dest, follow_symlinks=True)
            print(f"Backup: {dest}")


def rebuild_firewall(
    settings: Settings | None,
    *,
    server_cfg: Path,
    monitor_cfg: Path | None = None,
    ssh_port: int | None = None,
    dry_run: bool = False,
) -> None:
    cfg = settings or init_env()
    ssh_port = ssh_port or int(os.environ.get("SSH_PORT", "22"))
    if not server_cfg.is_file():
        raise FileNotFoundError(f"Config not found: {server_cfg}")

    data = yaml.safe_load(server_cfg.read_text(encoding="utf-8")) or {}
    udp_any, obp_udp_any, obp_udp = udp_rules_from_yaml(data)
    proxy_udp_bindall: set[int] = set()
    proxy_udp_ports: set[int] = set()
    if monitor_cfg and monitor_cfg.is_file():
        print(f">>> Monitor / proxy config: {monitor_cfg}")
        merge_monitor_proxy_udp(
            udp_any,
            monitor_cfg,
            proxy_udp_bindall=proxy_udp_bindall,
            proxy_udp_ports=proxy_udp_ports,
            adn_cfg=data,
        )

    host_rules: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"tcp": [], "udp": []})
    for ip, ports in udp_any.items():
        host_rules[ip]["udp"] = sorted(ports)

    any_tcp = sorted(set(_env_port_list("UFW_EXTRA_TCP")))
    any_udp = sorted(set(_env_port_list("UFW_EXTRA_UDP")))
    trusted = sorted(set(_env_source_list("UFW_TRUSTED_SOURCES")))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    print(">>> Backup UFW rule files")
    _backup_ufw(stamp, dry_run)
    print(">>> Reset (firewall disabled until enable — keep this SSH session open)")
    _run_ufw(cfg, ["--force", "reset"], dry_run=dry_run)
    _run_ufw(cfg, ["default", "deny", "incoming"], dry_run=dry_run)
    _run_ufw(cfg, ["default", "allow", "outgoing"], dry_run=dry_run)
    print(f">>> [Safety] SSH first — tcp/{ssh_port}")
    _run_ufw(
        cfg,
        ["allow", "in", "proto", "tcp", "to", "any", "port", str(ssh_port), "comment", "SSH"],
        dry_run=dry_run,
    )

    for ip in sorted(host_rules.keys()):
        buckets = host_rules[ip]
        print(f">>> {ip} — tcp, then udp from any")
        for p in buckets["tcp"]:
            _run_ufw(cfg, ["allow", "in", "proto", "tcp", "to", ip, "port", str(p), "from", "any"], dry_run=dry_run)
        for p in buckets["udp"]:
            cmd = ["allow", "in", "proto", "udp", "to", ip, "port", str(p), "from", "any"]
            if p in proxy_udp_ports:
                cmd.extend(["comment", _PROXY_UFW_COMMENT])
            _run_ufw(cfg, cmd, dry_run=dry_run)

    if obp_udp_any:
        print(">>> OBP — hostname peer: UDP from any")
        for dest_ip, port, label in obp_udp_any:
            _run_ufw(
                cfg,
                ["allow", "in", "proto", "udp", "from", "any", "to", dest_ip, "port", str(port), "comment", label],
                dry_run=dry_run,
            )

    if obp_udp:
        print(">>> OBP — fixed IPv4 peer")
        for dest_ip, port, peer_ip, label in obp_udp:
            _run_ufw(
                cfg,
                ["allow", "in", "proto", "udp", "from", peer_ip, "to", dest_ip, "port", str(port), "comment", label],
                dry_run=dry_run,
            )

    print(">>> to any — extra tcp, then udp")
    for p in any_tcp:
        _run_ufw(cfg, ["allow", "in", "proto", "tcp", "to", "any", "port", str(p), "from", "any"], dry_run=dry_run)
    for p in sorted(set(any_udp) | proxy_udp_bindall):
        cmd = ["allow", "in", "proto", "udp", "to", "any", "port", str(p), "from", "any"]
        if p in proxy_udp_bindall:
            cmd.extend(["comment", _PROXY_UFW_COMMENT])
        _run_ufw(cfg, cmd, dry_run=dry_run)

    if trusted:
        print(">>> trusted sources — full inbound")
        for src in trusted:
            _run_ufw(cfg, ["allow", "in", "from", src, "to", "any"], dry_run=dry_run)

    print(f">>> Enabling firewall (SSH tcp/{ssh_port} allowed)")
    _run_ufw(cfg, ["--force", "enable"], dry_run=dry_run)
    print(">>> Done. Open a second SSH session before closing this one.")
    if not dry_run:
        subprocess.run(["ufw", "status", "verbose"], check=False)
        subprocess.run(["ufw", "status", "numbered"], check=False)


def script_path(settings: Settings) -> Path | None:
    bundled = settings.adn_deploy_home / "scripts" / "ufw_rebuild_safe.py"
    if bundled.is_file():
        return bundled
    peer = settings.adn_dmr_server_path / "scripts" / "ufw_rebuild_safe.py"
    if peer.is_file():
        return peer
    legacy = Path("/opt/new-adn-server/scripts/ufw_rebuild_safe.py")
    if legacy.is_file():
        return legacy
    return None


def install_package(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.skip_os_packages or cfg.staging:
        print("  ufw: skipped (staging / no apt)")
        return True
    if shutil.which("ufw"):
        pass
    else:
        print("  ufw: installing package ...")
        run(cfg, "apt-get", "update", "-y")
        run(cfg, "apt-get", "install", "-y", "--no-install-recommends", "ufw")
    if cfg.ufw_enable != "1":
        print("  ufw: package installed; rules not applied (UFW_ENABLE=0)")
        return True
    print("  ufw: UFW_ENABLE=1 (apply rules from menu or: adn-deploy ufw rebuild --apply)")
    return True


def ufw_cmd(
    settings: Settings | None,
    action: str = "status",
    *,
    apply: bool = False,
    dry_run: bool = False,
) -> int:
    cfg = settings or init_env()
    if cfg.staging:
        print("ufw: not run in staging")
        return 0
    server_cfg = cfg.adn_dmr_server_path / "adn-server.yaml"
    mon_cfg = cfg.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    if action == "status":
        run(cfg, "ufw", "status", check=False)
        script = script_path(cfg)
        print(f"Script: {script or '(infra module)'}")
        print(f"Configs: {server_cfg} {mon_cfg}")
        return 0
    if action == "rebuild":
        if not server_cfg.is_file():
            print(f"adn-server.yaml not found: {server_cfg}", file=sys.stderr)
            return 1
        if apply and not dry_run and cfg.ufw_enable != "1":
            print("UFW_ENABLE is not 1 — enable in deploy.conf first", file=sys.stderr)
            return 1
        effective_dry = dry_run or (not apply)
        if is_dry_run(cfg):
            print(f"[dry-run] rebuild ufw dry_run={effective_dry}")
            return 0
        os.environ.setdefault("UFW_EXTRA_TCP", cfg.ufw_extra_tcp)
        os.environ.setdefault("UFW_EXTRA_UDP", cfg.ufw_extra_udp)
        os.environ.setdefault("UFW_TRUSTED_SOURCES", cfg.ufw_trusted_sources)
        rebuild_firewall(
            cfg,
            server_cfg=server_cfg,
            monitor_cfg=mon_cfg if mon_cfg.is_file() else None,
            dry_run=effective_dry,
        )
        return 0
    print("usage: ufw <status|rebuild> [--apply] [--dry-run]", file=sys.stderr)
    return 1
