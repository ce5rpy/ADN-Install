"""Per-service actions menu."""

from __future__ import annotations

from adn_deploy.application import config as app_config
from adn_deploy.application import update as app_update
from adn_deploy.application.config_schema import SERVICE_LABELS, service_unit
from adn_deploy.core.env import Settings
from adn_deploy.infra import os_bootstrap
from adn_deploy.infra import systemd
from adn_deploy.ui.screens.config_menu import ConfigMenuScreen
from adn_deploy.ui.run_capture import capture_call, capture_output
from adn_deploy.ui.widgets import MenuEntry, MenuScreen, OutputScreen


def service_menu_entries(settings: Settings) -> list[MenuEntry]:
    if settings.docker:
        return [
            MenuEntry("configure", "Configure"),
            MenuEntry("restart", "Restart container"),
            MenuEntry("back", "Back to main menu"),
        ]
    return [
        MenuEntry("configure", "Configure"),
        MenuEntry("restart", "Restart"),
        MenuEntry("stop", "Stop"),
        MenuEntry("start", "Start"),
        MenuEntry("update", "Update (git + dependencies)"),
        MenuEntry("pip", "Reinstall Python dependencies"),
        MenuEntry("back", "Back to main menu"),
    ]


class ServiceMenuScreen(MenuScreen):
    def __init__(self, settings: Settings, service_id: str) -> None:
        self.settings = settings
        self.service_id = service_id
        unit = service_unit(service_id)
        label = SERVICE_LABELS[service_id]
        if settings.docker:
            subtitle = f"Container {unit} — edit config, then restart to apply"
        else:
            subtitle = f"Actions for {unit}.service"
        super().__init__(label, subtitle, service_menu_entries(settings))

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        if action_id == "configure":
            self.app.push_screen(ConfigMenuScreen(self.settings, self.service_id))
            return
        unit = service_unit(self.service_id)
        if action_id in ("restart", "stop", "start"):
            if self.settings.docker and action_id == "restart":
                capture_call(lambda: app_config.sync_docker_wizard_config(self.settings))
            rc = systemd.services_cmd(self.settings, action_id, unit)
            msg = systemd.service_action_message(
                action_id, unit, rc, docker=self.settings.docker
            )
            if self.settings.docker:
                title = {
                    "restart": "Container restarted",
                }.get(action_id, f"Container — {action_id}")
            else:
                title = {
                    "start": "Service started",
                    "stop": "Service stopped",
                    "restart": "Service restarted",
                }.get(action_id, f"Service — {action_id}")
            self.app.push_screen(OutputScreen(title, msg))
            return
        if action_id == "pip":
            def _pip() -> bool:
                if self.settings.docker:
                    return True
                if self.service_id in ("adn-server", "adn-echo"):
                    return os_bootstrap.pip_peer(self.settings)
                if self.service_id == "adn-monitor":
                    return os_bootstrap.pip_monitor(self.settings)
                if self.service_id == "daprs":
                    return os_bootstrap.pip_daprs(self.settings)
                return False

            _, _, ok = capture_call(_pip)
            ok = bool(ok)
            if self.settings.docker:
                msg = f"pip skipped in Docker mode ({unit} uses container images)."
            elif ok:
                msg = f"Python dependencies reinstalled for {unit}."
            else:
                msg = f"pip install failed for {unit}."
            self.app.push_screen(OutputScreen("pip", msg))
            return
        if action_id == "update":
            capture_output(lambda: app_update.update_one(self.settings, self.service_id))
            rc = systemd.services_cmd(self.settings, "restart", unit)
            if rc == 0:
                msg = f"{unit} updated and restarted successfully."
            else:
                msg = (
                    f"{unit} updated but restart failed.\n\n"
                    f"{systemd.service_action_message('restart', unit, rc)}"
                )
            self.app.push_screen(OutputScreen("Update", msg))
