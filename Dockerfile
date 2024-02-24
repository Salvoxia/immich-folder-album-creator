FROM python:3.12-alpine
LABEL maintainer="Salvoxia <salvoxia@blindfish.info>"

COPY immich_auto_album.py requirements.txt docker/immich_auto_album.sh docker/setup_cron.sh /script/

RUN pip install --no-cache-dir -r /script/requirements.txt \
    && chmod +x /script/setup_cron.sh /script/immich_auto_album.sh \
    && rm -rf /tmp/* /var/tmp/* /var/cache/apk/* /var/cache/distfiles/*

WORKDIR /script
CMD ["sh", "-c", "/script/setup_cron.sh && crond -f"]