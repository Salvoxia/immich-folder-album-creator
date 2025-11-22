#!/usr/bin/env sh
if [ ! -z "$CRON_EXPRESSION" ]; then
    CRONTAB_PATH="$CRONTAB_DIR/crontab"
    # Create and lock down crontab
    touch "$CRONTAB_PATH"
    chmod 0600 "$CRONTAB_PATH"
    # populate crontab
    echo "$CRON_EXPRESSION UNATTENDED=1 /script/immich_auto_album.sh > /proc/1/fd/1 2>/proc/1/fd/2" > "$CRONTAB_PATH"
    if [ "$LOG_LEVEL" == "DEBUG" ]; then
        DEBUG_PARM=-debug
    fi
    /usr/local/bin/supercronic -passthrough-logs -no-reap -split-logs $DEBUG_PARM $CRONTAB_PATH
else
    UNATTENDED=1 /script/immich_auto_album.sh > /proc/1/fd/1 2>/proc/1/fd/2 || true
fi
