"""Main ADN-Deploy menu."""

from __future__ import annotations

from adn_deploy.application import update as app_update
from adn_deploy.application.config_schema import SERVICE_LABELS
from adn_deploy.core.env import Settings
from adn_deploy.ui.run_capture import capture_output
from adn_deploy.ui.widgets import OutputScreen
from adn_deploy.domain.plugins import is_plugin_enabled
from adn_deploy.ui.screens.config_menu import ConfigMenuScreen
from adn_deploy.ui.screens.deploy_conf import DeployConfScreen
from adn_deploy.ui.screens.service_menu import ServiceMenuScreen
from adn_deploy.ui.screens.web_menu import WebMenuScreen
from adn_deploy.ui.widgets import MenuEntry, MenuScreen


class MainMenuScreen(MenuScreen):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        entries = [
            MenuEntry("adn-server", SERVICE_LABELS["adn-server"]),
            MenuEntry("adn-monitor", SERVICE_LABELS["adn-monitor"]),
            MenuEntry("adn-echo", SERVICE_LABELS["adn-echo"]),
        ]
        if is_plugin_enabled(settings.paths.plugins, settings.adn_root, "daprs"):
            entries.append(MenuEntry("daprs", SERVICE_LABELS["daprs"]))
        if settings.docker:
            web_label = "Traefik / HTTPS"
            menu_title = "ADN Docker"
            menu_subtitle = "Configure services and restart containers"
        else:
            web_label = "Web panel / Nginx and TLS"
            menu_title = "ADN-Deploy"
            menu_subtitle = "Main menu — choose a service or setting"
        entries.extend(
            [
                MenuEntry("web", web_label),
                MenuEntry("deploy", "General settings (deploy.conf)"),
            ]
        )
        if not settings.docker:
            entries.extend(
                [
                    MenuEntry("update-toolkit", "Update ADN-Deploy (git pull + pip)"),
                    MenuEntry("update-all", "Update all (toolkit + apps)"),
                ]
            )
        entries.append(MenuEntry("exit", "Exit"))
        super().__init__(menu_title, menu_subtitle, entries, show_back=False)

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "exit":
            self.app.exit()
            return
        if action_id == "web":
            self.app.push_screen(WebMenuScreen(self.settings))
            return
        if action_id == "deploy":
            self.app.push_screen(DeployConfScreen(self.settings))
            return
        if action_id == "update-toolkit":
            text, _ = capture_output(lambda: app_update.update_deploy_toolkit(self.settings))
            self.app.push_screen(OutputScreen("Update ADN-Deploy", text))
            return
        if action_id == "update-all":
            text, _ = capture_output(lambda: app_update.run(self.settings))
            self.app.push_screen(OutputScreen("Update all", text))
            return
        if action_id in SERVICE_LABELS:
            self.app.push_screen(ServiceMenuScreen(self.settings, action_id))
            return
        if action_id == "configure":
            self.app.push_screen(ConfigMenuScreen(self.settings, "adn-monitor"))
