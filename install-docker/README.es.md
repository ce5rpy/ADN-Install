# Stack ADN en Docker — instalación de producción

[English](README.md) · **Español**

La instalación de producción **no** clona el toolkit en el host. Solo crea `/opt/adn-docker` y `/usr/local/sbin/adn-docker`. La parte Python/administración corre en **`adn-deploy-cli`**, que se descarga del registry.

**Acceso por defecto: solo HTTP** (`WEB_SSL=0`). HTTPS con `adn-docker menu` → ssl enable.

## Instalación

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

| Paso | Acción |
|------|--------|
| 1 | Instala Docker Engine (Debian) si falta |
| 2 | TUI de configuración obligatoria (SERVER_ID, título) |
| 3 | Crea `/opt/adn-docker/` — `docker-compose.yml`, `.env`, `deploy.conf`, `state/` |
| 4 | Instala `/usr/local/sbin/adn-docker` |
| 5 | Descarga las imágenes del stack, genera la configuración, `compose up -d` (HTTP :80) |

Valores fijos por defecto: `HBP_PASSPHRASE=passw0rd`, `WEB_SSL=0`.

Después de instalar:

```bash
adn-docker setup
adn-docker doctor
adn-docker menu
```

Sin terminal (por ejemplo, en automatización), define los valores obligatorios en lugar de usar `adn-docker setup`:

```bash
sudo adn-docker config set deploy ADN_SERVER_ID 73010
sudo adn-docker config set deploy ADN_DASHTITLE "Mi servidor"
sudo adn-docker config set deploy DAPRS_APRS_CALLSIGN N0CALL   # tu indicativo APRS
sudo adn-docker doctor
```

En Docker, `deploy.conf` es la fuente de verdad de estos valores: defínelos con `config set deploy …`. Los valores escritos directamente en los YAML de los servicios (`config set adn-server GLOBAL.SERVER_ID`, `config set monitor DASHBOARD.DASHTITLE`) se sobrescriben con `deploy.conf` en la siguiente sincronización.

## Estructura en el host

| Ruta | Función |
|------|---------|
| `/opt/adn-docker/docker-compose.yml` | Stack |
| `/opt/adn-docker/.env` | Contraseñas de MariaDB, tags de las imágenes |
| `/opt/adn-docker/deploy.conf` | Configuración de ejecución |
| `/opt/adn-docker/state/` | YAML de los servicios, traefik, logs |
| `/usr/local/sbin/adn-docker` | CLI del host |

## Imágenes y versiones

Las imágenes vienen de `docker.io/ce5rpy/*`. Cada imagen usa su propio tag, que se resuelve al instalar:

| Imagen | Tag | Override |
|--------|-----|----------|
| `adn-server` | Última release de ADN-DMR-Peer-Server | `DOCKER_TAG_SERVER` |
| `adn-monitor` | Última release de ADN-Monitor | `DOCKER_TAG_MONITOR` |
| `daprs` | `2.0.0` | `DOCKER_TAG_DAPRS` |
| `adn-deploy-cli` | Versión del toolkit | `DOCKER_TAG_DEPLOY_CLI` |

Para fijar una versión al instalar, por ejemplo: `sudo DOCKER_TAG_SERVER=2.5.5 bash docker-install.sh`. `DOCKER_REGISTRY` permite usar otro namespace de registry.

## Prueba con un registry local

Si las imágenes están en un registry privado (por ejemplo `127.0.0.1:5000/ce5rpy`):

```bash
sudo DOCKER_REGISTRY=127.0.0.1:5000/ce5rpy \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh)"
```

## Servicios

MariaDB, adn-server, adn-echo, adn-monitor (:8080), Traefik (:80), daprs (perfil `full`).

## Solución de problemas

| Problema | Solución |
|----------|----------|
| Reinstalar | `curl .../docker-install.sh \| sudo bash` |
| Stack con problemas de salud | `adn-docker ps` / `adn-docker logs adn-monitor` |
| HTTPS | `adn-docker menu` → ssl enable |
| Puerto 80 ya ocupado | Detén el otro servicio, o define `TRAEFIK_HTTP_PORT` en `/opt/adn-docker/.env` |

**Contraseña de MariaDB no coincide:** si cambiaron las contraseñas de `.env` después de la primera inicialización, elimina el volumen `adn_mariadb_data` y vuelve a instalar.
