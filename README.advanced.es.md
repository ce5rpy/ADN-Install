# ADN-Install — avanzado

[English](README.advanced.md) · **Español**

Referencia completa de los instaladores ADN: fijación de versiones, variables, comandos y estructura. Para una instalación rápida, consulta [README.es.md](README.es.md).

## Versiones: estable, develop o una versión concreta

**Actualiza siempre primero el toolkit.** El comando `version` y las variables de abajo necesitan un toolkit reciente; con uno antiguo no hacen nada:

```bash
sudo adn-deploy update --toolkit   # bare metal
sudo adn-docker update             # Docker (también actualiza adn-docker)
```

El servidor DMR (`adn-server`) y el monitor (`adn-monitor`) usan **las mismas variables y valores en bare metal y en Docker**:

| Variable | Se aplica a |
|----------|-------------|
| `ADN_VERSION` | las dos aplicaciones |
| `ADN_SERVER_VERSION` | solo adn-server (tiene prioridad sobre `ADN_VERSION`) |
| `ADN_MONITOR_VERSION` | solo adn-monitor (tiene prioridad sobre `ADN_VERSION`) |

| Valor | Significado | Bare metal (git) | Docker (imagen) |
|-------|-------------|------------------|-----------------|
| `stable` (por defecto) | última versión publicada | `master` | `:latest` |
| `develop` | próxima versión, **solo para pruebas** | `develop` | `:develop` |
| `X.Y.Z`, p. ej. `2.7.0` | una versión concreta, para subir o bajar | tag `vX.Y.Z` | `:X.Y.Z` |

Se guardan en `/opt/ADN-Install/deploy.conf` (bare metal) o `/opt/adn-docker/.env` (Docker).

**Instalación nueva en una versión** — agrega la variable al comando de instalación:

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo env ADN_VERSION=develop bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo env ADN_VERSION=develop bash
```

**Servidor ya instalado** — el mismo comando en ambos (`adn-deploy` en bare metal, `adn-docker` en Docker):

```bash
sudo adn-deploy version                  # muestra las versiones actuales
sudo adn-deploy version develop          # las dos aplicaciones a develop
sudo adn-deploy version 2.6.1            # las dos a 2.6.1 (bajar de versión)
sudo adn-deploy version --server 2.7.0   # solo una aplicación (o --monitor)
sudo adn-deploy version stable           # volver a la última versión publicada
```

El comando comprueba que la versión existe (tag o rama de git, o imagen Docker) antes de cambiar nada, la guarda y ejecuta la actualización. A partir de ahí, cada `update` se queda en esa versión (`develop` pasa a su último commit o imagen).

- **La configuración se conserva.** En bare metal, `adn-server.yaml`, `adn-echo.yaml`, `adn-monitor.yaml`, `.env` y los archivos de configuración/datos de D-APRS se respaldan en `/opt/adn-backups/<repo>-<fecha>/` (solo root) antes de cada cambio y se restauran después. `SERVER_ID` y la configuración de seguridad nunca se reinician. Si se editaron a mano archivos versionados de un repo de aplicación, la actualización se detiene para ese repo: haz commit o stash de esos cambios primero.
- **ODTP** (`adn-odtp`) existe desde adn-server 2.7.0. Con un servidor anterior se detiene, y `doctor` avisa de que no está corriendo.
- **Las imágenes `develop`** se reconstruyen con cada cambio en `develop`; cada build queda también disponible como `:develop-<commit>` (por ejemplo `adn-server:develop-c0f9f64`).
- **Variables anteriores** — `GIT_BRANCH_PEER` / `GIT_BRANCH_MONITOR` (bare metal) y `DOCKER_TAG_SERVER` / `DOCKER_TAG_MONITOR` (Docker) — siguen funcionando mientras no haya ninguna `ADN_*_VERSION`. El comando `version` las reemplaza.
- **El toolkit** (`/opt/ADN-Install`) sigue siempre `master`. Para fijarlo al instalar: `ADN_DEPLOY_REF` (rama, tag o commit).

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

### Variables

| Variable | Por defecto | Cuándo usarla |
|----------|-------------|---------------|
| `ADN_DEPLOY_REF` | `master` | Fijar el toolkit `ADN-Install` en una rama, tag (`v2.7.0`) o commit |
| `ADN_INSTALL_REF` | *(usa `ADN_DEPLOY_REF`)* | Igual que la anterior; tiene prioridad si ambas están definidas |
| `ADN_VERSION`, `ADN_SERVER_VERSION`, `ADN_MONITOR_VERSION` | `stable` | Versiones de las aplicaciones: `stable`, `develop` o `X.Y.Z` — ver [Versiones](#versiones-estable-develop-o-una-versión-concreta) |
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
| `adn-deploy update` | Actualiza el toolkit y los repos de las aplicaciones a las versiones configuradas, conserva la configuración y reinicia |
| `adn-deploy update --toolkit` | Actualiza solo el toolkit (hazlo primero) |
| `adn-deploy version [stable\|develop\|X.Y.Z]` | Muestra o cambia las versiones de las aplicaciones y actualiza ([Versiones](#versiones-estable-develop-o-una-versión-concreta)) |
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
| `adn-dmr-server/` | Amateur-Digital-Network/ADN-DMR-Peer-Server | `ADN_SERVER_VERSION` |
| `adn-monitor/` | Amateur-Digital-Network/ADN-Monitor | `ADN_MONITOR_VERSION` |
| `ADN-Install/` | ce5rpy/ADN-Install (toolkit en `/opt/ADN-Install`) | `ADN_DEPLOY_REF` al momento de instalar |
