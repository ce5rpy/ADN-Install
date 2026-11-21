# Changelog

All notable changes to **ADN-Install** (adn-deploy toolkit) are documented here.

<!-- version list -->

## v2.9.0 (2026-11-21)

### Features

- **version**: One way to choose app versions on bare metal and Docker


## v2.8.4 (2026-11-21)

### Bug Fixes

- **docs**: Install the development version (develop)


## v2.8.3 (2026-11-21)

### Bug Fixes

- **ci**: Actions on Node 24; ADN-Install manual releases keep Latest


## v2.8.2 (2026-11-21)

### Bug Fixes

- **release**: Publish daprs too, push the release tag with retries, ADN-Install versions itself


## v2.8.1 (2026-11-21)

### Bug Fixes

- **update**: Toolkit update no longer stops on root-owned or locally changed files


## v2.8.0 (2026-11-20)

### Features

- **menu**: ADN panel endpoint and token in the menu; ODTP port filled in


## v2.7.2 (2026-11-20)

### Bug Fixes

- **docker**: Adn-docker update also pulls the adn-deploy-cli image


## v2.7.1 (2026-11-19)

### Bug Fixes

- **docker**: Adn-docker update refreshes the compose file and itself

- **update**: Continue with the new toolkit code after a self-update

### Documentation

- Basic and advanced install READMEs; 2.6 to 2.7 upgrade steps


## v2.7.0 (2026-11-18)

### Bug Fixes

- **config**: Keep numeric types in config set

### Features

- **odtp**: ODTP gateway service for server 2.7


## v2.6.0 (2026-10-15)

### Bug Fixes

- **config**: Config set keeps deploy.conf and gps_data.cfg in step

### Continuous Integration

- Release PR merge-method check and incremental changelog

- Release with semantic-release, publish adn-deploy-cli, sync ADN-Install

- Skip publish jobs while their secrets are missing

### Features

- **docker**: Adn-docker update

- **update**: Toolkit self-update follows origin even after history rewrites

### Testing

