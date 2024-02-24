#!/usr/bin/env sh

if [ ! -z "$CRON_EXPRESSION" ]; then
    (crontab -l 2>/dev/null; echo "$CRON_EXPRESSION /script/immich_auto_album.sh > /proc/1/fd/1 2>/proc/1/fd/2") | crontab -
    # Make environment variables accessible to cron
    printenv > /etc/environment
fi