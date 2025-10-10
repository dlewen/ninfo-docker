# NInfo Docker Template

Docker template for deploying [ninfo](https://github.com/ninfo-py/ninfo) with a custom-styled Django web interface using [django-ninfo](https://github.com/dlewen/django-ninfo).

## Prerequisites

- Docker and Docker Compose
- Running Traefik container with external `web` network:
  ```bash
  docker network create web
  ```

## Quick Start

1. **Configure environment**
   ```bash
   cp template.env .env
   # Edit .env - update domain, credentials, and secret key
   ```

2. **Configure Docker Compose**
   ```bash
   cp docker-compose.yml.template docker-compose.yml
   # Edit docker-compose.yml - update Traefik labels with your domain
   ```

3. **Configure NInfo**
   ```bash
   nano ninfo/ninfo.ini
   # Configure plugins and settings
   ```

4. **Deploy**
   ```bash
   docker-compose up -d --build
   ```

Access your instance at your configured domain. Admin panel: `/admin`

## Configuration

### Environment Variables (.env)

Required settings:
- `DJANGO_ALLOWED_HOSTS` - Your domain name
- `DJANGO_SUPERUSER_USERNAME` - Admin username
- `DJANGO_SUPERUSER_PASSWORD` - Admin password (change default!)
- `DJANGO_SUPERUSER_EMAIL` - Admin email
- `DJANGO_SECRET_KEY` - Django secret key (change default!)
- `DJANGO_DEBUG` - Set to `False` in production
- `CUSTOM_GIT_REPOS` - Comma-separated plugin git repositories

### Traefik Labels (docker-compose.yml)

Update these labels with your domain:
```yaml
- "traefik.http.routers.ninfo.rule=Host(`ninfo.example.com`)"
- "traefik.http.routers.ninfo.tls.domains[0].main=ninfo.example.com"
```

Adjust `certresolver` as needed for your Traefik setup.

## Plugins

### Default Plugins

Included in `template.env`:
- **cymruwhois** - Team Cymru WHOIS lookups
- **shodan-internetdb** - Shodan InternetDB integration

### Adding Plugins

**Git repositories:**
```bash
# In .env
CUSTOM_GIT_REPOS="https://github.com/user/plugin1.git,https://github.com/user/plugin2.git"
```

**Local development:**
Place plugins in `build/local_plugins/`

Rebuild after adding plugins: `docker-compose up -d --build`

## Troubleshooting

**Container won't start**
```bash
docker-compose logs ninfo-www
```

**Can't access application**
- Verify Traefik is running and `web` network exists
- Check Traefik can reach nginx container
- Review Traefik logs for routing issues

**Database issues**
```bash
docker-compose down
docker volume rm ninfo-docker_django_db
docker-compose up -d
```

## Documentation

- [Architecture](ARCHITECTURE.md) - Detailed architecture and network configuration
- [ninfo](https://github.com/ninfo-py/ninfo) - Core library documentation

## License

See [LICENSE](LICENSE) file.
