"""Environment defaults, deploy.conf loading, and runtime flags."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar

from adn_deploy.core.paths import DeployPaths, deploy_conf_path, get_deploy_home

_DEPLOY_CONF_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$"
)
_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _truthy(value: str | bool | int | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _strip_deploy_value(raw: str) -> str:
    s = raw.strip()
    if not s:
        return ""
    if s[0] in "\"'":
        quote = s[0]
        end = s.find(quote, 1)
        if end != -1:
            return s[1:end]
    if " #" in s:
        s = s.split(" #", 1)[0].rstrip()
    return s.strip().strip("\"'")


def _expand_deploy_vars(value: str, known: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return known.get(key, match.group(0))

    prev = None
    out = value
    while prev != out:
        prev = out
        out = _VAR_REF.sub(repl, out)
    return out


# Keys allowed from deploy.conf (no arbitrary shell execution).
KNOWN_DEPLOY_KEYS: frozenset[str] = frozenset(
    {
        "ADN_ROOT",
        "ADN_DMR_SERVER_PATH",
        "ADN_MONITOR_PATH",
        "ADN_PYENV_ROOT",
        "ADN_USER",
        "ADN_CREATE_USER",
        "ADN_SUDO_NOPASSWD",
        "ADN_USER_HOME",
        "ADN_PYTHON_VERSION",
        "ADN_PYENV_PYTHON",
        "ADN_PYENV_REINSTALL",
        "ADN_LOG_DIR",
        "ADN_DEPLOY_CONF",
        "ADN_DEPLOY_STAGING",
        "ADN_DEPLOY_DRY_RUN",
        "ADN_DEPLOY_FILEGEN",
        "ADN_DEPLOY_SKIP_OS_PACKAGES",
        "ADN_DEPLOY_PROFILE",
        "ADN_DEPLOY_NON_INTERACTIVE",
        "ADN_DEPLOY_DOCKER",
        "ADN_SYSROOT",
        "ADN_ETC_ROOT",
        "ADN_SKIP_CLONE",
        "ADN_INSTALL_WEB_OPTIONAL",
        "HBP_PASSPHRASE",
        "ADN_SERVER_ID",
        "ADN_DASHTITLE",
        "NGINX_SITE_NAME",
        "NGINX_SERVER_NAMES",
        "TRAEFIK_HOST_NAMES",
        "NGINX_LISTEN_IP",
        "MONITOR_APP_PORT",
        "MONITOR_APP_UPSTREAM",
        "WEBSOCKET_PORT",
        "WEBSOCKET_UPSTREAM",
        "CERTBOT_EMAIL",
        "CERTBOT_PRIMARY_DOMAIN",
        "WEB_SSL",
        "UFW_ENABLE",
        "UFW_EXTRA_TCP",
        "UFW_EXTRA_UDP",
        "UFW_TRUSTED_SOURCES",
        "GIT_URL_DEPLOY",
        "GIT_URL_PEER",
        "GIT_URL_MONITOR",
        "GIT_BRANCH_DEPLOY",
        "GIT_BRANCH_PEER",
        "GIT_BRANCH_MONITOR",
        "GIT_URL_DAPRS",
        "GIT_BRANCH_DAPRS",
        "DAPRS_DATA_DMR_ID",
        "DAPRS_PEER_PORT",
        "DAPRS_APRS_CALLSIGN",
        "DAPRS_APRS_SERVER",
        "MYSQL_DB_NAME",
        "MYSQL_DB_USER",
        "MYSQL_DB_PASSWORD",
        "MYSQL_ROOT_PASSWORD",
    }
)


def parse_deploy_conf(path: Path) -> dict[str, str]:
    """Parse shell-style ``KEY=VALUE`` lines; only whitelisted keys are returned."""
    if not path.is_file():
        return {}

    raw_pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _DEPLOY_CONF_LINE.match(line)
        if not match:
            continue
        key, raw_val = match.group(1), match.group(2)
        if key not in KNOWN_DEPLOY_KEYS:
            continue
        raw_pairs.append((key, _strip_deploy_value(raw_val)))

    known: dict[str, str] = dict(os.environ)
    out: dict[str, str] = {}
    for key, raw_val in raw_pairs:
        expanded = _expand_deploy_vars(raw_val, {**known, **out})
        out[key] = expanded
    return out


@dataclass
class Settings:
    """Runtime configuration mirroring ``lib/env.sh`` defaults."""

    FIELD_TO_ENV: ClassVar[dict[str, str]] = {}

    adn_deploy_home: Path = field(default_factory=get_deploy_home)
    adn_root: Path = Path("/opt")
    adn_dmr_server_path: Path | None = None
    adn_monitor_path: Path | None = None
    adn_pyenv_root: Path | None = None
    adn_user: str = "adn"
    adn_create_user: str = "1"
    adn_sudo_nopasswd: str = "1"
    adn_user_home: str = ""
    adn_python_version: str = "3.13.14"
    adn_pyenv_python: Path | None = None
    adn_deploy_conf: Path | None = None
    adn_log_dir: Path = Path("/var/log/adn-server")
    adn_deploy_staging: str = "0"
    adn_deploy_dry_run: str = "0"
    adn_deploy_filegen: str = "0"
    adn_deploy_skip_os_packages: str = "0"
    adn_deploy_profile: str = "full"
    adn_deploy_non_interactive: str = "0"
    adn_deploy_docker: str = "0"
    adn_sysroot: str = ""
    adn_etc_root: Path = Path("/etc")

    adn_server_id: str = ""
    adn_dashtitle: str = ""
    hbp_passphrase: str = ""

    nginx_site_name: str = "adn-monitor"
    nginx_server_names: str = ""
    traefik_host_names: str = ""
    nginx_listen_ip: str = ""
    monitor_app_port: str = "8080"
    monitor_app_upstream: str = "127.0.0.1"
    certbot_email: str = ""
    certbot_primary_domain: str = ""
    web_ssl: str = "0"
    ufw_enable: str = "0"
    ufw_extra_tcp: str = ""
    ufw_extra_udp: str = ""
    ufw_trusted_sources: str = ""

    git_url_deploy: str = "https://github.com/ce5rpy/ADN-Install.git"
    git_url_peer: str = "https://github.com/ce5rpy/ADN-DMR-Peer-Server.git"
    git_url_monitor: str = "https://github.com/ce5rpy/ADN-Monitor.git"
    git_branch_deploy: str = ""
    git_branch_peer: str = ""
    git_branch_monitor: str = ""

    git_url_daprs: str = "https://gitlab.com/C31AG/hbnet.git"
    git_branch_daprs: str = "aprs_features"
    daprs_data_dmr_id: str = "900999"
    daprs_peer_port: str = "54871"
    daprs_aprs_callsign: str = ""
    daprs_aprs_server: str = "rotate.aprs2.net"

    mysql_db_name: str = "hbmon"
    mysql_db_user: str = "self_service_user"
    mysql_db_password: str = ""
    mysql_root_password: str = ""

    # Preserved from environment before deploy.conf (bash adn_env_init behavior).
    _env_staging: str = ""
    _env_filegen: str = ""
    _env_skip_os: str = ""
    _env_nonint: str = ""
    _env_sysroot: str = ""
    _env_root: str = ""
    _env_deploy_home: str = ""

    paths: DeployPaths = field(default_factory=DeployPaths.from_home)

    @property
    def dry_run(self) -> bool:
        return _truthy(self.adn_deploy_dry_run)

    @property
    def staging(self) -> bool:
        return _truthy(self.adn_deploy_staging)

    @property
    def filegen(self) -> bool:
        return _truthy(self.adn_deploy_filegen) and self.staging

    @property
    def docker(self) -> bool:
        return _truthy(self.adn_deploy_docker)

    @property
    def profile(self) -> str:
        return self.adn_deploy_profile or "full"

    @property
    def skip_os_packages(self) -> bool:
        return self.staging or _truthy(self.adn_deploy_skip_os_packages)

    @property
    def non_interactive(self) -> bool:
        return _truthy(self.adn_deploy_non_interactive)

    def has_sysroot(self) -> bool:
        return bool(self.adn_sysroot)

    def pyenv_python(self) -> Path:
        """Resolve pyenv interpreter (matches ``adn_pyenv_python`` in bash)."""
        if self.adn_pyenv_python:
            explicit = (
                self.adn_pyenv_python
                if isinstance(self.adn_pyenv_python, Path)
                else Path(str(self.adn_pyenv_python))
            )
            if explicit.is_file():
                return explicit

        ver_py = (
            (self.adn_pyenv_root or self.adn_root / ".pyenv")
            / "versions"
            / self.adn_python_version
            / "bin"
            / "python3"
        )
        if ver_py.is_file():
            return ver_py

        shim = (self.adn_pyenv_root or self.adn_root / ".pyenv") / "shims" / "python3"
        if shim.is_file():
            return shim

        filegen_fallback = Path("/opt/.pyenv/versions/3.11.8/bin/python3")
        if self.filegen and filegen_fallback.is_file():
            return filegen_fallback

        raise FileNotFoundError(
            f"pyenv Python {self.adn_python_version} not found under "
            f"{self.adn_pyenv_root or self.adn_root / '.pyenv'}/versions"
        )

    def expand_plugin_path(self, template: str) -> str:
        mapping = {
            "ADN_ROOT": str(self.adn_root),
            "ADN_DMR_SERVER_PATH": str(self.adn_dmr_server_path or self.adn_root / "adn-dmr-server"),
            "ADN_MONITOR_PATH": str(self.adn_monitor_path or self.adn_root / "adn-monitor"),
        }
        out = template
        for key, val in mapping.items():
            out = out.replace("${" + key + "}", val)
        return out

    _PATH_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "adn_deploy_home",
            "adn_root",
            "adn_dmr_server_path",
            "adn_monitor_path",
            "adn_pyenv_root",
            "adn_pyenv_python",
            "adn_deploy_conf",
            "adn_log_dir",
            "adn_etc_root",
        }
    )

    def apply_deploy_conf(self, conf: dict[str, str]) -> None:
        for key, value in conf.items():
            attr = key.lower()
            if not hasattr(self, attr):
                continue
            if attr in self._PATH_FIELDS and value:
                setattr(self, attr, Path(value))
            else:
                setattr(self, attr, value)

    def finalize_paths(self) -> None:
        self.adn_dmr_server_path = self.adn_dmr_server_path or self.adn_root / "adn-dmr-server"
        self.adn_monitor_path = self.adn_monitor_path or self.adn_root / "adn-monitor"
        self.adn_pyenv_root = self.adn_pyenv_root or self.adn_root / ".pyenv"
        self.adn_deploy_conf = self.adn_deploy_conf or deploy_conf_path(
            adn_root=self.adn_root,
            deploy_home=self.adn_deploy_home,
        )
        self.paths = DeployPaths.from_home(self.adn_deploy_home)

    def to_env_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for f in fields(self):
            if f.name.startswith("_") or f.name == "paths":
                continue
            val = getattr(self, f.name)
            env_key = f.name.upper()
            if isinstance(val, Path):
                out[env_key] = str(val)
            elif val is not None:
                out[env_key] = str(val)
        out["ADN_DEPLOY_HOME"] = str(self.adn_deploy_home)
        out["WEBSOCKET_PORT"] = self.monitor_app_port
        out["WEBSOCKET_UPSTREAM"] = self.monitor_app_upstream
        return out

    def export_to_os_environ(self) -> None:
        for key, value in self.to_env_dict().items():
            os.environ[key] = value


def apply_docker_cli_container_paths(settings: Settings) -> None:
    """Inside adn-deploy-cli: map host paths from deploy.conf/.env to bind mounts."""
    if not settings.docker:
        return
    env_docker_state = os.environ.get("ADN_DOCKER_STATE", "").strip()
    if env_docker_state:
        state = Path(env_docker_state)
        settings.adn_root = state
        settings.adn_dmr_server_path = state / "peer"
        settings.adn_monitor_path = state / "monitor"
        settings.adn_log_dir = state / "logs"
        settings.adn_etc_root = state / "etc"
    env_deploy_conf = os.environ.get("ADN_DEPLOY_CONF", "").strip()
    if env_deploy_conf:
        mounted = Path(env_deploy_conf)
        if mounted.is_file():
            settings.adn_deploy_conf = mounted


def init_env(
    *,
    deploy_home: Path | None = None,
    reload_conf: bool = True,
    dry_run: bool | None = None,
    profile: str | None = None,
    deploy_conf: Path | None = None,
    non_interactive: bool | None = None,
) -> Settings:
    """Python equivalent of ``adn_env_init`` (core path/flag logic only)."""
    settings = Settings()
    if deploy_home is not None:
        settings.adn_deploy_home = deploy_home.resolve()
    elif os.environ.get("ADN_DEPLOY_HOME"):
        settings.adn_deploy_home = Path(os.environ["ADN_DEPLOY_HOME"]).resolve()
    else:
        settings.adn_deploy_home = get_deploy_home()

    settings._env_sysroot = os.environ.get("ADN_SYSROOT", "")
    settings._env_root = os.environ.get("ADN_ROOT", "")
    settings._env_deploy_home = os.environ.get("ADN_DEPLOY_HOME", "")
    settings._env_staging = os.environ.get("ADN_DEPLOY_STAGING", "")
    settings._env_filegen = os.environ.get("ADN_DEPLOY_FILEGEN", "")
    settings._env_skip_os = os.environ.get("ADN_DEPLOY_SKIP_OS_PACKAGES", "")
    settings._env_nonint = os.environ.get("ADN_DEPLOY_NON_INTERACTIVE", "")

    if os.environ.get("ADN_ROOT"):
        settings.adn_root = Path(os.environ["ADN_ROOT"])
    settings.finalize_paths()

    if reload_conf and settings.adn_deploy_conf and settings.adn_deploy_conf.is_file():
        settings.apply_deploy_conf(parse_deploy_conf(settings.adn_deploy_conf))

    if settings._env_staging:
        settings.adn_deploy_staging = settings._env_staging
    if settings._env_filegen:
        settings.adn_deploy_filegen = settings._env_filegen
    if settings._env_skip_os:
        settings.adn_deploy_skip_os_packages = settings._env_skip_os
    if settings._env_nonint:
        settings.adn_deploy_non_interactive = settings._env_nonint

    if settings._env_sysroot:
        settings.adn_sysroot = settings._env_sysroot
        settings.adn_root = Path(settings._env_root or f"{settings.adn_sysroot}/opt")
        if settings._env_deploy_home:
            settings.adn_deploy_home = Path(settings._env_deploy_home)
        else:
            settings.adn_deploy_home = settings.adn_root / "ADN-Install"
    elif not settings.adn_sysroot and settings.filegen:
        root_str = str(settings.adn_root)
        if root_str.endswith("/opt") and root_str != "/opt":
            settings.adn_sysroot = root_str[: -len("/opt")]

    if settings.has_sysroot() and settings.filegen:
        sysroot = Path(settings.adn_sysroot)
        settings.adn_root = sysroot / "opt"
        settings.adn_dmr_server_path = settings.adn_root / "adn-dmr-server"
        settings.adn_monitor_path = settings.adn_root / "adn-monitor"
        settings.adn_pyenv_root = settings.adn_root / ".pyenv"
        if settings._env_deploy_home:
            settings.adn_deploy_home = Path(settings._env_deploy_home)
        else:
            settings.adn_deploy_home = settings.adn_root / "ADN-Install"
        settings.adn_deploy_conf = settings.adn_deploy_home / "deploy.conf"
        log = str(settings.adn_log_dir)
        if log.startswith("/var/log/") or not log:
            settings.adn_log_dir = sysroot / "var/log/adn-server"
    else:
        settings.finalize_paths()

    if settings.docker:
        docker_env = settings.adn_deploy_home / "install-docker" / "compose" / ".env"
        if docker_env.is_file():
            settings.apply_deploy_conf(parse_deploy_conf(docker_env))
        settings.adn_deploy_skip_os_packages = "1"
        if not settings.monitor_app_upstream or settings.monitor_app_upstream in ("127.0.0.1", "monitor-core"):
            settings.monitor_app_upstream = os.environ.get("MONITOR_APP_UPSTREAM", "adn-monitor")
        log = str(settings.adn_log_dir)
        if log.startswith("/var/log/") or not log:
            settings.adn_log_dir = settings.adn_root / "logs"
        docker_state = settings.adn_deploy_home / "install-docker" / "compose" / "state"
        if settings.adn_dmr_server_path and str(settings.adn_dmr_server_path).startswith(str(settings.adn_root)):
            docker_state = Path(str(settings.adn_dmr_server_path)).parent
        settings.adn_etc_root = docker_state / "etc"
    elif settings.has_sysroot():
        sysroot = Path(settings.adn_sysroot)
        settings.adn_etc_root = sysroot / "etc"
        log = str(settings.adn_log_dir)
        if log.startswith("/var/log/") or not log:
            settings.adn_log_dir = sysroot / "var/log/adn-server"
    elif settings.staging:
        if settings.filegen:
            settings.adn_etc_root = settings.adn_root / "etc"
        else:
            settings.adn_etc_root = settings.adn_root / "staging" / "etc"

    if settings.filegen:
        settings.adn_user = settings.adn_user or os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"
        log = str(settings.adn_log_dir)
        if log.startswith("/var/log/") or not log:
            if settings.has_sysroot():
                settings.adn_log_dir = Path(settings.adn_sysroot) / "var/log/adn-server"
            else:
                settings.adn_log_dir = settings.adn_root / "var/log/adn-server"
        settings.adn_deploy_skip_os_packages = "1"

    try:
        settings.adn_pyenv_python = settings.pyenv_python()
    except FileNotFoundError:
        settings.adn_pyenv_python = None

    settings.paths = DeployPaths.from_home(settings.adn_deploy_home)

    if dry_run:
        settings.adn_deploy_dry_run = "1"
    if profile:
        settings.adn_deploy_profile = profile
    if deploy_conf is not None:
        settings.adn_deploy_conf = deploy_conf.resolve()
        if settings.adn_deploy_conf.is_file():
            settings.apply_deploy_conf(parse_deploy_conf(settings.adn_deploy_conf))
    if non_interactive:
        settings.adn_deploy_non_interactive = "1"

    env_compose_file = os.environ.get("ADN_DOCKER_ENV_FILE", "").strip()
    if settings.docker and env_compose_file and Path(env_compose_file).is_file():
        settings.apply_deploy_conf(parse_deploy_conf(Path(env_compose_file)))

    apply_docker_cli_container_paths(settings)

    return settings


def require_settings(settings: Settings | None = None) -> Settings:
    return settings if settings is not None else init_env()
