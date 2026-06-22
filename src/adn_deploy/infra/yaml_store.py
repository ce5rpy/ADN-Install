"""Get/set dotted YAML keys and apply deploy override manifests."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    from ruamel.yaml import YAML
except ImportError:
    try:
        import yaml as _yaml

        class YAML:  # type: ignore[no-redef]
            def __init__(self) -> None:
                self.preserve_quotes = False

            def load(self, stream: Any) -> Any:
                return _yaml.safe_load(stream) or {}

            def dump(self, data: Any, stream: Any) -> None:
                _yaml.safe_dump(data, stream, default_flow_style=False, sort_keys=False)

    except ImportError as exc:
        raise ImportError("ruamel.yaml or PyYAML required") from exc


def loader() -> YAML:
    y = YAML()
    if hasattr(y, "preserve_quotes"):
        y.preserve_quotes = True
    if hasattr(y, "indent"):
        y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    y = loader()
    data = y.load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    y = loader()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        y.dump(data, f)


def get_path(root: dict[str, Any], dotted: str) -> Any:
    cur: Any = root
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_path(root: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = root
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def expand(s: str, env: dict[str, str]) -> str:
    out = s
    for key, val in env.items():
        out = out.replace("{" + key + "}", val)
    return out


def coerce_scalar_value(key: str, value: Any) -> Any:
    """Normalize CLI string values to YAML scalars (ENABLED booleans, numeric ports)."""
    if not isinstance(value, str):
        return value
    leaf = key.rsplit(".", 1)[-1]
    low = value.strip().lower()
    if leaf == "ENABLED":
        if low in ("true", "yes", "1", "on"):
            return True
        if low in ("false", "no", "0", "off"):
            return False
    if leaf in (
        "PORT",
        "DB_PORT",
        "TARGET_PORT",
        "MASTER_PORT",
        "NETWORK_ID",
        "GENERATOR",
        "MAX_PEERS",
        "PROTO_VER",
        "SERVER_ID",
        "REPORT_PORT",
        "LISTEN_PORT",
    ):
        if low.isdigit():
            return int(low)
    return value


def normalize_openbridge_block(block: dict[str, Any]) -> None:
    """Ensure OpenBridge blocks use typed scalars expected by adn-server."""
    block["MODE"] = "OPENBRIDGE"
    block["ENABLED"] = True
    for field in ("PORT", "TARGET_PORT", "NETWORK_ID", "PROTO_VER"):
        if field in block and block[field] is not None and block[field] != "":
            block[field] = int(block[field])


def parse_udp_port(label: str, raw: str) -> int:
    s = str(raw).strip()
    if not s.isdigit():
        raise ValueError(f"{label} must be a number (1-65535)")
    port = int(s)
    if port < 1 or port > 65535:
        raise ValueError(f"{label} out of range: {port}")
    return port


def value_preview(val: Any, max_len: int = 40) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return f"[{len(val)} items]"
    if isinstance(val, dict):
        return "{...}"
    s = str(val).replace("\n", " ")
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def iter_config_keys(
    root: dict[str, Any],
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 3,
) -> list[tuple[str, str, str]]:
    """Return (dotted_path, type, preview) for scalars and arrays up to max_depth."""
    out: list[tuple[str, str, str]] = []
    if not isinstance(root, dict):
        return out

    def walk(node: Any, path: str, d: int) -> None:
        if isinstance(node, dict):
            if d >= max_depth:
                return
            for key, val in node.items():
                child = f"{path}.{key}" if path else key
                if isinstance(val, dict):
                    walk(val, child, d + 1)
                elif isinstance(val, list):
                    out.append((child, "array", value_preview(val)))
                else:
                    out.append((child, "scalar", value_preview(val)))
        elif isinstance(node, list):
            out.append((path, "array", value_preview(node)))

    walk(root, prefix, depth)
    out.sort(key=lambda t: t[0].lower())
    return out


_PASSPHRASE_PLACEHOLDER_RE = re.compile(r"^<set-in-[^>]+>\s*$", re.IGNORECASE)


def passphrase_needs_normalize(val: Any) -> bool:
    """True when PASSPHRASE is empty or an example placeholder (not a deliberate secret)."""
    if val is None:
        return True
    if not isinstance(val, str):
        return False
    v = val.strip()
    if not v:
        return True
    return bool(_PASSPHRASE_PLACEHOLDER_RE.match(v))


def yaml_get(config: Path, key: str) -> Any:
    data = load_yaml(config)
    return get_path(data, key)


def yaml_set(config: Path, key: str, value: Any) -> None:
    data = load_yaml(config)
    set_path(data, key, coerce_scalar_value(key, value))
    save_yaml(config, data)


def add_obp_block(
    config: Path,
    *,
    block_name: str,
    template: Path,
    ip: str = "",
    port: str,
    target_ip: str,
    target_port: str,
    network_id: str,
    passphrase: str,
) -> None:
    data = load_yaml(config)
    systems = data.setdefault("SYSTEMS", {})
    if not isinstance(systems, dict):
        raise ValueError("SYSTEMS is not a mapping")
    name = block_name.strip()
    if not name:
        raise ValueError("block name is required")
    if name in systems:
        raise ValueError(f"block already exists: {name}")

    block = load_yaml(template)
    if not isinstance(block, dict):
        raise ValueError("template must be a YAML mapping")

    block.update(
        {
            "IP": ip.strip(),
            "PORT": parse_udp_port("Local port", port),
            "TARGET_IP": target_ip.strip(),
            "TARGET_PORT": parse_udp_port("Remote port", target_port),
            "NETWORK_ID": int(str(network_id).strip()),
            "PASSPHRASE": passphrase,
        }
    )
    normalize_openbridge_block(block)
    systems[name] = block
    save_yaml(config, data)


def add_system_block(config: Path, *, block_name: str, template: Path) -> None:
    data = load_yaml(config)
    systems = data.setdefault("SYSTEMS", {})
    if not isinstance(systems, dict):
        raise ValueError("SYSTEMS is not a mapping")
    if block_name in systems:
        raise ValueError(f"block already exists: {block_name}")
    block = load_yaml(template)
    if not isinstance(block, dict):
        raise ValueError("template must be a YAML mapping")
    if block.get("MODE") == "OPENBRIDGE":
        normalize_openbridge_block(block)
    systems[block_name] = block
    save_yaml(config, data)


def list_children(config: Path, prefix: str = "") -> list[tuple[str, str, str]]:
    data = load_yaml(config)
    if prefix:
        node = get_path(data, prefix)
        if not isinstance(node, dict):
            raise ValueError(f"prefix not a mapping: {prefix}")
    else:
        node = data
    rows: list[tuple[str, str, str]] = []
    for key, val in sorted(node.items(), key=lambda kv: str(kv[0]).lower()):
        if isinstance(val, dict):
            mode = val.get("MODE", "")
            preview = f"MODE={mode}" if mode else f"{len(val)} keys"
            kind = "block" if prefix == "SYSTEMS" else "section"
            rows.append((str(key), kind, str(preview)))
        elif isinstance(val, list):
            rows.append((str(key), "array", value_preview(val)))
        else:
            rows.append((str(key), "scalar", value_preview(val)))
    return rows


def list_keys(config: Path, *, prefix: str = "", max_depth: int = 3) -> list[tuple[str, str, str]]:
    data = load_yaml(config)
    if prefix:
        node = get_path(data, prefix)
        if not isinstance(node, dict):
            raise ValueError(f"prefix not a mapping: {prefix}")
        return iter_config_keys(node, prefix=prefix, depth=0, max_depth=max_depth)

    items: list[tuple[str, str, str]] = []
    for top_key, top_val in sorted(data.items(), key=lambda kv: str(kv[0]).lower()):
        if isinstance(top_val, dict):
            items.extend(
                iter_config_keys(
                    top_val,
                    prefix=str(top_key),
                    depth=0,
                    max_depth=max_depth,
                )
            )
        elif isinstance(top_val, list):
            items.append((str(top_key), "array", value_preview(top_val)))
        else:
            items.append((str(top_key), "scalar", value_preview(top_val)))
    return items


def normalize_passphrases(config: Path, value: str = "passw0rd") -> int:
    data = load_yaml(config)
    systems = data.get("SYSTEMS")
    changed = 0
    if isinstance(systems, dict):
        for block in systems.values():
            if isinstance(block, dict) and "PASSPHRASE" in block:
                if passphrase_needs_normalize(block.get("PASSPHRASE")):
                    if block.get("PASSPHRASE") != value:
                        block["PASSPHRASE"] = value
                        changed += 1
    if changed:
        save_yaml(config, data)
    return changed


def sync_echo_passphrase(server: Path, echo: Path) -> bool:
    if not echo.exists():
        raise FileNotFoundError(f"skip (missing): {echo}")
    server_cfg = load_yaml(server)
    echo_cfg = load_yaml(echo)
    systems = server_cfg.get("SYSTEMS")
    echo_master = systems.get("ECHO") if isinstance(systems, dict) else None
    if not isinstance(echo_master, dict):
        raise ValueError("ECHO system missing in server config")
    passphrase = echo_master.get("PASSPHRASE")
    if passphrase_needs_normalize(passphrase):
        raise ValueError(
            "ECHO.PASSPHRASE missing or still a placeholder — run normalize on adn-server.yaml first"
        )
    e_systems = echo_cfg.get("SYSTEMS")
    echo_block = e_systems.get("ECHO") if isinstance(e_systems, dict) else None
    if not isinstance(echo_block, dict):
        raise ValueError("ECHO system missing in echo config")
    if echo_block.get("PASSPHRASE") != passphrase:
        echo_block["PASSPHRASE"] = passphrase
        save_yaml(echo, echo_cfg)
        return True
    return False


def apply_overrides(
    manifest: Path,
    *,
    variables: dict[str, str] | None = None,
    filter_path: Path | None = None,
) -> list[Path]:
    manifest_data = load_yaml(manifest)
    env: dict[str, str] = dict(variables or {})
    for k, v in os.environ.items():
        if k.startswith("ADN_") or k in ("ADN_ROOT",):
            env.setdefault(k, v)

    applied: list[Path] = []
    for target in manifest_data.get("targets") or []:
        raw_path = expand(str(target.get("path", "")), env)
        if not raw_path:
            continue
        cfg = Path(raw_path)
        if filter_path is not None and cfg.resolve() != filter_path.resolve():
            continue
        if not cfg.exists():
            continue
        data = load_yaml(cfg)
        for dotted, value in (target.get("sets") or {}).items():
            val = expand(value, env) if isinstance(value, str) else value
            set_path(data, str(dotted), coerce_scalar_value(str(dotted), val))
        save_yaml(cfg, data)
        applied.append(cfg)
    return applied


def cmd_get(args: argparse.Namespace) -> None:
    val = yaml_get(Path(args.config), args.key)
    if val is None:
        sys.exit(2)
    if isinstance(val, (dict, list)):
        print(repr(val))
    else:
        print(val)


def cmd_set(args: argparse.Namespace) -> None:
    yaml_set(Path(args.config), args.key, args.value)
    print(f"set {args.key} in {args.config}")


def cmd_add_obp_block(args: argparse.Namespace) -> None:
    add_obp_block(
        Path(args.config),
        block_name=args.block_name,
        template=Path(args.template),
        ip=args.ip,
        port=args.port,
        target_ip=args.target_ip,
        target_port=args.target_port,
        network_id=args.network_id,
        passphrase=args.passphrase,
    )
    print(f"added OpenBridge SYSTEMS.{args.block_name}")


def cmd_add_system_block(args: argparse.Namespace) -> None:
    add_system_block(
        Path(args.config),
        block_name=args.block_name,
        template=Path(args.template),
    )
    print(f"added SYSTEMS.{args.block_name} from {args.template}")


def cmd_list_children(args: argparse.Namespace) -> None:
    for key, kind, preview in list_children(Path(args.config), args.prefix):
        print(f"{key}|{kind}|{preview}")


def cmd_list_keys(args: argparse.Namespace) -> None:
    for path, kind, preview in list_keys(
        Path(args.config),
        prefix=args.prefix,
        max_depth=int(args.max_depth),
    ):
        print(f"{path}|{kind}|{preview}")


def cmd_normalize_passphrases(args: argparse.Namespace) -> None:
    changed = normalize_passphrases(Path(args.config), args.value)
    print(f"normalize PASSPHRASE: {changed} block(s) -> {args.value}")


def cmd_sync_echo_passphrase(args: argparse.Namespace) -> None:
    changed = sync_echo_passphrase(Path(args.server), Path(args.echo))
    if changed:
        print("sync SYSTEMS.ECHO.PASSPHRASE -> server ECHO")
    else:
        print("sync SYSTEMS.ECHO.PASSPHRASE: already matches server ECHO")


def cmd_apply(args: argparse.Namespace) -> None:
    vars_map: dict[str, str] = {}
    for item in args.var or []:
        if "=" in item:
            k, v = item.split("=", 1)
            vars_map[k] = v
    filter_path = Path(args.filter_path).resolve() if args.filter_path else None
    for cfg in apply_overrides(Path(args.manifest), variables=vars_map, filter_path=filter_path):
        print(f"applied overrides: {cfg}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="ADN deploy YAML scalar helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get")
    g.add_argument("--config", required=True)
    g.add_argument("--key", required=True)

    s = sub.add_parser("set")
    s.add_argument("--config", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--value", required=True)

    a = sub.add_parser("apply")
    a.add_argument("--manifest", required=True)
    a.add_argument("--var", action="append", default=[])
    a.add_argument("--filter-path", default="", help="apply only to this config file path")

    lk = sub.add_parser("list-keys")
    lk.add_argument("--config", required=True)
    lk.add_argument("--prefix", default="", help="dotted path to a mapping section")
    lk.add_argument("--max-depth", default="3", help="max nesting depth under prefix")

    lc = sub.add_parser("list-children")
    lc.add_argument("--config", required=True)
    lc.add_argument("--prefix", default="", help="dotted path; empty = top-level sections")

    ab = sub.add_parser("add-system-block")
    ab.add_argument("--config", required=True)
    ab.add_argument("--block-name", required=True)
    ab.add_argument("--template", required=True)

    obp = sub.add_parser("add-obp-block")
    obp.add_argument("--config", required=True)
    obp.add_argument("--block-name", required=True)
    obp.add_argument("--template", required=True)
    obp.add_argument("--ip", default="")
    obp.add_argument("--port", required=True)
    obp.add_argument("--target-ip", required=True)
    obp.add_argument("--target-port", required=True)
    obp.add_argument("--network-id", required=True)
    obp.add_argument("--passphrase", required=True)

    np = sub.add_parser("normalize-passphrases")
    np.add_argument("--config", required=True)
    np.add_argument("--value", default="passw0rd")

    sp = sub.add_parser("sync-echo-passphrase")
    sp.add_argument("--server", required=True, help="adn-server.yaml path")
    sp.add_argument("--echo", required=True, help="adn-echo.yaml path")

    args = p.parse_args(argv)
    handlers = {
        "get": cmd_get,
        "set": cmd_set,
        "list-keys": cmd_list_keys,
        "list-children": cmd_list_children,
        "add-system-block": cmd_add_system_block,
        "add-obp-block": cmd_add_obp_block,
        "normalize-passphrases": cmd_normalize_passphrases,
        "sync-echo-passphrase": cmd_sync_echo_passphrase,
        "apply": cmd_apply,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
