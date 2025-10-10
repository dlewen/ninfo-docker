# Architecture

## Components

- **ninfo-www** - Django application running with Gunicorn on port 8000
- **nginx** - Reverse proxy serving static files and forwarding to Django
- **Traefik** (external) - SSL/TLS termination and routing

## Network Configuration

### Networks

- `ninfo` - Internal network (Django ↔ Nginx)
- `web` - External network (Traefik ↔ Nginx)

### Traffic Flow

```
Internet → Traefik (web network) → Nginx (port 80) → Django (port 8000)
```

The application doesn't expose ports directly to the host. All traffic routes through Traefik on the external `web` network.

## Volumes

| Volume | Purpose |
|--------|---------|
| `static_volume` | Django static files (shared with Nginx) |
| `django_db` | SQLite database persistence |
| `./ninfo/ninfo.ini` | NInfo configuration (bind mount) |
| `./nginx/logs` | Nginx access/error logs (bind mount) |

## Build Process

The Dockerfile uses a multi-stage build:

1. **Builder stage**
   - Clones ninfo and django-ninfo repositories
   - Clones plugin repositories from `CUSTOM_GIT_REPOS`
   - Copies local plugins from `build/local_plugins/`
   - Builds Python wheels for all packages

2. **Runtime stage**
   - Creates non-root user `ninfo` (UID 30002)
   - Installs wheels from builder stage
   - Collects Django static files
   - Runs entrypoint script on startup

## Entrypoint Process

On container startup (`entrypoint.sh`):
1. Run Django migrations
2. Create superuser if it doesn't exist
3. Update superuser password to match `DJANGO_SUPERUSER_PASSWORD`
4. Start Gunicorn with 3 workers

## Security

- Application runs as non-root user `ninfo` (UID 30002)
- No ports exposed directly to host
- All external traffic through Traefik with TLS
- Secret key and passwords configured via environment variables
