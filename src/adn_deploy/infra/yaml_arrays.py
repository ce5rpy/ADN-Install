"""CRUD for DASHBOARD link lists (nav_links, footer, news) in adn-monitor.yaml."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
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


def yaml_loader() -> YAML:
    y = YAML()
    if hasattr(y, "preserve_quotes"):
        y.preserve_quotes = True
    if hasattr(y, "indent"):
        y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_schema(path: Path) -> dict[str, Any]:
    return yaml_loader().load(path.read_text(encoding="utf-8")) or {}


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml_loader().load(path.read_text(encoding="utf-8")) or {}


def plain_item(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {"name": str(raw)}
    out: dict[str, str] = {"name": str(raw.get("name", ""))}
    if raw.get("url"):
        out["url"] = str(raw["url"])
    return out


def normalize_dashboard_links(dash: Any) -> None:
    """Rebuild nav_links/footer/news as plain dicts so ruamel does not append items under wrong keys."""
    if not isinstance(dash, dict):
        return
    nl = dash.get("nav_links")
    nl_items: list[Any] = []
    nl_name = "Links"
    if isinstance(nl, dict):
        nl_name = str(nl.get("name") or nl_name)
        nl_items = [plain_item(x) for x in (nl.get("items") or []) if isinstance(x, dict) or x]
    dash["nav_links"] = {"name": nl_name, "items": nl_items}

    for cid in ("footer", "news"):
        block = dash.get(cid)
        items: list[Any] = []
        if isinstance(block, dict):
            items = [plain_item(x) for x in (block.get("items") or []) if isinstance(x, dict) or x]
        elif isinstance(block, list):
            items = [plain_item(x) for x in block]
        dash[cid] = {"items": items}


def save_config(path: Path, data: dict[str, Any]) -> None:
    backup = path.with_suffix(path.suffix + f".bak.{datetime.now():%Y%m%d%H%M%S}")
    if path.exists():
        shutil.copy2(path, backup)
    if os.environ.get("ADN_DEPLOY_VERBOSE") == "1":
        print(f"backup: {backup}", file=sys.stderr)
    dash = data.get("DASHBOARD")
    if isinstance(dash, dict):
        normalize_dashboard_links(dash)
    y = yaml_loader()
    with path.open("w", encoding="utf-8") as f:
        y.dump(data, f)


def get_collection(schema: dict[str, Any], coll_id: str) -> dict[str, Any]:
    for c in schema.get("collections", []):
        if c.get("id") == coll_id:
            return c
    raise ValueError(f"unknown collection: {coll_id}")


def collection_block(dash: dict[str, Any], coll_id: str, *, create: bool = False) -> dict[str, Any] | None:
    """Return the parent block (nav_links / footer / news), matching adn-monitor.yaml.example."""
    if not isinstance(dash, dict):
        return None
    block = dash.get(coll_id)
    if block is None and create:
        block = {}
        dash[coll_id] = block
    if block is None:
        return None
    if not isinstance(block, dict):
        block = {}
        dash[coll_id] = block
    return block


def get_items_list(dash: dict[str, Any], coll: dict[str, Any]) -> list[Any]:
    coll_id = coll["id"]
    block = collection_block(dash, coll_id, create=False)
    if not block:
        return []
    items = block.get("items")
    return items if isinstance(items, list) else []


def ensure_items_list(dash: dict[str, Any], coll: dict[str, Any]) -> list[Any]:
    coll_id = coll["id"]
    block = collection_block(dash, coll_id, create=True)
    assert block is not None
    if coll_id == "nav_links":
        block.setdefault("name", "Links")
    items = block.get("items")
    if not isinstance(items, list):
        items = []
        block["items"] = items
    return items


def parent_field_set(dash: dict[str, Any], coll: dict[str, Any], field_path: str, value: str) -> None:
    block = collection_block(dash, coll["id"], create=True)
    assert block is not None
    key = field_path.split(".")[-1]
    block[key] = value


def parent_field_get(dash: dict[str, Any], coll: dict[str, Any], field_path: str) -> str:
    block = collection_block(dash, coll["id"], create=False)
    if not block:
        return ""
    key = field_path.split(".")[-1]
    val = block.get(key, "")
    return "" if val is None else str(val)


def list_items(schema_path: Path, config_path: Path, collection_id: str) -> list[tuple[int, str, str]]:
    schema = load_schema(schema_path)
    data = load_config(config_path)
    coll = get_collection(schema, collection_id)
    dash = data.get(schema.get("root_key", "DASHBOARD"), {})
    rows: list[tuple[int, str, str]] = []
    for i, it in enumerate(get_items_list(dash, coll)):
        if isinstance(it, dict):
            rows.append((i, str(it.get("name", "")), str(it.get("url", ""))))
        else:
            rows.append((i, str(it), ""))
    return rows


def add_item(
    schema_path: Path,
    config_path: Path,
    collection_id: str,
    *,
    name: str,
    url: str = "",
) -> None:
    schema = load_schema(schema_path)
    data = load_config(config_path)
    root_key = schema.get("root_key", "DASHBOARD")
    dash = data.setdefault(root_key, {})
    normalize_dashboard_links(dash)
    coll = get_collection(schema, collection_id)
    items = ensure_items_list(dash, coll)
    entry: dict[str, Any] = {"name": name}
    if url:
        entry["url"] = url
    items.append(entry)
    save_config(config_path, data)


def edit_item(
    schema_path: Path,
    config_path: Path,
    collection_id: str,
    *,
    index: int,
    name: str,
    url: str = "",
) -> None:
    schema = load_schema(schema_path)
    data = load_config(config_path)
    root_key = schema.get("root_key", "DASHBOARD")
    dash = data.setdefault(root_key, {})
    normalize_dashboard_links(dash)
    coll = get_collection(schema, collection_id)
    items = ensure_items_list(dash, coll)
    if index < 0 or index >= len(items):
        raise IndexError("index out of range")
    entry: dict[str, Any] = {"name": name}
    if url:
        entry["url"] = url
    elif isinstance(items[index], dict) and items[index].get("url"):
        entry["url"] = items[index]["url"]
    items[index] = entry
    save_config(config_path, data)


def delete_item(
    schema_path: Path,
    config_path: Path,
    collection_id: str,
    *,
    index: int,
) -> None:
    schema = load_schema(schema_path)
    data = load_config(config_path)
    root_key = schema.get("root_key", "DASHBOARD")
    dash = data.setdefault(root_key, {})
    normalize_dashboard_links(dash)
    coll = get_collection(schema, collection_id)
    items = ensure_items_list(dash, coll)
    if 0 <= index < len(items):
        items.pop(index)
        save_config(config_path, data)
    else:
        raise IndexError("index out of range")


def get_parent_field(schema_path: Path, config_path: Path, collection_id: str) -> str:
    schema = load_schema(schema_path)
    data = load_config(config_path)
    coll = get_collection(schema, collection_id)
    dash = data.get(schema.get("root_key", "DASHBOARD"), {})
    for pf in coll.get("parent_fields") or []:
        path = pf.get("path", "")
        if path:
            return parent_field_get(dash, coll, path)
    raise LookupError("no parent field for collection")


def set_parent_field(
    schema_path: Path,
    config_path: Path,
    collection_id: str,
    *,
    value: str,
) -> None:
    schema = load_schema(schema_path)
    data = load_config(config_path)
    root_key = schema.get("root_key", "DASHBOARD")
    dash = data.setdefault(root_key, {})
    normalize_dashboard_links(dash)
    coll = get_collection(schema, collection_id)
    for pf in coll.get("parent_fields") or []:
        path = pf.get("path", "")
        if path:
            parent_field_set(dash, coll, path, value)
            save_config(config_path, data)
            return
    raise LookupError("no parent field for collection")


def cmd_list(args: argparse.Namespace) -> None:
    for i, name, url in list_items(Path(args.schema), Path(args.config), args.collection):
        print(f"{i}\t{name}\t{url}")


def cmd_add(args: argparse.Namespace) -> None:
    add_item(
        Path(args.schema),
        Path(args.config),
        args.collection,
        name=args.name,
        url=args.url,
    )


def cmd_edit(args: argparse.Namespace) -> None:
    edit_item(
        Path(args.schema),
        Path(args.config),
        args.collection,
        index=int(args.index),
        name=args.name,
        url=args.url,
    )


def cmd_delete(args: argparse.Namespace) -> None:
    delete_item(
        Path(args.schema),
        Path(args.config),
        args.collection,
        index=int(args.index),
    )


def cmd_get_parent(args: argparse.Namespace) -> None:
    print(get_parent_field(Path(args.schema), Path(args.config), args.collection))


def cmd_set_parent(args: argparse.Namespace) -> None:
    set_parent_field(
        Path(args.schema),
        Path(args.config),
        args.collection,
        value=args.value,
    )


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="ADN deploy YAML array helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, extra in (
        ("list", []),
        ("add", [("--name", {"required": True}), ("--url", {"default": ""})]),
        ("edit", [("--index", {"required": True}), ("--name", {"required": True}), ("--url", {"default": ""})]),
        ("delete", [("--index", {"required": True})]),
        ("get-parent", []),
        ("set-parent", [("--value", {"required": True})]),
    ):
        sp = sub.add_parser(name)
        sp.add_argument("--schema", required=True)
        sp.add_argument("--config", required=True)
        sp.add_argument("--collection", required=True)
        for arg, kwargs in extra:
            sp.add_argument(arg, **kwargs)

    args = p.parse_args(argv)
    handlers = {
        "list": cmd_list,
        "add": cmd_add,
        "edit": cmd_edit,
        "delete": cmd_delete,
        "get-parent": cmd_get_parent,
        "set-parent": cmd_set_parent,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
