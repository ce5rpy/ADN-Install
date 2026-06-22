"""ADN-Deploy Textual root application."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App
from textual.binding import Binding

from adn_deploy.application import config as app_config
from adn_deploy.core.env import Settings
from adn_deploy.infra import yaml_store
from adn_deploy.ui.run_capture import capture_call
from adn_deploy.ui.screens.main_menu import MainMenuScreen
from adn_deploy.ui.widgets import InputScreen, OutputScreen


class AdnDeployApp(App):
    TITLE = "ADN-Deploy"
    # Ctrl+C -> quit (Cursor steals Ctrl+Q). F10 also quits (Ctrl+X is reserved for nano).
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True, system=True),
        Binding("f10", "quit", "Quit", show=True),
    ]
    CSS = """
    Screen {
        background: $surface;
    }
    #subtitle, #hint {
        margin: 0 0 1 0;
    }
    #output {
        margin: 1 0;
    }
    Input {
        margin: 0 0 1 0;
    }
    """

    def __init__(self, settings: Settings, *, wizard_only: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self._wizard_only = wizard_only

    def _quiet(self, fn):
        """Run config/install helpers without printing over the TUI."""
        _, _, result = capture_call(fn)
        return result

    def _bootstrap_wizard_configs(self) -> None:
        app_config.deploy_conf_init(self.settings)
        app_config.init_peer(self.settings)
        app_config.init_monitor(self.settings)

    def _show_main_menu(self) -> None:
        self._present_screen(MainMenuScreen(self.settings))
        self.refresh(repaint=True, layout=True)

    def _present_screen(self, screen) -> None:
        """Push on Textual's empty _default screen; switch otherwise."""
        if self.screen.id == "_default":
            self.push_screen(screen)
        else:
            self.switch_screen(screen)

    def _wizard_error(self, message: str, retry: Callable[[], None]) -> None:
        self.switch_screen(OutputScreen("Setup", message, on_close=retry))

    def _leave_wizard(self, code: int = 0) -> None:
        self.exit(code)

    def _wizard_cancelled(self) -> None:
        extra = ""
        if app_config.daprs_plugin_enabled(self.settings):
            extra = ", and APRS gateway callsign"
        body = (
            "Mandatory setup was not completed.\n\n"
            "Run adn-deploy wizard (or adn-docker setup on Docker) to finish "
            f"SERVER_ID, dashboard title{extra}."
        )
        if self._wizard_only:
            self.switch_screen(
                OutputScreen("Setup required", body, on_close=lambda: self._leave_wizard(1))
            )
            return
        self.switch_screen(
            OutputScreen(
                "Setup required",
                body,
                on_close=self._show_main_menu,
            )
        )

    def _wizard_step_ids(self) -> list[str]:
        steps = ["server_id", "dashtitle"]
        if app_config.daprs_plugin_enabled(self.settings):
            steps.append("aprs")
        if not self.settings.docker:
            steps.append("hostname")
        return steps

    def _wizard_next_after_dashtitle(self) -> None:
        if app_config.daprs_plugin_enabled(self.settings):
            self._wizard_daprs_aprs()
        elif self.settings.docker:
            self._wizard_done()
        else:
            self._wizard_nginx()

    def _wizard_next_after_aprs(self) -> None:
        if self.settings.docker:
            self._wizard_done()
        else:
            self._wizard_nginx()

    def _wizard_label(self, step_id: str) -> str:
        steps = self._wizard_step_ids()
        idx = steps.index(step_id) + 1
        return f"Mandatory setup ({idx}/{len(steps)})"

    def on_mount(self) -> None:
        if self._wizard_only:
            self._wizard_resume()
            return
        if self._menu_setup_needed():
            self._quiet(self._bootstrap_wizard_configs)
            self._wizard_resume()
        else:
            self._show_main_menu()

    def _wizard_resume(self) -> None:
        """Continue mandatory setup at the first incomplete field."""
        from adn_deploy.core.env import init_env

        self._quiet(self._bootstrap_wizard_configs)
        self.settings = init_env()
        cfg = self.settings
        if app_config.server_id_incomplete(cfg):
            self._wizard_server_id()
            return
        if app_config.dashtitle_incomplete(cfg):
            self._wizard_dashtitle()
            return
        if app_config.daprs_plugin_enabled(cfg) and app_config.daprs_aprs_incomplete(cfg):
            self._wizard_daprs_aprs()
            return
        if not cfg.docker and app_config.nginx_hosts_incomplete(cfg):
            self._wizard_nginx()
            return
        if cfg.docker and app_config.traefik_acme_incomplete(cfg):
            self._wizard_acme_email()
            return
        app_config.mandatory_setup_mark_done(cfg)
        if self._wizard_only:
            self._leave_wizard(0)
        else:
            self._show_main_menu()

    def _menu_setup_needed(self) -> bool:
        cfg = self.settings
        if cfg.filegen:
            return False
        if not app_config.mandatory_fields_incomplete(cfg):
            app_config.mandatory_setup_mark_done(cfg)
            return False
        return True

    def _wizard_server_id(self) -> None:
        peer = self.settings.adn_dmr_server_path / "adn-server.yaml"
        cur = yaml_store.yaml_get(peer, "GLOBAL.SERVER_ID") if peer.is_file() else ""
        default = "" if app_config.server_id_invalid(str(cur or "")) else str(cur)
        self._present_screen(
            InputScreen(
                self._wizard_label("server_id"),
                "SERVER_ID (unique numeric ID for this server)",
                default,
                on_submit=self._submit_server_id,
                on_cancel=self._wizard_cancelled,
            )
        )

    def _submit_server_id(self, value: str) -> None:
        if not value or not self._quiet(
            lambda: app_config.apply_server_id(self.settings, value)
        ):
            self._wizard_error(
                "SERVER_ID is required.\nEnter your assigned numeric ID (digits only, not 0).",
                self._wizard_server_id,
            )
            return
        self._wizard_dashtitle()

    def _wizard_dashtitle(self) -> None:
        if not app_config.dashtitle_incomplete(self.settings):
            self._wizard_next_after_dashtitle()
            return
        peer = self.settings.adn_dmr_server_path / "adn-server.yaml"
        mon = self.settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"
        sid = yaml_store.yaml_get(peer, "GLOBAL.SERVER_ID") if peer.is_file() else ""
        cur = yaml_store.yaml_get(mon, "DASHBOARD.DASHTITLE") if mon.is_file() else ""
        default = f"ADN Systems {sid}" if sid else "ADN Systems"
        if cur and not app_config.is_placeholder_dashtitle(str(cur)):
            default = str(cur)
        self.switch_screen(
            InputScreen(
                self._wizard_label("dashtitle"),
                "Dashboard title (header text)",
                default,
                on_submit=self._submit_dashtitle,
                on_cancel=self._wizard_cancelled,
            )
        )

    def _submit_dashtitle(self, value: str) -> None:
        if not value or not self._quiet(
            lambda: app_config.apply_dashtitle(self.settings, value)
        ):
            self._wizard_error(
                "Dashboard title is required.",
                self._wizard_dashtitle,
            )
            return
        self._wizard_next_after_dashtitle()

    def _wizard_nginx(self) -> None:
        if not app_config.nginx_hosts_incomplete(self.settings):
            if self.settings.docker:
                self._wizard_acme_email()
            else:
                self._wizard_done()
            return
        if self.settings.docker:
            default = (self.settings.traefik_host_names or "_").strip() or "_"
            field = "Public hostname for Traefik (_ = any host)"
        else:
            if not self.settings.nginx_server_names.strip():
                self._quiet(lambda: app_config.wizard_nginx_hosts_required(self.settings))
                self._wizard_done()
                return
            default = self.settings.nginx_server_names
            field = "Panel domain(s), space-separated"
        self.switch_screen(
            InputScreen(
                self._wizard_label("hostname"),
                field,
                default,
                on_submit=self._submit_nginx,
                on_cancel=self._wizard_cancelled,
            )
        )

    def _submit_nginx(self, value: str) -> None:
        if not value or not self._quiet(
            lambda: app_config.apply_nginx_hosts(self.settings, value)
        ):
            self._wizard_error(
                "Replace the example hostname with your real panel domain\n"
                "(or use catch-all _).",
                self._wizard_nginx,
            )
            return
        if self.settings.docker:
            self._wizard_acme_email()
        else:
            self._wizard_done()

    def _wizard_acme_email(self) -> None:
        if not app_config.traefik_acme_incomplete(self.settings):
            self._wizard_daprs_aprs()
            return
        default = app_config.traefik_acme_email_value(self.settings) or "admin@example.com"
        self.switch_screen(
            InputScreen(
                self._wizard_label("acme"),
                "ACME email for HTTPS later (adn-docker ssl enable)",
                default,
                on_submit=self._submit_acme_email,
                on_cancel=self._wizard_cancelled,
            )
        )

    def _submit_acme_email(self, value: str) -> None:
        if not value or not self._quiet(
            lambda: app_config.apply_traefik_acme_email(self.settings, value)
        ):
            self._wizard_error(
                "Enter a valid email for Let's Encrypt.",
                self._wizard_acme_email,
            )
            return
        self._wizard_daprs_aprs()

    def _wizard_daprs_aprs(self) -> None:
        if not app_config.daprs_plugin_enabled(self.settings):
            self._wizard_next_after_aprs()
            return
        if not app_config.daprs_aprs_incomplete(self.settings):
            self._wizard_next_after_aprs()
            return
        default = app_config.daprs_aprs_default(self.settings)
        self.switch_screen(
            InputScreen(
                self._wizard_label("aprs"),
                "APRS callsign (base only, e.g. CE5RPY)\n"
                "SSID -10 and passcode are applied automatically.",
                default,
                on_submit=self._submit_daprs_aprs,
                on_cancel=self._wizard_cancelled,
            )
        )

    def _submit_daprs_aprs(self, value: str) -> None:
        if not value or not self._quiet(
            lambda: app_config.apply_daprs_aprs_login(self.settings, value)
        ):
            self._wizard_error(
                "Enter a valid base callsign (e.g. CE5RPY, without -SSID).",
                self._wizard_daprs_aprs,
            )
            return
        self._wizard_next_after_aprs()

    def start_mandatory_wizard(self) -> None:
        """Re-run mandatory setup (SERVER_ID, title, APRS, hostname)."""
        self._wizard_resume()

    def _wizard_done(self) -> None:
        if app_config.mandatory_fields_incomplete(self.settings):
            if app_config.daprs_aprs_incomplete(self.settings) and app_config.daprs_plugin_enabled(
                self.settings
            ):
                self._wizard_daprs_aprs()
                return
            if not self.settings.docker and app_config.nginx_hosts_incomplete(self.settings):
                self._wizard_nginx()
                return
        if not app_config.mandatory_fields_incomplete(self.settings):
            self._quiet(lambda: app_config.mandatory_setup_mark_done(self.settings))
            if self.settings.docker:
                self._quiet(lambda: app_config.sync_docker_wizard_config(self.settings))
        if self._wizard_only:
            self._leave_wizard(0 if not app_config.mandatory_fields_incomplete(self.settings) else 1)
        else:
            self._show_main_menu()


def run_menu(settings: Settings) -> None:
    AdnDeployApp(settings).run()


def run_setup_wizard(settings: Settings) -> None:
    """Mandatory setup only — no main menu (install / adn-docker setup)."""
    AdnDeployApp(settings, wizard_only=True).run()
