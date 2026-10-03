# ADN-Install

[English](README.md) · **Español**

Instaladores públicos del stack ADN de **ce5rpy** (servidor DMR peer + monitor unificado en Python).

**Ramas:** `develop` (trabajo diario) · `master` (release). Las URLs de instalación con curl usan `master`.

## Instalación bare metal

En una VM nueva con Debian 13 o Ubuntu 22.04+, como **root**:

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo bash
```

El instalador corre como root y, por defecto, crea la cuenta Linux **`adn`** (pyenv, clones git, dueño de los servicios). Si `adn` ya existe, no se modifica y no se pide contraseña.

**VM nueva — definir la contraseña de login del nuevo usuario `adn`** (solo no interactivo / CI):

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh \
  | sudo ADN_USER_PASSWORD='tu_contraseña' bash
```

Instalación interactiva (terminal normal): si `adn` no existe y `ADN_USER_PASSWORD` no está definida, la fase `[1/6]` pide la contraseña en `/dev/tty`.

O desde un clon local:

```bash
cd /opt/ADN-Install
sudo bash install.sh
```

Fijar la rama del toolkit (`ADN-Install` en `/opt/ADN-Install`):

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh \
  | sudo ADN_DEPLOY_REF=master bash
```

`ADN_INSTALL_REF` tiene prioridad sobre `ADN_DEPLOY_REF` cuando ambas están definidas.

### Instalación bare metal (rama `develop`)

Bare metal usa **dos fijaciones de rama independientes**:

| Qué se clona | Ruta | Variable de rama | Por defecto |
|--------------|------|------------------|-------------|
| Toolkit instalador | `/opt/ADN-Install` | `ADN_DEPLOY_REF` o `ADN_INSTALL_REF` | `master` |
| Servidor DMR peer | `/opt/adn-dmr-server` | `GIT_BRANCH_PEER` en `deploy.conf` (rama, tag o commit) | rama por defecto del remoto (`master`) |
| Monitor | `/opt/adn-monitor` | `GIT_BRANCH_MONITOR` en `deploy.conf` (rama, tag o commit) | rama por defecto del remoto (`master`) |

`ADN_DEPLOY_REF=develop` solo fija el **toolkit**. Los repos de las aplicaciones se siguen clonando desde `master` salvo que definas `GIT_BRANCH_PEER` / `GIT_BRANCH_MONITOR` en `deploy.conf`.

**Recomendado — instalación completa en `develop` (3 pasos):**

```bash
# 1) Preparar el toolkit desde develop (se detiene antes de clonar el stack)
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/develop/install.sh \
  | sudo env ADN_DEPLOY_REF=develop ADN_DEPLOY_BOOTSTRAP_ONLY=1 bash

# 2) Fijar los repos de las aplicaciones en develop
sudo tee -a /opt/ADN-Install/deploy.conf <<'EOF'
GIT_BRANCH_PEER="develop"
GIT_BRANCH_MONITOR="develop"
EOF

# 3) Completar la instalación (SO, pyenv, stack, asistente, servicios)
sudo bash /opt/ADN-Install/install/install.sh
```

**Clon local en `develop`:**

```bash
cd /opt/ADN-Install   # git checkout develop
sudo tee -a deploy.conf <<'EOF'
GIT_BRANCH_PEER="develop"
GIT_BRANCH_MONITOR="develop"
EOF
sudo ADN_DEPLOY_REF=develop bash install.sh
```

**Ya instalado — actualizar o cambiar de versión:**

`adn-deploy update` (o volver a ejecutar el instalador) actualiza en el lugar los repos de las aplicaciones a la referencia definida en `deploy.conf`: una rama, un tag de release o un commit. Sin `GIT_BRANCH_*` siguen `master`.

```bash
sudo tee -a /opt/ADN-Install/deploy.conf <<'EOF'
GIT_BRANCH_PEER="v2.5.6"
GIT_BRANCH_MONITOR="v2.5.3"
EOF
sudo adn-deploy update    # fetch + checkout, pip, reinicio de servicios
```

- La configuración local se conserva: `adn-server.yaml`, `adn-echo.yaml`, `adn-monitor.yaml`, `.env` y los archivos de configuración y datos de D-APRS se respaldan en `/opt/adn-backups/<repo>-<fecha>/` (solo root) antes de cada cambio y se restauran después. Una actualización nunca reinicia `SERVER_ID` ni la configuración de seguridad.
- Si se editaron a mano archivos versionados de un repo de aplicación, la actualización se detiene para ese repo: primero haz commit o stash de esos cambios.

| Variable | Por defecto | Cuándo usarla |
|----------|-------------|---------------|
| `ADN_DEPLOY_REF` | `master` | Fijar la rama del toolkit `ADN-Install` (`develop`, tag, SHA) |
| `ADN_INSTALL_REF` | *(usa `ADN_DEPLOY_REF`)* | Igual que la anterior; tiene prioridad si ambas están definidas |
| `GIT_BRANCH_PEER` | *(sin definir → rama por defecto del remoto)* | En `deploy.conf`, para instalar/actualizar `adn-dmr-server` en una rama, tag (`v2.5.6`) o commit |
| `GIT_BRANCH_MONITOR` | *(sin definir → rama por defecto del remoto)* | En `deploy.conf`, para instalar/actualizar `adn-monitor` en una rama, tag (`v2.5.3`) o commit |
| `ADN_DEPLOY_BOOTSTRAP_ONLY` | `0` | `1` = solo clonar el toolkit; luego editar `deploy.conf` antes de volver a ejecutar la instalación |
| `ADN_USER` | `adn` | Cambiar el nombre del usuario Linux |
| `ADN_USER_PASSWORD` | *(sin definir)* | Solo al **crear** `adn` sin pedir la contraseña por TTY |
| `ADN_CREATE_USER=0` | crear usuario | Usar un usuario existente; debe existir previamente |
| `ADN_DEPLOY_STAGING=1` | desactivado | Instalación de staging bajo otro `ADN_ROOT` (sin apt/systemd/nginx a nivel de sistema) |

Después de instalar: `adn-deploy menu`, `adn-deploy doctor`, `adn-deploy service start`.

## Instalación Docker (producción)

**No** clona este repo en el host. Crea `/opt/adn-docker` y `/usr/local/sbin/adn-docker`. Las imágenes vienen de `docker.io/ce5rpy/*`, cada una en la última release de su componente.

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

Después de instalar:

```bash
adn-docker setup    # si se omitió el asistente
adn-docker doctor
adn-docker menu     # ssl enable cuando esté listo
```

Ver [install-docker/README.es.md](install-docker/README.es.md) para la estructura en el host y la solución de problemas.

## Arquitectura (bare metal)

| Componente | Función |
|------------|---------|
| **adn-server** | DMR peer + proxy de hotspots integrado |
| **adn-monitor** | FastAPI: REST `/api/*`, WebSocket `/ws` |
| **nginx** | TLS + SPA estática |
| **MariaDB** | Base de datos de login self-service |

## Comandos

| Comando | Descripción |
|---------|-------------|
| `adn-deploy install` | Instalación completa |
| `adn-deploy update` | Actualiza el toolkit y los repos de las aplicaciones a las referencias configuradas, conserva la configuración y reinicia |
| `adn-deploy menu` | Menú de administración (Textual) |
| `adn-deploy doctor` | Chequeos de salud |
| `adn-deploy stack` | git, configuración, systemd, web |

## Estructura

- `install.sh` — arranque bare metal (`curl | bash`)
- `docker-install.sh` — instalación Docker de producción (`curl | bash`)
- `sbin/adn-deploy` — wrapper del CLI (Python de pyenv)
- `src/adn_deploy/` — toolkit en Python
- `install-docker/` — solo scripts de instalación del runtime Docker (sin build)

## Repos clonados bajo `$ADN_ROOT`

| Ruta | GitHub | Rama (`deploy.conf`) |
|------|--------|----------------------|
| `adn-dmr-server/` | Amateur-Digital-Network/ADN-DMR-Peer-Server | `GIT_BRANCH_PEER` |
| `adn-monitor/` | Amateur-Digital-Network/ADN-Monitor | `GIT_BRANCH_MONITOR` |
| `ADN-Install/` | ce5rpy/ADN-Install (toolkit en `/opt/ADN-Install`) | `ADN_DEPLOY_REF` al momento de instalar |
