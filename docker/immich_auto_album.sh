#!/usr/bin/env sh

# Always run unattended
arg_fetch_chunk_size=""
arg_chunk_size=""
arg_log_Level=""
arg_root_path=""
arg_api_url=""
arg_api_key=""

if [ ! -z "$FETCH_CHUNK_SIZE" ]; then
    arg_fetch_chunk_size="-C $FETCH_CHUNK_SIZE"
fi

if [ ! -z "$CHUNK_SIZE" ]; then
    arg_chunk_size="-c $CHUNK_SIZE"
fi

if [ ! -z "$LOG_LEVEL" ]; then
    arg_log_Level="-l $LOG_LEVEL"
fi

BASEDIR=$(dirname "$0")
python3 $BASEDIR/immich_auto_album.py -u $arg_fetch_chunk_size $arg_chunk_size $arg_log_Level $ROOT_PATH $API_URL $API_KEY