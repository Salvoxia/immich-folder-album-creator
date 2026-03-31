FROM python:3.13-alpine3.22
LABEL maintainer="Salvoxia <salvoxia@blindfish.info>"
ARG TARGETPLATFORM

# Latest releases available at https://github.com/aptible/supercronic/releases
ENV SUPERCRONIC_URL_BASE=https://github.com/aptible/supercronic/releases/download/v0.2.43/ \
    SUPERCRONIC_BASE=supercronic \
    CRONTAB_DIR=/script/cron \
    IS_DOCKER=1

COPY immich_auto_album.py requirements.txt docker/immich_auto_album.sh docker/setup_cron.sh /script/

# gcc and musl-dev are required for building requirements for regex python module
RUN <<EOT
set -e
case "${TARGETPLATFORM}" in
     "linux/amd64")  SUPERCRONIC=$SUPERCRONIC_BASE-linux-amd64 SUPERCRONIC_SHA1SUM=f97b92132b61a8f827c3faf67106dc0e4467ccf2 ;;
     "linux/arm64")  SUPERCRONIC=$SUPERCRONIC_BASE-linux-arm64 SUPERCRONIC_SHA1SUM=5c6266786c2813d6f8a99965d84452faae42b483 ;;
     "linux/arm/v7")  SUPERCRONIC=$SUPERCRONIC_BASE-linux-arm SUPERCRONIC_SHA1SUM=9d222afc7875bff33bb3623dd88b390f51d9d81e ;;
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
