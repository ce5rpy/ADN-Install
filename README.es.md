# ADN-Install

[English](README.md) · **Español**

Instala un servidor DMR de ADN: el servidor DMR, el panel web y la pasarela para apps de móvil.

Aquí está todo lo necesario. Para fijar versiones, variables y otros detalles, consulta la [guía avanzada](README.advanced.es.md).

## Qué necesitas

- Un servidor o VM con **Debian 13** o **Ubuntu 22.04 o posterior**, recién instalado.
- Acceso como **root** (o un usuario con `sudo`).
- Tu **Server ID** y el **nombre** que quieres en el panel.

## Instalar

Elige **una** de las dos opciones. Si no estás seguro, elige **Docker**.

**Opción A — Docker (recomendada):**

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

**Opción B — Bare metal (sin Docker):**

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo bash
```

Al final, el instalador pide tu Server ID y el nombre del panel. Si no los pidió (por ejemplo, porque se ejecutó sin terminal), ejecuta:

```bash
sudo adn-docker setup     # Docker
sudo adn-deploy wizard    # Bare metal
```

## Comprobar que funciona

```bash
sudo adn-docker doctor    # Docker
sudo adn-deploy doctor    # Bare metal
```

Debe terminar con `Doctor: OK`. Después abre `http://<ip-de-tu-servidor>/` en el navegador para ver el panel.

## Abre estos puertos

Si tu servidor o tu proveedor cloud tiene cortafuegos, abre:

| Puerto | Para |
|--------|------|
| `80/tcp`, `443/tcp` | Panel web |
| `62031/udp` | Hotspots |
| `62032/udp` | Enlaces OpenBridge con otros servidores |
| `54006/udp` | Apps de móvil y terminales IP (ODTP) |

## Conectar con el panel ADN

Para que el panel ADN muestre tu servidor (versión, puertos, enlaces, ODTP), genera un **token** en la página de tu servidor del panel de sysops; el panel también muestra el **endpoint**. Después:

```bash
sudo adn-docker menu      # Docker
sudo adn-deploy menu      # Bare metal
```

Entra en **Server (DMR peer) → Configure → Change a variable**, completa `ADN_PANEL.ENDPOINT` y `ADN_PANEL.TOKEN`, y después vuelve atrás y elige **Restart container** (Docker) o **Reload config** (bare metal). El puerto ODTP se completa solo.

## Actualizar

**Docker:**

```bash
sudo adn-docker update
```

**Bare metal:**

```bash
sudo adn-deploy update
```

Tu configuración se conserva.

### Actualizar de 2.6 a 2.7

La versión 2.7 agrega la pasarela para apps de móvil (ODTP). Para actualizar desde 2.6 hay que seguir estos pasos **una sola vez**:

**Docker** — vuelve a ejecutar el instalador (tu configuración y tus contraseñas se conservan):

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

**Bare metal** — ejecuta estos dos comandos, en este orden:

```bash
sudo adn-deploy update --toolkit
sudo adn-deploy update
```

Después abre `54006/udp` en tu cortafuegos.

## Menú de administración

```bash
sudo adn-docker menu      # Docker
sudo adn-deploy menu      # Bare metal
```

## ¿Algo no funciona?

1. Ejecuta `doctor` (ver arriba) y lee las líneas que dicen `WARN` o `ERROR`.
2. Comprueba que los puertos estén abiertos.
3. Consulta la [guía avanzada](README.advanced.es.md) y, para Docker, [install-docker/README.es.md](install-docker/README.es.md).
