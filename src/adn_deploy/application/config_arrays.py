"""Dashboard nav_links / footer / news array editor."""

from __future__ import annotations

from pathlib import Path

from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.paths import monitor_arrays_schema
from adn_deploy.infra import yaml_arrays


def monitor_config(settings: Settings) -> Path:
    return settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"


def schema_path(settings: Settings) -> Path:
    return monitor_arrays_schema(settings.adn_deploy_home)


def list_items(settings: Settings, collection: str) -> list[tuple[int, str, str]]:
    return yaml_arrays.list_items(
        schema_path(settings),
        monitor_config(settings),
        collection,
    )


def count(settings: Settings, collection: str) -> int:
    return len(list_items(settings, collection))


def add_link(
    settings: Settings,
    collection: str,
    name: str,
    url: str = "",
) -> None:
    yaml_arrays.add_item(
        schema_path(settings),
        monitor_config(settings),
        collection,
        name=name,
        url=url,
    )


def edit_link(
    settings: Settings,
    collection: str,
    index: int,
    name: str,
    url: str = "",
) -> None:
    yaml_arrays.edit_item(
        schema_path(settings),
        monitor_config(settings),
        collection,
        index=index,
        name=name,
        url=url,
    )


def delete_link(settings: Settings, collection: str, index: int) -> None:
    yaml_arrays.delete_item(
        schema_path(settings),
        monitor_config(settings),
        collection,
        index=index,
    )


def get_parent_title(settings: Settings, collection: str = "nav_links") -> str:
    return yaml_arrays.get_parent_field(
        schema_path(settings),
        monitor_config(settings),
        collection,
    )


def set_parent_title(settings: Settings, value: str, collection: str = "nav_links") -> None:
    yaml_arrays.set_parent_field(
        schema_path(settings),
        monitor_config(settings),
        collection,
        value=value,
    )


def arrays_cmd(
    settings: Settings | None,
    action: str,
    *,
    collection: str = "nav_links",
    name: str = "",
    url: str = "",
    index: str = "",
    value: str = "",
) -> int:
    cfg = settings or init_env()
    schema = schema_path(cfg)
    config = monitor_config(cfg)
    if action == "list":
        for idx, n, u in yaml_arrays.list_items(schema, config, collection):
            print(f"{idx}\t{n}\t{u}")
        return 0
    if action == "add":
        yaml_arrays.add_item(schema, config, collection, name=name, url=url)
        return 0
    if action == "edit":
        yaml_arrays.edit_item(schema, config, collection, index=int(index), name=name, url=url)
        return 0
    if action == "delete":
        yaml_arrays.delete_item(schema, config, collection, index=int(index))
        return 0
    if action == "get-parent":
        print(get_parent_title(cfg, collection))
        return 0
    if action == "set-parent":
        set_parent_title(cfg, value, collection)
        return 0
    print("usage: config arrays <list|add|edit|delete|get-parent|set-parent>", file=__import__("sys").stderr)
    return 1
