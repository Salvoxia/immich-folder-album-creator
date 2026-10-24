FROM python:3.15.1-alpine3.24@sha256:d44b1254cb92329418d164b22b20d86bbd3869d48e80e09e476531a409a728bb
LABEL maintainer="Salvoxia <salvoxia@blindfish.info>"
ARG TARGETPLATFORM

# Latest releases available at https://github.com/aptible/supercronic/releases
ENV SUPERCRONIC_URL_BASE=https://github.com/aptible/supercronic/releases/download/v0.2.51/ \
    SUPERCRONIC_BASE=supercronic \
    CRONTAB_DIR=/script/cron \
    IS_DOCKER=1

COPY immich_auto_album.py requirements.txt docker/immich_auto_album.sh docker/setup_cron.sh docker/util.sh /script/

# gcc and musl-dev are required for building requirements for regex python module
RUN <<EOT
set -e
case "${TARGETPLATFORM}" in
     "linux/amd64")  SUPERCRONIC=$SUPERCRONIC_BASE-linux-amd64 SUPERCRONIC_SHA1SUM=1692066e350a88ff4d7d6474fe3c7a6c41ec5e89 ;;
     "linux/arm64")  SUPERCRONIC=$SUPERCRONIC_BASE-linux-arm64 SUPERCRONIC_SHA1SUM=9d4c2000493215a1898502b2fc2dada3e8ea8c7a ;;
     "linux/arm/v7")  SUPERCRONIC=$SUPERCRONIC_BASE-linux-arm SUPERCRONIC_SHA1SUM=9224966499cd319ed85759e9b6442f885d920c4f ;;
     *) exit 1 ;;
esac
[ "$TARGETPLATFORM" = "linux/arm/v7" ] && apk add gcc musl-dev
apk add tini curl
pip install --no-cache-dir -r /script/requirements.txt
chmod +x /script/setup_cron.sh /script/immich_auto_album.sh
rm -rf /tmp/* /var/tmp/* /var/cache/apk/* /var/cache/distfiles/*
[ "$TARGETPLATFORM" = "linux/arm/v7" ] && apk del gcc musl-dev
curl -fsSLO "${SUPERCRONIC_URL_BASE}${SUPERCRONIC}"
echo "${SUPERCRONIC_SHA1SUM}  ${SUPERCRONIC}" | sha1sum -c -
chmod +x "$SUPERCRONIC"
mv "$SUPERCRONIC" "/usr/local/bin/${SUPERCRONIC}"
ln -s "/usr/local/bin/${SUPERCRONIC}" /usr/local/bin/supercronic
apk del curl
# Prepare crontab
mkdir $CRONTAB_DIR
chmod 0777 $CRONTAB_DIR
EOT

WORKDIR /script

USER 1000:1000

ENTRYPOINT ["tini", "-s", "-g", "--", "/script/setup_cron.sh"]
