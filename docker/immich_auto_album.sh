#!/usr/bin/env sh

# parse comma separated root paths and wrap in quotes
oldIFS=$IFS
IFS=','
# disable globbing
set -f          
# parse ROOT_PATH CSV
main_root_path=""
additional_root_paths=""
for path in ${ROOT_PATH}; do
  if [ -z "$main_root_path" ]; then
    main_root_path="\"$path\""
  else
    additional_root_paths="--root-path \"$path\" $additional_root_paths"
  fi
done
IFS=$oldIFS

# parse semicolon separated root paths and wrap in quotes
oldIFS=$IFS
IFS=':'
# parse  SHARE_WITH CSV
share_with_list=""
if [ ! -z "$SHARE_WITH" ]; then
    for share_user in ${SHARE_WITH}; do
        share_with_list="--share-with \"$share_user\" $share_with_list"
    done
fi

# parse PATH_FILTER CSV
path_filter_list=""
if [ ! -z "$PATH_FILTER" ]; then
    for path_filter_entry in ${PATH_FILTER}; do
        path_filter_list="--path-filter \"$path_filter_entry\" $path_filter_list"
    done
fi

# parse IGNORE CSV
ignore_list=""
if [ ! -z "$IGNORE" ]; then
    for ignore_entry in ${IGNORE}; do
        ignore_list="--ignore \"$ignore_entry\" $ignore_list"
    done
fi

## parse ABLUM_NAME_POST_REGEX<n>
# Split on newline only
IFS=$(echo -en "\n\b")
album_name_post_regex_list=""
# Support up to 10 regex patterns
regex_max=10
for regex_no in `seq 1 $regex_max`
do
    for entry in `env`
    do
        # check if env variable name begins with ALBUM_POST_NAME_REGEX followed by a the current regex no and and equal sign
        pattern=$(echo "^ALBUM_NAME_POST_REGEX${regex_no}+=.+")
        TEST=$(echo "${entry}" | grep -E "$pattern")
        if [ ! -z "${TEST}" ]; then
            value="${entry#*=}" # select everything after the first `=`
            album_name_post_regex_list="$album_name_post_regex_list --album-name-post-regex $value"
        fi
    done
done

# reset IFS
IFS=$oldIFS

unattended=
if [ ! -z "$UNATTENDED" ]; then
    unattended="--unattended"
fi

api_key=""
api_key_type=""

if [ ! -z "$API_KEY" ]; then
    api_key=$API_KEY
    api_key_type="--api-key-type literal"
elif [ ! -z "$API_KEY_FILE" ]; then
    api_key=$API_KEY_FILE
    api_key_type="--api-key-type file"
fi

args="$api_key_type $unattended $main_root_path $API_URL $api_key"

if [ ! -z "$additional_root_paths" ]; then
    args="$additional_root_paths $args"
fi

if [ ! -z "$ALBUM_LEVELS" ]; then
    args="--album-levels=\"$ALBUM_LEVELS\" $args"
fi

if [ ! -z "$ALBUM_SEPARATOR" ]; then
    args="--album-separator \"$ALBUM_SEPARATOR\" $args"
fi

if [ ! -z "$album_name_post_regex_list" ]; then
    args="$album_name_post_regex_list $args"
fi

if [ ! -z "$FETCH_CHUNK_SIZE" ]; then
    args="--fetch-chunk-size $FETCH_CHUNK_SIZE $args"
fi

if [ ! -z "$CHUNK_SIZE" ]; then
    args="--chunk-size $CHUNK_SIZE $args"
fi

if [ ! -z "$LOG_LEVEL" ]; then
    args="--log-level $LOG_LEVEL $args"
fi

if [ "$INSECURE" = "true" ]; then
    args="--insecure $args"
fi

if [ ! -z "$ignore_list" ]; then
    args="$ignore_list $args"
fi

if [ ! -z "$MODE" ]; then
    args="--mode \"$MODE\" $args"
fi

if [ ! -z "$DELETE_CONFIRM" ]; then
    args="--delete-confirm $args"
fi

if [ ! -z "$share_with_list" ]; then
    args="$share_with_list $args"
fi

if [ ! -z "$SHARE_ROLE" ]; then
    args="--share-role $SHARE_ROLE $args"
fi

if [ ! -z "$SYNC_MODE" ]; then
    args="--sync-mode $SYNC_MODE $args"
fi

if [ ! -z "$ALBUM_ORDER" ]; then
    args="--album-order $ALBUM_ORDER $args"
fi

if [ ! -z "$FIND_ASSETS_IN_ALBUMS" ]; then
    args="--find-assets-in-albums $args"
fi

if [ ! -z "$FIND_ARCHIVED_ASSETS" ]; then
    args="--find-archived-assets $args"
fi

if [ ! -z "$path_filter_list" ]; then
    args="$path_filter_list $args"
fi

if [ ! -z "$SET_ALBUM_THUMBNAIL" ]; then
    args="--set-album-thumbnail \"$SET_ALBUM_THUMBNAIL\" $args"
fi

if [ ! -z "$ARCHIVE" ]; then
    args="--archive $args"
fi

if [ ! -z "$READ_ALBUM_PROPERTIES" ]; then
    args="--read-album-properties $args"
fi

if [ ! -z "$API_TIMEOUT" ]; then
    args="--api-timeout \"$API_TIMEOUT\" $args"
fi

if [ "$COMMENTS_AND_LIKES" == "1" ]; then
    args="--comments-and-likes-enabled $args"
elif [ "$COMMENTS_AND_LIKES" == "0" ]; then
    args="--comments-and-likes-disabled $args"
fi

if [ ! -z "$UPDATE_ALBUM_PROPS_MODE" ]; then
    args="--update-album-props-mode $UPDATE_ALBUM_PROPS_MODE $args"
fi

BASEDIR=$(dirname "$0")
echo $args | xargs python3 -u $BASEDIR/immich_auto_album.py
