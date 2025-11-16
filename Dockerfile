FROM python:3.13-alpine3.22
LABEL maintainer="Salvoxia <salvoxia@blindfish.info>"
ARG TARGETPLATFORM

# Latest releases available at https://github.com/aptible/supercronic/releases
ENV SUPERCRONIC_URL_BASE=https://github.com/aptible/supercronic/releases/download/v0.2.39/supercronic \
    SUPERCRONIC_SHA1SUM=c98bbf82c5f648aaac8708c182cc83046fe48423 \
    SUPERCRONIC_BASE=supercronic \
    CRONTAB_PATH=/tmp/crontab

COPY immich_auto_album.py requirements.txt docker/immich_auto_album.sh docker/setup_cron.sh /script/

# gcc and musl-dev are required for building requirements for regex python module
RUN case "${TARGETPLATFORM}" in \
         "linux/amd64")  SUPERCRONIC_URL=$SUPERCRONIC_URL_BASE-linux-amd64 SUPERCRONIC=$SUPERCRONIC_BASE-linux-amd64 ;; \
         "linux/arm64")  SUPERCRONIC_URL=$SUPERCRONIC_URL_BASE-linux-arm SUPERCRONIC=$SUPERCRONIC_BASE-linux-arm  ;; \
         "linux/arm/v7")  SUPERCRONIC_URL=$SUPERCRONIC_URL_BASE-linux-arm64 SUPERCRONIC=$SUPERCRONIC_BASE-linux-arm64  ;; \
         *) exit 1 ;; \
    esac; \
    if [ "$TARGETPLATFORM" = "linux/arm/v7" ]; then apk add gcc musl-dev; fi \
    && apk add tini curl \
    && pip install --no-cache-dir -r /script/requirements.txt \
    && chmod +x /script/setup_cron.sh /script/immich_auto_album.sh \
    && rm -rf /tmp/* /var/tmp/* /var/cache/apk/* /var/cache/distfiles/* \
    && if [ "$TARGETPLATFORM" = "linux/arm/v7" ]; then apk del gcc musl-dev; fi \
    && curl -fsSLO "$SUPERCRONIC_URL" \
    && echo "${SUPERCRONIC_SHA1SUM}  ${SUPERCRONIC}" | sha1sum -c - \
    && chmod +x "$SUPERCRONIC" \
    && mv "$SUPERCRONIC" "/usr/local/bin/${SUPERCRONIC}" \
    && ln -s "/usr/local/bin/${SUPERCRONIC}" /usr/local/bin/supercronic \
    && apk del curl

ENV IS_DOCKER=1
WORKDIR /script

USER 1000:1000

ENTRYPOINT ["tini", "-s", "-g", "--", "/script/setup_cron.sh"]
