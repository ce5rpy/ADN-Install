"""YAML / deploy.conf configuration menus."""

from __future__ import annotations

from adn_deploy.application import config as app_config
from adn_deploy.application.config_schema import COMMON_VARS, SERVICE_LABELS
from adn_deploy.core.env import Settings
from adn_deploy.infra import yaml_store
from adn_deploy.ui.external_editor import run_external_editor
from adn_deploy.ui.screens.link_editor import LinkEditorScreen
from adn_deploy.ui.run_capture import capture_call
from adn_deploy.ui.widgets import InputScreen, MenuEntry, MenuScreen, OutputScreen


class ConfigMenuScreen(MenuScreen):
    def __init__(self, settings: Settings, service_id: str) -> None:
        self.settings = settings
        self.service_id = service_id
        label = SERVICE_LABELS.get(service_id, service_id)
        entries = [
            MenuEntry("vars", "Change a variable"),
            MenuEntry("nano", "Edit full file (editor)"),
        ]
        if service_id == "adn-monitor":
            entries.extend(
                [
                    MenuEntry("nav_links", "Top links"),
                    MenuEntry("footer", "Footer links"),
                    MenuEntry("news", "News"),
                ]
            )
        entries.append(MenuEntry("back", "Back"))
        if settings.docker:
            if service_id == "daprs":
                subtitle = "gps_data.cfg — restart container after saving"
            else:
                subtitle = "YAML / deploy.conf — restart container after saving"
        elif service_id == "daprs":
            subtitle = "deploy.conf + gps_data.cfg"
        else:
            subtitle = "YAML variables or full-file editor"
        super().__init__(f"Configure — {label}", subtitle, entries)

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        if action_id == "nano":
            try:
                path = app_config.service_file(self.settings, self.service_id)
            except ValueError as exc:
                self.app.push_screen(OutputScreen("Configure", str(exc)))
                return
            run_external_editor(self.app, path)
            return
        if action_id in ("nav_links", "footer", "news"):
            self.app.push_screen(LinkEditorScreen(self.settings, action_id))
            return
        if action_id == "vars":
            self.app.push_screen(VarPickerScreen(self.settings, self.service_id))


class VarPickerScreen(MenuScreen):
    def __init__(self, settings: Settings, service_id: str) -> None:
        self.settings = settings
        self.service_id = service_id
        entries = [
            MenuEntry(meta.key, f"{meta.label} ({meta.key})")
            for meta in COMMON_VARS.get(service_id, [])
        ]
        entries.append(MenuEntry("back", "Back"))
        super().__init__("Variable", "Choose a key to edit", entries)

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        self.app.push_screen(VarEditScreen(self.settings, self.service_id, action_id))


class VarEditScreen(InputScreen):
    def __init__(self, settings: Settings, service_id: str, key: str) -> None:
        self.settings = settings
        self.service_id = service_id
        self.key = key
        meta = next((m for m in COMMON_VARS.get(service_id, []) if m.key == key), None)
        label = meta.label if meta else key
        default = ""
        hint = meta.hint if meta else ""
        if service_id == "daprs":
            default = app_config.get_daprs_setting(settings, key) or hint
        else:
            try:
                path = app_config.service_file(settings, service_id)
                if path.is_file():
                    val = yaml_store.yaml_get(path, key)
                    default = str(val) if val is not None else hint
            except (ValueError, OSError):
                default = hint
        super().__init__(label, key, default or hint)

    def on_button_pressed(self, event) -> None:
        from textual.widgets import Button, Input

        if not isinstance(event, Button.Pressed):
            return
        if event.button.id == "cancel":
            self.action_cancel()
            return
        value = self.query_one("#value", Input).value.strip()
        if not value:
            self.app.notify("Value required", severity="error")
            return
        if self.service_id == "daprs":
            _, rc, _ = capture_call(
                lambda: app_config.set_cmd(self.settings, self.service_id, self.key, value)
            )
            if rc != 0:
                self.app.notify("Invalid value", severity="error")
                return
        else:
            app_config.set_cmd(self.settings, self.service_id, self.key, value)
        self.app.pop_screen()
        self.app.notify("Saved")
