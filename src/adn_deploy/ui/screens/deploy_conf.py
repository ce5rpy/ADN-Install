"""General settings (deploy.conf) menu."""

from __future__ import annotations

from adn_deploy.application import config as app_config
from adn_deploy.application import doctor
from adn_deploy.application import install as app_install
from adn_deploy.application import update as app_update
from adn_deploy.application.config_schema import COMMON_VARS
from adn_deploy.core.env import Settings, parse_deploy_conf
from adn_deploy.infra import os_bootstrap
from adn_deploy.infra import ufw as ufw_infra
from adn_deploy.ui.external_editor import run_external_editor
from adn_deploy.ui.run_capture import capture_output
from adn_deploy.ui.screens.config_menu import VarPickerScreen
from adn_deploy.ui.widgets import InputScreen, MenuEntry, MenuScreen, OutputScreen


class DeployConfScreen(MenuScreen):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        entries = [
            MenuEntry("update-toolkit", "Update ADN-Deploy (git pull + pip)"),
            MenuEntry("pyenv", "Python environment (pyenv + pip)"),
            MenuEntry("stack", "Install stack (git, config, systemd, web)"),
            MenuEntry("var", "Change a variable"),
            MenuEntry("nano", "Edit deploy.conf (editor)"),
            MenuEntry("wizard", "Setup wizard (SERVER_ID, title, APRS)"),
            MenuEntry("init", "Create YAML configs from template"),
            MenuEntry("ufw", "Firewall (UFW)"),
            MenuEntry("doctor", "System diagnostics"),
            MenuEntry("pip", "Reinstall Python dependencies"),
            MenuEntry("back", "Back"),
        ]
        super().__init__("General settings", "deploy.conf and installer tasks", entries)

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        if action_id == "update-toolkit":
            text, _ = capture_output(lambda: app_update.update_deploy_toolkit(self.settings))
            self.app.push_screen(OutputScreen("Update ADN-Deploy", text))
            return
        if action_id == "pyenv":
            text, _ = capture_output(lambda: app_install.setup_pyenv(self.settings))
            self.app.push_screen(OutputScreen("Python environment (pyenv)", text))
            return
        if action_id == "stack":
            text, _ = capture_output(lambda: app_install.install_stack(self.settings))
            self.app.push_screen(OutputScreen("Install stack", text))
            return
        if action_id == "var":
            self.app.push_screen(DeployVarPickerScreen(self.settings))
            return
        if action_id == "nano":
            conf = self.settings.adn_deploy_conf
            if conf:
                run_external_editor(self.app, conf)
            return
        if action_id == "wizard":
            from adn_deploy.ui.app import AdnDeployApp

            if isinstance(self.app, AdnDeployApp):
                self.app.start_mandatory_wizard()
            return
        if action_id == "init":
            app_config.init_all(self.settings)
            self.app.notify("Config files initialized")
            return
        if action_id == "ufw":
            self.app.push_screen(UfwMenuScreen(self.settings))
            return
        if action_id == "doctor":
            text, _ = capture_output(lambda: doctor.run(self.settings))
            self.app.push_screen(OutputScreen("System diagnostics", text))
            return
        if action_id == "pip":
            ok = os_bootstrap.pip_all(self.settings)
            msg = "Python dependencies reinstalled." if ok else "pip install failed."
            self.app.push_screen(OutputScreen("pip", msg))


class DeployVarPickerScreen(MenuScreen):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        entries = [
            MenuEntry(meta.key, f"{meta.label} ({meta.key})")
            for meta in COMMON_VARS["deploy"]
        ]
        entries.append(MenuEntry("custom", "Other key (type name)"))
        entries.append(MenuEntry("back", "Back"))
        super().__init__("Variable", "deploy.conf", entries)

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        if action_id == "custom":
            self.app.push_screen(DeployCustomKeyScreen(self.settings))
            return
        self.app.push_screen(DeployVarEditScreen(self.settings, action_id))


class DeployCustomKeyScreen(InputScreen):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        super().__init__("Key", "Variable name (e.g. NGINX_SERVER_NAMES)", "")

    def on_button_pressed(self, event) -> None:
        from textual.widgets import Button, Input

        if not isinstance(event, Button.Pressed):
            return
        if event.button.id == "cancel":
            self.action_cancel()
            return
        key = self.query_one("#value", Input).value.strip()
        if not key:
            self.app.notify("Key required", severity="error")
            return
        self.app.pop_screen()
        self.app.push_screen(DeployVarEditScreen(self.settings, key))


class DeployVarEditScreen(InputScreen):
    def __init__(self, settings: Settings, key: str) -> None:
        self.settings = settings
        self.key = key
        default = ""
        conf = settings.adn_deploy_conf
        if conf and conf.is_file():
            default = parse_deploy_conf(conf).get(key, "")
        meta = next((m for m in COMMON_VARS["deploy"] if m.key == key), None)
        label = meta.label if meta else key
        super().__init__(label, key, default)

    def on_button_pressed(self, event) -> None:
        from textual.widgets import Button, Input

        if not isinstance(event, Button.Pressed):
            return
        if event.button.id == "cancel":
            self.action_cancel()
            return
        value = self.query_one("#value", Input).value
        conf = self.settings.adn_deploy_conf
        assert conf is not None
        app_config.set_kv(self.settings, conf, self.key, value)
        self.settings.apply_deploy_conf(parse_deploy_conf(conf))
        self.app.pop_screen()
        self.app.notify("Saved")


class UfwMenuScreen(MenuScreen):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        enable_lbl = "Disable firewall" if settings.ufw_enable == "1" else "Enable firewall"
        entries = [
            MenuEntry("live", "Show current rules (numbered)"),
            MenuEntry("preview", "Preview rebuild (dry-run)"),
            MenuEntry("apply", "Apply rebuild from config"),
            MenuEntry("trusted", "Trusted IPs (full inbound)"),
            MenuEntry("tcp", "Extra TCP ports (to any)"),
            MenuEntry("udp", "Extra UDP ports (to any)"),
            MenuEntry("enable", enable_lbl),
            MenuEntry("back", "Back"),
        ]
        super().__init__(
            "Firewall (UFW)",
            "Live rules, deploy.conf extras, rebuild from YAML",
            entries,
        )

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        if action_id == "live":
            text, _ = capture_output(lambda: ufw_infra.ufw_cmd(self.settings, "status"))
            self.app.push_screen(OutputScreen("UFW — live rules", text))
            return
        if action_id == "preview":
            text, _ = capture_output(
                lambda: ufw_infra.ufw_cmd(self.settings, "rebuild", dry_run=True)
            )
            self.app.push_screen(OutputScreen("UFW — preview rebuild", text))
            return
        if action_id == "apply":
            if self.settings.ufw_enable != "1":
                self.app.notify("Enable firewall first (UFW_ENABLE=1)", severity="error")
                return
            text, _ = capture_output(
                lambda: ufw_infra.ufw_cmd(self.settings, "rebuild", apply=True)
            )
            self.app.push_screen(OutputScreen("UFW — apply rebuild", text))
            return
        if action_id in ("trusted", "tcp", "udp"):
            key = {"trusted": "UFW_TRUSTED_SOURCES", "tcp": "UFW_EXTRA_TCP", "udp": "UFW_EXTRA_UDP"}[
                action_id
            ]
            self.app.push_screen(UfwListEditScreen(self.settings, key))
            return
        if action_id == "enable":
            conf = self.settings.adn_deploy_conf
            assert conf is not None
            new_val = "0" if self.settings.ufw_enable == "1" else "1"
            app_config.set_kv(self.settings, conf, "UFW_ENABLE", new_val)
            self.settings.apply_deploy_conf(parse_deploy_conf(conf))
            self.app.notify(f"UFW_ENABLE={new_val}")


class UfwListEditScreen(MenuScreen):
    def __init__(self, settings: Settings, varname: str) -> None:
        self.settings = settings
        self.varname = varname
        entries = [
            MenuEntry("show", "Show entries"),
            MenuEntry("add", "Add"),
            MenuEntry("back", "Back"),
        ]
        super().__init__(varname, "Saved in deploy.conf — used on rebuild", entries)

    def _current(self) -> str:
        conf = self.settings.adn_deploy_conf
        if conf and conf.is_file():
            return parse_deploy_conf(conf).get(self.varname, "")
        return ""

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        if action_id == "show":
            self.app.push_screen(OutputScreen(self.varname, self._current() or "(empty)"))
            return
        if action_id == "add":
            self.app.push_screen(UfwAddTokenScreen(self.settings, self.varname))


class UfwAddTokenScreen(InputScreen):
    def __init__(self, settings: Settings, varname: str) -> None:
        self.settings = settings
        self.varname = varname
        super().__init__(varname, f"New value for {varname}", "")

    def on_button_pressed(self, event) -> None:
        from textual.widgets import Button, Input

        if not isinstance(event, Button.Pressed):
            return
        if event.button.id == "cancel":
            self.action_cancel()
            return
        token = self.query_one("#value", Input).value.strip()
        if not token:
            self.app.notify("Value required", severity="error")
            return
        conf = self.settings.adn_deploy_conf
        assert conf is not None
        cur = parse_deploy_conf(conf).get(self.varname, "")
        parts = cur.split() if cur else []
        parts.append(token)
        app_config.set_kv(self.settings, conf, self.varname, " ".join(parts))
        self.settings.apply_deploy_conf(parse_deploy_conf(conf))
        self.app.pop_screen()
        self.app.notify("Added")
