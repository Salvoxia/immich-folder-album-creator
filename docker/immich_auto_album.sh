#!/usr/bin/env sh

# parse comma separated root paths
root_paths=$(echo "$ROOT_PATH" | tr "," "\n")
main_root_path=""
additional_root_paths=""
for path in ${root_paths}; do
  if [ -z "$main_root_path" ]; then
    main_root_path="$path"
  else
    additional_root_paths="-r $path $additional_root_paths"
  fi
done

unattended=
if [ ! -z "$UNATTENDED" ]; then
    unattended="-u"
fi

args="$unattended $main_root_path $API_URL $API_KEY"

if [ ! -z "$additional_root_paths" ]; then
    args="$additional_root_paths $args"
fi

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

if [ "$INSECURE" = "true" ]; then
    args="-k $args"
fi

if [ ! -z "$IGNORE" ]; then
    args="-i \"$IGNORE\" $args"
fi

if [ ! -z "$MODE" ]; then
    args="-m \"$MODE\" $args"
fi

if [ ! -z "$DELETE_CONFIRM" ]; then
    args="-d $args"
fi

BASEDIR=$(dirname "$0")
echo $args | xargs python3 -u $BASEDIR/immich_auto_album.py