#!/usr/bin/env sh

args="-u $ROOT_PATH $API_URL $API_KEY"

if [ ! -z "$ALBUM_LEVELS" ]; then
    args="-a $ALBUM_LEVELS $args"
fi

if [ ! -z "$ALBUM_SEPARATOR" ]; then
    args="-s \"$ALBUM_SEPARATOR\" $args"
fi

if [ ! -z "$FETCH_CHUNK_SIZE" ]; then
    args="-C $FETCH_CHUNK_SIZE $args"
fi

if [ ! -z "$CHUNK_SIZE" ]; then
    args="-c $CHUNK_SIZE $args"
fi

if [ ! -z "$LOG_LEVEL" ]; then
    args="-l $LOG_LEVEL $args"
fi


BASEDIR=$(dirname "$0")
echo $args | xargs python3 -u $BASEDIR/immich_auto_album.py