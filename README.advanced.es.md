# ADN-Install — avanzado

[English](README.advanced.md) · **Español**

Referencia completa de los instaladores ADN: fijación de versiones, variables, comandos y estructura. Para una instalación rápida, consulta [README.es.md](README.es.md).

## Actualizar de 2.6 a 2.7

La versión 2.7 agrega la pasarela ODTP (`adn-odtp`, UDP `54006`) para apps de móvil y terminales IP.

**Bare metal** — actualiza primero el toolkit y después el resto, para que el segundo comando ya corra con el toolkit 2.7:

```bash
sudo adn-deploy update --toolkit   # solo el toolkit
sudo adn-deploy update             # adn-server / adn-monitor 2.7, agrega adn-odtp
sudo adn-deploy doctor
```

Si `deploy.conf` fija `GIT_BRANCH_PEER` / `GIT_BRANCH_MONITOR` en versiones anteriores, cámbialas a `v2.7.0` (o elimínalas) antes del segundo comando.

**Docker** — vuelve a ejecutar el instalador. Renueva `docker-compose.yml` y `adn-docker` (que agregan el servicio `adn-odtp`), conserva `.env`, las contraseñas y `state/`, y descarga las imágenes 2.7:

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
sudo adn-docker doctor
```

En ambos casos, abre `54006/udp` en el cortafuegos para que las apps puedan conectarse.

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

### Versiones

Por defecto todo se instala desde `master`, que siempre tiene la última release, igual que la instalación Docker. Hay tres fijaciones independientes, todas opcionales:

| Qué se clona | Ruta | Fijación | Por defecto |
|--------------|------|----------|-------------|
| Toolkit instalador | `/opt/ADN-Install` | `ADN_DEPLOY_REF` o `ADN_INSTALL_REF` (entorno) | `master` |
| Servidor DMR peer | `/opt/adn-dmr-server` | `GIT_BRANCH_PEER` en `deploy.conf` (rama, tag o commit) | rama por defecto del remoto (`master`) |
| Monitor | `/opt/adn-monitor` | `GIT_BRANCH_MONITOR` en `deploy.conf` (rama, tag o commit) | rama por defecto del remoto (`master`) |

`ADN_INSTALL_REF` tiene prioridad sobre `ADN_DEPLOY_REF` cuando ambas están definidas.

**Instalar versiones específicas de las aplicaciones** (2 pasos):

```bash
# 1) Preparar solo el toolkit (se detiene antes de clonar las aplicaciones)
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh \
  | sudo env ADN_DEPLOY_BOOTSTRAP_ONLY=1 bash

# 2) Fijar las versiones de las aplicaciones y completar la instalación (SO, pyenv, stack, asistente, servicios)
sudo tee -a /opt/ADN-Install/deploy.conf <<'EOF'
GIT_BRANCH_PEER="v2.7.0"
GIT_BRANCH_MONITOR="v2.7.0"
EOF
sudo bash /opt/ADN-Install/install/install.sh
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
| `ADN_DEPLOY_REF` | `master` | Fijar el toolkit `ADN-Install` en una rama, tag (`v2.7.0`) o commit |
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
| **adn-odtp** | Pasarela ODTP (servidor ≥ 2.7): las apps de móvil y terminales IP entran como peers. UDP `54006` (`ODTP.LISTEN_PORT` en `adn-odtp.yaml`); ábrelo en el cortafuegos |
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
