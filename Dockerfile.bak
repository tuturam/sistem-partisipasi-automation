FROM docker.n8n.io/n8nio/n8n

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
