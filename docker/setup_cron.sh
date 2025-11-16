#!/usr/bin/env sh
if [ ! -z "$CRON_EXPRESSION" ]; then
    echo "$CRON_EXPRESSION UNATTENDED=1 /script/immich_auto_album.sh > /proc/1/fd/1 2>/proc/1/fd/2" > $CRONTAB_PATH
    if [ "$LOG_LEVEL" == "DEBUG" ]; then
        $DEBUG_PARM=-debug
    fi
    /usr/local/bin/supercronic $DEBUGPARM $CRONTAB_PATH
else
    UNATTENDED=1 /script/immich_auto_album.sh > /proc/1/fd/1 2>/proc/1/fd/2 || true
fi
