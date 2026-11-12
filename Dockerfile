ARG N8N_VERSION=2.41.6
FROM docker.io/n8nio/n8n:${N8N_VERSION}

USER root

# Base image n8n 2.x (Docker Hardened Image / Alpine 3.24) tidak menyertakan apk.
# Bootstrap apk-tools-static dulu supaya bisa install Chromium dari repo Alpine 3.24.
RUN set -eux; \
    ARCH="$(uname -m)"; \
    BASE="https://dl-cdn.alpinelinux.org/alpine/v3.24"; \
    wget -qO /tmp/index.html "$BASE/main/$ARCH/"; \
    PKG="$(grep -oE 'apk-tools-static-[0-9][^"]+\.apk' /tmp/index.html | head -1)"; \
    wget -qO /tmp/apk-tools-static.apk "$BASE/main/$ARCH/$PKG"; \
    tar -xzf /tmp/apk-tools-static.apk -C /tmp; \
    mkdir -p /etc/apk /lib/apk/db; \
    /tmp/sbin/apk.static -X "$BASE/main" -U --allow-untrusted add apk-tools; \
    printf '%s\n' "$BASE/main" "$BASE/community" > /etc/apk/repositories; \
    apk add --no-cache --allow-untrusted alpine-keys; \
    apk add --no-cache chromium nss glib freetype harfbuzz ca-certificates ttf-freefont udev; \
    rm -rf /tmp/index.html /tmp/apk-tools-static.apk /tmp/sbin /var/cache/apk/*

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium-browser

USER node

# Bake community nodes into the image. On first run Docker seeds an empty
# n8n-data volume with this directory, so a fresh instance already has the
# Puppeteer node. --legacy-peer-deps avoids pulling n8n-workflow's native
# isolated-vm dependency (n8n provides it at runtime).
RUN mkdir -p /home/node/.n8n/nodes \
 && cd /home/node/.n8n/nodes \
 && echo '{"name":"installed-nodes","private":true}' > package.json \
 && npm install --legacy-peer-deps --no-audit --no-fund \
      n8n-nodes-puppeteer@1.5.0 \
      n8n-nodes-browseract@1.4.0 \
      puppeteer-extra-plugin-user-data-dir@^2.4.1 \
 && npm cache clean --force

# cloudflared Quick Tunnel: auto-create a free HTTPS tunnel (no token) and set
# WEBHOOK_URL at container start (needed for Telegram inline buttons).
USER root
RUN set -eux; \
    case "$(uname -m)" in x86_64) A=amd64;; aarch64) A=arm64;; *) echo unsupported; exit 1;; esac; \
    wget -qO /usr/local/bin/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$A"; \
    chmod +x /usr/local/bin/cloudflared
COPY tunnel-entrypoint.sh /tunnel-entrypoint.sh
RUN chmod +x /tunnel-entrypoint.sh
USER node
ENTRYPOINT ["tini", "--", "/tunnel-entrypoint.sh"]