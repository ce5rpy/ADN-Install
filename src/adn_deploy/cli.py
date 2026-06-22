"""ADN-Deploy CLI (Typer)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer

from adn_deploy.application import config as app_config
from adn_deploy.application import config_arrays
from adn_deploy.application import doctor
from adn_deploy.application import install as app_install
from adn_deploy.application import plugin_cmd
from adn_deploy.application import preflight
from adn_deploy.application import reference
from adn_deploy.application import update as app_update
from adn_deploy.application import web
from adn_deploy.core.env import init_env
from adn_deploy.infra import os_bootstrap
from adn_deploy.infra import systemd
from adn_deploy.infra import templates
from adn_deploy.infra import ufw as ufw_infra

app = typer.Typer(
    name="adn-deploy",
    help="ADN bare-metal installer and admin toolkit",
    no_args_is_help=True,
    add_completion=False,
)

_state: dict = {}


def _ensure_interactive_tty() -> bool:
    """Attach stdin/stdout/stderr to /dev/tty when invoked from a pipe (curl | sudo bash)."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        return True
    if not os.environ.get("TERM"):
        os.environ["TERM"] = "xterm-256color"
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return False
    try:
        os.dup2(fd, 0)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        os.close(fd)
    return sys.stdin.isatty() and sys.stdout.isatty()


def _settings():
    if "settings" not in _state:
        _state["settings"] = init_env(
            dry_run=_state.get("dry_run", False),
            profile=_state.get("profile", "full"),
            deploy_conf=_state.get("conf"),
            non_interactive=_state.get("yes", False),
        )
    return _state["settings"]


@app.callback()
def main(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions only"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive"),
    profile: str = typer.Option("full", "--profile", help="minimal|full"),
    conf: Optional[Path] = typer.Option(None, "--conf", help="deploy.conf path"),
) -> None:
    _state["dry_run"] = dry_run
    _state["yes"] = yes
    _state["profile"] = profile
    _state["conf"] = conf


@app.command("install")
def install_cmd(
    profile: Optional[str] = typer.Option(None, "--profile", help="minimal|full"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive"),
) -> None:
    """Full install: foundation + pyenv + stack (non-interactive)."""
    if profile is not None:
        _state["profile"] = profile
    if yes:
        _state["yes"] = True
    ok = app_install.run(_settings())
    raise typer.Exit(0 if ok else 1)


@app.command("finalize")
def finalize_cmd() -> None:
    """After wizard: download aliases, render nginx, restart services."""
    ok = app_install.finalize_bare_metal_install(_settings())
    raise typer.Exit(0 if ok else 1)


@app.command("pyenv")
def pyenv_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive"),
) -> None:
    """Install pyenv Python and adn-deploy package (after install.sh)."""
    if yes:
        _state["yes"] = True
    ok = app_install.setup_pyenv(_settings())
    raise typer.Exit(0 if ok else 1)


@app.command("stack")
def stack_cmd(
    profile: Optional[str] = typer.Option(None, "--profile", help="minimal|full"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive"),
) -> None:
    """Install apps, config, systemd, web (after install.sh + pyenv)."""
    if profile is not None:
        _state["profile"] = profile
    if yes:
        _state["yes"] = True
    ok = app_install.install_stack(_settings())
    raise typer.Exit(0 if ok else 1)


@app.command("preflight")
def preflight_cmd() -> None:
    """Check OS, disk, staging guards."""
    ok = preflight.run(_settings())
    raise typer.Exit(0 if ok else 1)


@app.command("menu")
def menu_cmd() -> None:
    """Interactive Textual admin menu."""
    if not _ensure_interactive_tty():
        typer.echo("adn-deploy menu: a TTY is required.", err=True)
        raise typer.Exit(1)
    from adn_deploy.ui.app import run_menu

    run_menu(_settings())


@app.command("wizard")
def wizard_cmd() -> None:
    """Mandatory setup wizard only (no main menu)."""
    if not _ensure_interactive_tty():
        typer.echo("adn-deploy wizard: a TTY is required.", err=True)
        raise typer.Exit(1)
    from adn_deploy.ui.app import run_setup_wizard

    run_setup_wizard(_settings())
    cfg = init_env()
    if app_config.mandatory_fields_incomplete(cfg):
        raise typer.Exit(1)
    from adn_deploy.application.install import post_mandatory_wizard_setup

    raise typer.Exit(0 if post_mandatory_wizard_setup(cfg) else 1)


@app.command("setup")
def setup_cmd() -> None:
    """Alias for wizard — mandatory SERVER_ID, title, hostname, APRS."""
    wizard_cmd()


@app.command("update")
def update_cmd(
    toolkit_only: bool = typer.Option(
        False,
        "--toolkit",
        help="Update ADN-Deploy only (git pull + pip -e); skip apps/services",
    ),
) -> None:
    """git pull toolkit and apps, pip, redeploy units."""
    cfg = _settings()
    ok = app_update.update_deploy_toolkit(cfg) if toolkit_only else app_update.run(cfg)
    raise typer.Exit(0 if ok else 1)


@app.command("pip")
def pip_cmd() -> None:
    """Reinstall pip -r for enabled plugins."""
    from adn_deploy.core.subprocess_runner import require_root_or_exit

    cfg = _settings()
    require_root_or_exit(cfg)
    ok = os_bootstrap.pip_all(cfg)
    raise typer.Exit(0 if ok else 1)


service_app = typer.Typer(help="systemctl wrapper")
app.add_typer(service_app, name="service")


@service_app.callback(invoke_without_command=True)
def service_main(
    ctx: typer.Context,
    action: str = typer.Argument("status"),
    unit: str = typer.Argument(""),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    rc = systemd.services_cmd(_settings(), action, unit)
    raise typer.Exit(rc)


config_app = typer.Typer(help="Configuration files")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init() -> None:
    app_config.init_all(_settings())


@config_app.command("sync-docker")
def config_sync_docker() -> None:
    """Docker only: apply deploy.conf wizard values to state YAMLs and compose .env."""
    app_config.sync_docker_wizard_config(_settings())


@config_app.command("edit")
def config_edit(
    service: str = typer.Argument("", help="adn-server|adn-monitor|deploy|…"),
) -> None:
    if not service:
        typer.echo("usage: config edit <service>", err=True)
        raise typer.Exit(1)
    app_config.edit(_settings(), service)


@config_app.command("wizard")
def config_wizard() -> None:
    app_config.wizard_scalars(_settings())


@config_app.command("set")
def config_set(
    service: str = typer.Argument(...),
    key: str = typer.Argument(...),
    value: str = typer.Argument(...),
) -> None:
    rc = app_config.set_cmd(_settings(), service, key, value)
    raise typer.Exit(rc)


@config_app.callback(invoke_without_command=True)
def config_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        app_config.init_all(_settings())


arrays_app = typer.Typer(help="Dashboard link arrays")
config_app.add_typer(arrays_app, name="arrays")


@arrays_app.command("list")
def arrays_list(collection: str = typer.Option("nav_links", "--collection")) -> None:
    config_arrays.arrays_cmd(_settings(), "list", collection=collection)


@arrays_app.command("add")
def arrays_add(
    collection: str = typer.Option(..., "--collection"),
    name: str = typer.Option(..., "--name"),
    url: str = typer.Option("", "--url"),
) -> None:
    config_arrays.arrays_cmd(_settings(), "add", collection=collection, name=name, url=url)


@arrays_app.command("edit")
def arrays_edit(
    collection: str = typer.Option(..., "--collection"),
    index: str = typer.Option(..., "--index"),
    name: str = typer.Option(..., "--name"),
    url: str = typer.Option("", "--url"),
) -> None:
    config_arrays.arrays_cmd(_settings(), "edit", collection=collection, index=index, name=name, url=url)


@arrays_app.command("delete")
def arrays_delete(
    collection: str = typer.Option(..., "--collection"),
    index: str = typer.Option(..., "--index"),
) -> None:
    config_arrays.arrays_cmd(_settings(), "delete", collection=collection, index=index)


@arrays_app.command("menu")
def arrays_menu(
    collection: str = typer.Argument("nav_links"),
) -> None:
    from adn_deploy.ui.screens.link_editor import run_link_editor

    run_link_editor(_settings(), collection)


web_app = typer.Typer(help="Web panel / nginx / TLS")
app.add_typer(web_app, name="web")


@web_app.callback(invoke_without_command=True)
def web_main(ctx: typer.Context, sub: str = typer.Argument("")) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if not sub:
        typer.echo("usage: web <panel|mysql|nginx|cert|ws|build> …", err=True)
        raise typer.Exit(1)
    rc = web.web_cmd(_settings(), sub)
    raise typer.Exit(rc)


@web_app.command("panel")
def web_panel_cmd() -> None:
    """Build frontend and render nginx vhost (after mandatory setup)."""
    raise typer.Exit(web.web_cmd(_settings(), "panel"))


@web_app.command("mysql")
def web_mysql() -> None:
    raise typer.Exit(web.web_cmd(_settings(), "mysql"))


@web_app.command("nginx")
def web_nginx(action: str = typer.Argument("reload")) -> None:
    raise typer.Exit(web.web_cmd(_settings(), "nginx", action))


@web_app.command("cert")
def web_cert(action: str = typer.Argument("status")) -> None:
    raise typer.Exit(web.web_cmd(_settings(), "cert", action))


@web_app.command("ssl")
def web_ssl(action: str = typer.Argument("enable")) -> None:
    raise typer.Exit(web.web_cmd(_settings(), "ssl", action))


@web_app.command("ws")
def web_ws(
    via_nginx: bool = typer.Option(False, "--via-nginx"),
    soft: bool = typer.Option(False, "--soft"),
) -> None:
    args = []
    if via_nginx:
        args.append("--via-nginx")
    if soft:
        args.append("--soft")
    raise typer.Exit(web.web_cmd(_settings(), "ws", *args))


@web_app.command("build")
def web_build() -> None:
    raise typer.Exit(web.web_cmd(_settings(), "build"))


ufw_app = typer.Typer(help="UFW firewall")
app.add_typer(ufw_app, name="ufw")


@ufw_app.callback(invoke_without_command=True)
def ufw_main(
    ctx: typer.Context,
    action: str = typer.Argument("status"),
    apply: bool = typer.Option(False, "--apply"),
    dry_run_flag: bool = typer.Option(False, "--dry-run"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    rc = ufw_infra.ufw_cmd(_settings(), action, apply=apply, dry_run=dry_run_flag)
    raise typer.Exit(rc)


@app.command("doctor")
def doctor_cmd() -> None:
    """Health checks."""
    ok = doctor.run(_settings())
    raise typer.Exit(0 if ok else 1)


@app.command("render-all")
def render_all_cmd() -> None:
    """Render systemd/nginx/logrotate into sysroot."""
    templates.render_all(_settings())


reference_app = typer.Typer(help="Reference files")
app.add_typer(reference_app, name="reference")


@reference_app.command("dump")
def reference_dump(outfile: Optional[Path] = typer.Argument(None)) -> None:
    path = reference.dump(_settings(), outfile)
    typer.echo(path)


plugin_app = typer.Typer(help="Enable/disable plugins")
app.add_typer(plugin_app, name="plugin")


@plugin_app.command("enable")
def plugin_enable(id: str = typer.Argument(...)) -> None:
    raise typer.Exit(plugin_cmd.run(_settings(), "enable", id))


@plugin_app.command("disable")
def plugin_disable(id: str = typer.Argument(...)) -> None:
    raise typer.Exit(plugin_cmd.run(_settings(), "disable", id))


@app.command("help")
def help_cmd(ctx: typer.Context) -> None:
    """Show help."""
    typer.echo(ctx.get_help())


if __name__ == "__main__":
    app()
