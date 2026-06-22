"""Web panel / nginx / TLS menu."""

from __future__ import annotations

from adn_deploy.application import web
from adn_deploy.core.env import Settings, parse_deploy_conf
from adn_deploy.ui.run_capture import capture_output
from adn_deploy.ui.widgets import InputScreen, MenuEntry, MenuScreen, OutputScreen


class WebMenuScreen(MenuScreen):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.docker:
            title = "Traefik / HTTPS"
            blurb = "Edge routing and TLS (containers — no host nginx/mysql)"
            self.nginx_label = ""
            self.render_label = "Regenerate Traefik routing"
            entries = [
                MenuEntry("render", self.render_label),
                MenuEntry("ssl-enable", "Enable HTTPS (Let's Encrypt)"),
                MenuEntry("back", "Back"),
            ]
        else:
            title = "Web panel / Nginx"
            blurb = "Nginx, Let's Encrypt, MySQL, and WebSocket test"
            self.nginx_label = "Test and reload Nginx"
            self.render_label = "Regenerate site from template"
            entries = [
                MenuEntry("mysql", "Create/sync MySQL user and YAML"),
                MenuEntry("nginx", self.nginx_label),
                MenuEntry("render", self.render_label),
                MenuEntry("ssl-enable", "Enable SSL (Let's Encrypt)"),
                MenuEntry("cert", "View SSL certificates"),
                MenuEntry("cert-renew", "Renew certificates"),
                MenuEntry("ws", "Test monitor WebSocket"),
                MenuEntry("back", "Back"),
            ]
        super().__init__(title, blurb, entries)

    def on_menu_action(self, action_id: str) -> None:
        if action_id == "back":
            self.action_back()
            return
        if action_id == "mysql":
            text, _ = capture_output(lambda: web.mysql_bootstrap(self.settings))
            self.app.push_screen(OutputScreen("MySQL — create / sync", text))
            return
        if action_id == "nginx":
            if self.settings.docker:
                text, _ = capture_output(lambda: web.web_cmd(self.settings, "nginx", "test"))
            else:
                text, _ = capture_output(lambda: web.nginx_cmd(self.settings, "reload"))
            self.app.push_screen(OutputScreen(self.nginx_label, text))
            return
        if action_id == "render":
            if self.settings.docker:
                text, _ = capture_output(lambda: web.web_cmd(self.settings, "nginx", "render"))
            else:
                text, _ = capture_output(lambda: web.nginx_render(self.settings))
            self.app.push_screen(OutputScreen(self.render_label, text))
            return
        if action_id == "ssl-enable":
            self._ssl_enable()
            return
        if action_id == "cert":
            text, _ = capture_output(lambda: web.certbot_cmd(self.settings, "status"))
            self.app.push_screen(OutputScreen("SSL certificates", text))
            return
        if action_id == "cert-renew":
            text, _ = capture_output(lambda: web.certbot_cmd(self.settings, "renew"))
            self.app.push_screen(OutputScreen("SSL renew", text))
            return
        if action_id == "ws":
            text, _ = capture_output(lambda: web.ws_cmd(self.settings))
            self.app.push_screen(OutputScreen("Monitor WebSocket test", text))

    def _ssl_enable(self) -> None:
        if web.ssl_enabled(self.settings):
            self.app.push_screen(
                OutputScreen(
                    "SSL",
                    "SSL is already enabled (WEB_SSL=1).\nUse View SSL certificates or Renew.",
                )
            )
            return
        host_names = self.settings.nginx_server_names.strip()
        if self.settings.docker:
            host_names = (self.settings.traefik_host_names or host_names).strip()
        if not host_names or host_names == "_":
            msg = (
                "Set TRAEFIK_HOST_NAMES in deploy.conf first."
                if self.settings.docker
                else "Set NGINX_SERVER_NAMES in deploy.conf first (General settings)."
            )
            self.app.push_screen(OutputScreen("SSL", msg))
            return
        if not self.settings.certbot_email:
            self.app.push_screen(SslEmailScreen(self.settings, host_names))
            return
        self._issue_cert(host_names)

    def _issue_cert(self, host_names: str) -> None:
        from adn_deploy.application import config as app_config

        conf = self.settings.adn_deploy_conf
        assert conf is not None
        primary = host_names.split()[0]
        app_config.set_kv(self.settings, conf, "CERTBOT_PRIMARY_DOMAIN", primary)
        self.settings.apply_deploy_conf(parse_deploy_conf(conf))
        ok = web.certbot_issue(self.settings)
        if ok:
            web.ws_sync_yaml(self.settings)
            self.app.push_screen(OutputScreen("SSL", "SSL enabled. Panel is served over HTTPS."))
        else:
            self.app.push_screen(
                OutputScreen(
                    "SSL",
                    "Certbot could not issue the certificate.\nCheck DNS and nginx, then try again.",
                )
            )


class SslEmailScreen(InputScreen):
    def __init__(self, settings: Settings, host_names: str) -> None:
        self.settings = settings
        self.host_names = host_names
        super().__init__("Let's Encrypt", "ACME contact email", "")

    def on_button_pressed(self, event) -> None:
        from textual.widgets import Button, Input

        if not isinstance(event, Button.Pressed):
            return
        if event.button.id == "cancel":
            self.action_cancel()
            return
        email = self.query_one("#value", Input).value.strip()
        if not email:
            self.app.notify("Email required", severity="error")
            return
        from adn_deploy.application import config as app_config

        conf = self.settings.adn_deploy_conf
        assert conf is not None
        app_config.set_kv(self.settings, conf, "CERTBOT_EMAIL", email)
        self.settings.apply_deploy_conf(parse_deploy_conf(conf))
        self.app.pop_screen()
        parent = self.app.screen
        if isinstance(parent, WebMenuScreen):
            parent._issue_cert(self.host_names)
