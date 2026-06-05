#!/usr/bin/env bash
#
# install-vault.sh — Deploy the ICIT password vault (Passbolt CE) on the QNAP NAS.
# Single-shot: builds the compose stack, starts an ISOLATED MariaDB, waits for health,
# and creates the first admin user. Runs over SSH on the QNAP (Container Station).
#
# Architecture: cloudflared (existing) terminates TLS -> http://<nas>:HOST_HTTP_PORT -> container.
# Add the tunnel ingress rule AFTER this completes (printed at the end).
#
set -euo pipefail

# ============================ EDIT THESE ============================
PRODUCT_NAME="Iron Vault"                     # <- the single rebrand var (email From-name, etc.)
PUBLIC_URL="https://vault.ironcityit.com"     # public hostname served by your Cloudflare Tunnel
ADMIN_EMAIL="bill@ironcityit.com"             # first admin account
ADMIN_FIRST="Bill"
ADMIN_LAST="Laukaitis"

# --- Google Workspace SMTP (smtp.gmail.com) ---
SMTP_HOST="smtp.gmail.com"
SMTP_PORT="587"                               # STARTTLS — clean path for Passbolt/CakePHP
SMTP_USER="alerts@ironcityit.com"             # MUST be a real Google Workspace mailbox
SMTP_PASS="REPLACE_WITH_APP_PASSWORD_NO_SPACES"  # myaccount.google.com > Security > App passwords (2FA on)
MAIL_FROM="alerts@ironcityit.com"             # this mailbox, or a send-as alias it owns

# --- Local stack settings ---
HOST_HTTP_PORT="8088"                         # host port (QNAP reserves 80/443 for its UI — do NOT use those)
INSTALL_DIR="/share/Container/icit-vault"     # adjust if your Container share differs
PASSBOLT_TAG="5.10.0-1-ce"                     # pin a version; check hub.docker.com/r/passbolt/passbolt for newer
# ===================================================================

# Generated DB secrets (written once, reused on re-run)
mkdir -p "$INSTALL_DIR"
ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  DB_ROOT_PASS="$(openssl rand -hex 24)"
  DB_PASS="$(openssl rand -hex 24)"
  cat > "$ENV_FILE" <<EOF
DB_ROOT_PASS=${DB_ROOT_PASS}
DB_PASS=${DB_PASS}
EOF
  chmod 600 "$ENV_FILE"
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

# Pick the compose command available on this QNAP
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "ERROR: docker compose not found. Enable Container Station / install the compose plugin." >&2
  exit 1
fi

cat > "$INSTALL_DIR/docker-compose.yml" <<EOF
services:
  vault-db:
    image: mariadb:10.11
    container_name: icit-vault-db
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: "${DB_ROOT_PASS}"
      MYSQL_DATABASE: "vault"
      MYSQL_USER: "vault"
      MYSQL_PASSWORD: "${DB_PASS}"
    volumes:
      - vault_db:/var/lib/mysql
    networks:
      - vaultnet
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 5s
      retries: 12

  vault:
    image: passbolt/passbolt:${PASSBOLT_TAG}
    container_name: icit-vault
    restart: unless-stopped
    depends_on:
      vault-db:
        condition: service_healthy
    environment:
      APP_FULL_BASE_URL: "${PUBLIC_URL}"
      DATASOURCES_DEFAULT_HOST: "vault-db"
      DATASOURCES_DEFAULT_PORT: "3306"
      DATASOURCES_DEFAULT_USERNAME: "vault"
      DATASOURCES_DEFAULT_PASSWORD: "${DB_PASS}"
      DATASOURCES_DEFAULT_DATABASE: "vault"
      DATASOURCES_DEFAULT_SSL: "false"
      EMAIL_DEFAULT_FROM_NAME: "${PRODUCT_NAME}"
      EMAIL_DEFAULT_FROM: "${MAIL_FROM}"
      EMAIL_TRANSPORT_DEFAULT_HOST: "${SMTP_HOST}"
      EMAIL_TRANSPORT_DEFAULT_PORT: "${SMTP_PORT}"
      EMAIL_TRANSPORT_DEFAULT_USERNAME: "${SMTP_USER}"
      EMAIL_TRANSPORT_DEFAULT_PASSWORD: "${SMTP_PASS}"
      EMAIL_TRANSPORT_DEFAULT_TLS: "true"
      PASSBOLT_PLUGINS_JWT_AUTHENTICATION_ENABLED: "true"
    volumes:
      - vault_gpg:/etc/passbolt/gpg
      - vault_jwt:/etc/passbolt/jwt
    ports:
      - "${HOST_HTTP_PORT}:80"
    networks:
      - vaultnet

volumes:
  vault_db:
  vault_gpg:
  vault_jwt:

networks:
  vaultnet:
    driver: bridge
EOF

echo ">> Pulling images..."
$DC -f "$INSTALL_DIR/docker-compose.yml" pull

echo ">> Starting stack..."
$DC -f "$INSTALL_DIR/docker-compose.yml" up -d

echo ">> Waiting for the vault container to come up..."
for i in $(seq 1 30); do
  if docker exec icit-vault su -m -c "bin/cake passbolt healthcheck --database" -s /bin/sh www-data >/dev/null 2>&1; then
    break
  fi
  sleep 5
  [[ $i -eq 30 ]] && { echo "WARN: healthcheck not green yet — check logs: docker logs icit-vault"; }
done

echo ">> Creating first admin user (${ADMIN_EMAIL})..."
docker exec icit-vault su -m -c \
  "bin/cake passbolt register_user -u ${ADMIN_EMAIL} -f ${ADMIN_FIRST} -l ${ADMIN_LAST} -r admin" \
  -s /bin/sh www-data || \
  echo "(If this said the user exists, that's fine — re-run register only for new admins.)"

cat <<DONE

============================================================
${PRODUCT_NAME} is up on the NAS.

NEXT STEPS:
1) Add a Cloudflare Tunnel ingress rule:
     ${PUBLIC_URL}  ->  http://<NAS_LAN_IP>:${HOST_HTTP_PORT}
   (or http://localhost:${HOST_HTTP_PORT} if cloudflared runs on the NAS)

2) The register command above prints a setup URL. Open it in a fresh
   browser profile to install the extension and finish admin setup.

BACKUP (do this — losing vault_gpg = unrecoverable secrets):
   docker run --rm -v icit-vault_vault_gpg:/g -v "\$PWD":/b alpine \\
     tar czf /b/vault_gpg_\$(date +%F).tgz -C /g .
   docker run --rm -v icit-vault_vault_jwt:/j -v "\$PWD":/b alpine \\
     tar czf /b/vault_jwt_\$(date +%F).tgz -C /j .

DB creds are in ${ENV_FILE} (chmod 600).
============================================================
DONE
