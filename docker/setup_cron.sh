#!/usr/bin/env sh
set -eu

SCRIPT="/script/immich_auto_album.sh"

# source util library
. util.sh

# Set defaults ---
CRON_EXPRESSION="${CRON_EXPRESSION:-}"

# RUN_IMMEDIATELY depends on CRON set
if [ ! -z "$CRON_EXPRESSION" ]; then
    RUN_IMMEDIATELY="${RUN_IMMEDIATELY:-false}"
else
    RUN_IMMEDIATELY="${RUN_IMMEDIATELY:-true}"
fi

# Perform immediate run
if is_true "$RUN_IMMEDIATELY"; then
    "$SCRIPT" > /proc/1/fd/1 2>/proc/1/fd/2 || true
fi

# Set up SuperCronic schedule
if [ -n "$CRON_EXPRESSION" ]; then
    CRONTAB_PATH="/tmp/crontab"
   
    # Create and lock down crontab
    touch "$CRONTAB_PATH"
    chmod 0600 "$CRONTAB_PATH"

    # populate crontab
    echo "$CRON_EXPRESSION UNATTENDED=1 /script/immich_auto_album.sh > /proc/1/fd/1 2>/proc/1/fd/2" > "$CRONTAB_PATH"
    
    # SuperCronic debug logging
    DEBUG_PARM=""
    if [ "${LOG_LEVEL:-}" = "DEBUG" ]; then
        DEBUG_PARM="-debug"
    fi
    /usr/local/bin/supercronic -passthrough-logs -no-reap -split-logs $DEBUG_PARM $CRONTAB_PATH
fi