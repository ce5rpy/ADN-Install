#!/usr/bin/env bash
# Bootstrap pyenv under $ADN_PYENV_ROOT and pip install -e adn-deploy (no system pip).
set -euo pipefail

: "${ADN_DEPLOY_HOME:?ADN_DEPLOY_HOME required}"

CONF="${ADN_DEPLOY_CONF:-$ADN_DEPLOY_HOME/deploy.conf}"
if [[ -f "$CONF" && -r "$CONF" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONF"
  set +a
fi

export ADN_ROOT="${ADN_ROOT:-/opt}"
export ADN_PYENV_ROOT="${ADN_PYENV_ROOT:-$ADN_ROOT/.pyenv}"
export ADN_PYTHON_VERSION="${ADN_PYTHON_VERSION:-3.13.14}"
export ADN_USER="${ADN_USER:-adn}"
export ADN_USER_HOME="${ADN_USER_HOME:-/home/$ADN_USER}"

# shellcheck disable=SC1091
source "$ADN_DEPLOY_HOME/scripts/bootstrap_pyenv.sh"
