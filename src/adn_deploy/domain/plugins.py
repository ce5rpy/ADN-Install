"""Plugin engine: YAML manifests, topological order, enabled state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from adn_deploy.core.paths import plugins_enabled_state


@dataclass
class PluginInfo:
    id: str
    depends_on: list[str] = field(default_factory=list)
    group: str = ""
    enabled_by_default: bool = True
    profiles: list[str] = field(default_factory=lambda: ["minimal", "full"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "depends_on": self.depends_on,
            "group": self.group,
            "enabled_by_default": self.enabled_by_default,
            "profiles": self.profiles,
        }


def load_plugin(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid plugin file: {path}")
    return data


def list_plugins(plugins_dir: Path, profile: str = "full") -> list[PluginInfo]:
    out: list[PluginInfo] = []
    for path in sorted(plugins_dir.glob("*.yaml")):
        data = load_plugin(path)
        pid = str(data.get("id") or path.stem)
        group = str(data.get("group") or "")
        enabled = bool(data.get("enabled_by_default", True))
        profiles = list(data.get("profiles") or ["minimal", "full"])

        if profile == "minimal":
            if "minimal" not in profiles:
                continue
            if group in ("web", "optional"):
                continue

        out.append(
            PluginInfo(
                id=pid,
                depends_on=list(data.get("depends_on") or []),
                group=group,
                enabled_by_default=enabled,
                profiles=profiles,
            )
        )
    return out


def topo_sort(items: list[PluginInfo] | list[dict[str, Any]]) -> list[str]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, PluginInfo):
            by_id[item.id] = item.to_dict()
        else:
            by_id[str(item["id"])] = item

    order: list[str] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(nid: str) -> None:
        if nid in seen:
            return
        if nid in visiting:
            raise ValueError(f"plugin cycle at {nid}")
        visiting.add(nid)
        for dep in by_id.get(nid, {}).get("depends_on") or []:
            if dep in by_id:
                visit(dep)
        visiting.remove(nid)
        seen.add(nid)
        order.append(nid)

    for item in items:
        pid = item.id if isinstance(item, PluginInfo) else str(item["id"])
        visit(pid)
    return order


def topo_order(plugins_dir: Path, profile: str = "full") -> list[str]:
    return topo_sort(list_plugins(plugins_dir, profile))


def plugin_get(plugins_dir: Path, plugin_id: str, key: str) -> Any:
    path = plugins_dir / f"{plugin_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(plugin_id)
    data = load_plugin(path)
    val: Any = data
    for part in key.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    return val


def enabled_state_path(adn_root: Path) -> Path:
    return plugins_enabled_state(adn_root)


def _read_state_lines(state_file: Path) -> list[str]:
    if not state_file.is_file():
        return []
    return [line.strip() for line in state_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def set_plugin_enabled(adn_root: Path, plugin_id: str, enabled: bool) -> None:
    state = enabled_state_path(adn_root)
    state.parent.mkdir(parents=True, exist_ok=True)
    lines = [ln for ln in _read_state_lines(state) if ln not in (plugin_id, f"!{plugin_id}")]
    lines.append(plugin_id if enabled else f"!{plugin_id}")
    state.write_text("\n".join(sorted(set(lines))) + "\n", encoding="utf-8")


def is_plugin_enabled(
    plugins_dir: Path,
    adn_root: Path,
    plugin_id: str,
) -> bool:
    state = enabled_state_path(adn_root)
    if state.is_file():
        lines = _read_state_lines(state)
        if plugin_id in lines:
            return True
        if f"!{plugin_id}" in lines:
            return False

    default = plugin_get(plugins_dir, plugin_id, "enabled_by_default")
    if default is None:
        return True
    if isinstance(default, bool):
        return default
    return str(default).lower() not in ("false", "0")


def plugin_peer_stack_enabled(plugins_dir: Path, adn_root: Path) -> bool:
    return is_plugin_enabled(plugins_dir, adn_root, "adn-server") or is_plugin_enabled(
        plugins_dir, adn_root, "adn-echo"
    )


def list_plugins_json(plugins_dir: Path, profile: str = "full") -> str:
    return json.dumps([p.to_dict() for p in list_plugins(plugins_dir, profile)])


def topo_order_json(plugins_dir: Path, profile: str = "full", items_json: str | None = None) -> str:
    if items_json:
        raw = json.loads(items_json or "[]")
    else:
        raw = [p.to_dict() for p in list_plugins(plugins_dir, profile)]
    return json.dumps(topo_sort(raw))
