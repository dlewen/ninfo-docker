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

## SSO Authentication (OIDC)

ninfo supports Single Sign-On via any OIDC-compliant provider (Keycloak, Azure Entra ID, etc.). When OIDC is not configured, the app falls back to standard Django username/password authentication.

To enable OIDC, add these environment variables to your `.env` file:

```bash
# Required OIDC settings
OIDC_RP_CLIENT_ID=your-client-id
OIDC_RP_CLIENT_SECRET=your-client-secret
OIDC_OP_AUTHORIZATION_ENDPOINT=https://...
OIDC_OP_TOKEN_ENDPOINT=https://...
OIDC_OP_USER_ENDPOINT=https://...
OIDC_OP_JWKS_ENDPOINT=https://...

# Optional: enables single sign-out (redirects to IdP on logout)
OIDC_OP_END_SESSION_ENDPOINT=https://...
```

### Keycloak Example

Replace `keycloak.example.com` with your Keycloak host and `myrealm` with your realm name.

```bash
OIDC_RP_CLIENT_ID=ninfo
OIDC_RP_CLIENT_SECRET=your-client-secret-from-keycloak
OIDC_OP_AUTHORIZATION_ENDPOINT=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/auth
OIDC_OP_TOKEN_ENDPOINT=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/token
OIDC_OP_USER_ENDPOINT=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/userinfo
OIDC_OP_JWKS_ENDPOINT=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
OIDC_OP_END_SESSION_ENDPOINT=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/logout
```

Keycloak client setup:
1. Create a new client in your realm with Client ID `ninfo`
2. Set **Client authentication** to `On` (confidential)
3. Set **Valid redirect URIs** to `https://ninfo.example.com/oidc/callback/`
4. Set **Valid post logout redirect URIs** to `https://ninfo.example.com/`
5. Copy the client secret from the **Credentials** tab

### Azure Entra ID Example

Replace `your-tenant-id` with your Azure AD tenant ID.

```bash
OIDC_RP_CLIENT_ID=your-application-client-id
OIDC_RP_CLIENT_SECRET=your-client-secret-value
OIDC_OP_AUTHORIZATION_ENDPOINT=https://login.microsoftonline.com/your-tenant-id/oauth2/v2.0/authorize
OIDC_OP_TOKEN_ENDPOINT=https://login.microsoftonline.com/your-tenant-id/oauth2/v2.0/token
OIDC_OP_USER_ENDPOINT=https://graph.microsoft.com/oidc/userinfo
OIDC_OP_JWKS_ENDPOINT=https://login.microsoftonline.com/your-tenant-id/discovery/v2.0/keys
OIDC_OP_END_SESSION_ENDPOINT=https://login.microsoftonline.com/your-tenant-id/oauth2/v2.0/logout
```

Azure Entra app registration:
1. In Azure Portal, go to **App registrations** and create a new registration
2. Set **Redirect URI** (Web) to `https://ninfo.example.com/oidc/callback/`
3. Under **Certificates & secrets**, create a new client secret
4. Under **API permissions**, ensure `openid`, `profile`, and `email` are granted
5. Under **Authentication**, set **Front-channel logout URL** to `https://ninfo.example.com/`

### Disabling OIDC

Simply remove or comment out the `OIDC_RP_CLIENT_ID` variable from `.env`. The app automatically falls back to the Django login form. The local admin account (from `DJANGO_SUPERUSER_*` variables) always works regardless of OIDC configuration.

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
