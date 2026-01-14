[![Build Status](https://github.com/salvoxia/immich-folder-album-creator/workflows/CI/badge.svg)](https://github.com/Salvoxia/immich-folder-album-creator/actions/workflows/ci.yaml)
[![Build Status](https://github.com/salvoxia/immich-folder-album-creator/workflows/build-image/badge.svg)](https://github.com/Salvoxia/immich-folder-album-creator/actions/workflows/build-image.yaml)
[![Docker][docker-image]][docker-url]

[docker-image]: https://img.shields.io/docker/pulls/salvoxia/immich-folder-album-creator.svg
[docker-url]: https://hub.docker.com/r/salvoxia/immich-folder-album-creator/

# Immich Folder Album Creator

This is a python script designed to automatically create albums in [Immich](https://immich.app/) from a folder structure mounted into the Immich container.
This is useful for automatically creating and populating albums for external libraries.
Using the provided docker image, the script can simply be added to the Immich compose stack and run along the rest of Immich's containers.

__Current compatibility:__ Immich v1.106.1 - v2.4.x

### Disclaimer
This script is mostly based on the following original script: [REDVM/immich_auto_album.py](https://gist.github.com/REDVM/d8b3830b2802db881f5b59033cf35702)

## Table of Contents
- [Immich Folder Album Creator](#immich-folder-album-creator)
    - [Disclaimer](#disclaimer)
  - [Table of Contents](#table-of-contents)
  - [Usage](#usage)
    - [Creating an API Key](#creating-an-api-key)
    - [Bare Python Script](#bare-python-script)
    - [Docker](#docker)
      - [Environment Variables](#environment-variables)
      - [Run the container with Docker](#run-the-container-with-docker)
      - [Run the container with Docker-Compose](#run-the-container-with-docker-compose)
    - [Choosing the correct `root_path`](#choosing-the-correct-root_path)
  - [How it works](#how-it-works)
  - [Album Level Ranges](#album-level-ranges)
  - [Filtering](#filtering)
    - [Ignoring Assets](#ignoring-assets)
    - [Filtering for Assets](#filtering-for-assets)
    - [Filter Examples](#filter-examples)
  - [Album Name Regex](#album-name-regex)
    - [Regex Examples](#regex-examples)
  - [Automatic Album Sharing](#automatic-album-sharing)
    - [Album Sharing Examples (Bare Python Script)](#album-sharing-examples-bare-python-script)
    - [Album Sharing Examples (Docker)](#album-sharing-examples-docker)
  - [Cleaning Up Albums](#cleaning-up-albums)
    - [`CLEANUP`](#cleanup)
    - [`DELETE_ALL`](#delete_all)
  - [Assets in Multiple Albums](#assets-in-multiple-albums)
  - [Setting Album Thumbnails](#setting-album-thumbnails)
  - [Setting Album-Fine Properties](#setting-album-fine-properties)
    - [Prerequisites](#prerequisites)
    - [`.albumprops` File Format](#albumprops-file-format)
    - [Enabling `.albumprops` discovery](#enabling-albumprops-discovery)
    - [Property Precedence](#property-precedence)
  - [Mass Updating Album Properties](#mass-updating-album-properties)
    - [Examples:](#examples)
  - [Asset Visibility & Locked Folder](#asset-visibility--locked-folder)
  - [Dealing with External Library Changes](#dealing-with-external-library-changes)
    - [`docker-compose` example passing the API key as environment variable](#docker-compose-example-passing-the-api-key-as-environment-variable)
    - [`docker-compose` example using a secrets file for the API key](#docker-compose-example-using-a-secrets-file-for-the-api-key)

## Usage
### Creating an API Key
Regardless of how the script will be used later ([Bare Python Script](#bare-python-script) or [Docker](#docker)), an API Key is required for each user the script should be used for.
Since Immich Server v1.135.x, creating API keys allows the user to specify permissions. The following permissions are required for the script to work with any possible option.  
The list contains API key permissions valid for **Immich v2.1.0**.
  - `asset`
    - `asset.read`
    - `asset.delete`
    - `asset.update`
  - `album`
    - `album.create`
    - `album.read`
    - `album.update`
    - `album.delete`
  - `albumAsset`
    - `albumAsset.create`
  - `albumUser`
    - `albumUser.create`
    - `albumUser.update`
    - `albumUser.delete`
  - `user`
    - `user.read`

### Bare Python Script
1. Download the script and its requirements
    ```bash
    curl https://raw.githubusercontent.com/Salvoxia/immich-folder-album-creator/main/immich_auto_album.py -o immich_auto_album.py
    curl https://raw.githubusercontent.com/Salvoxia/immich-folder-album-creator/main/requirements.txt -o requirements.txt
    ```
2. Install requirements
    ```bash
    pip3 install -r requirements.txt
    ```
3. Run the script
```
    usage: immich_auto_album.py [-h] [--api-key API_KEY] [-t {literal,file}] [-r ROOT_PATH] [-u] [-a ALBUM_LEVELS] [-s ALBUM_SEPARATOR] [-R PATTERN [REPL ...]] [-c CHUNK_SIZE] [-C FETCH_CHUNK_SIZE] [-l {CRITICAL,ERROR,WARNING,INFO,DEBUG}] [-k] [-i IGNORE]
                            [-m {CREATE,CLEANUP,DELETE_ALL}] [-d] [-x SHARE_WITH] [-o {editor,viewer}] [-S {0,1,2}] [-O {False,asc,desc}] [-A] [-f PATH_FILTER] [--set-album-thumbnail {first,last,random,random-all,random-filtered}] [--visibility {archive,hidden,locked,timeline}]
                            [--find-archived-assets] [--read-album-properties] [--api-timeout API_TIMEOUT] [--comments-and-likes-enabled] [--comments-and-likes-disabled] [--update-album-props-mode {0,1,2}]
                            root_path api_url api_key

Create Immich Albums from an external library path based on the top level folders

positional arguments:
  root_path             The external library's root path in Immich
  api_url               The root API URL of immich, e.g. https://immich.mydomain.com/api/
  api_key               The Immich API Key to use. Set --api-key-type to 'file' if a file path is provided.

options:
  -h, --help            show this help message and exit
  --api-key API_KEY     Additional API Keys to run the script for; May be specified multiple times for running the script for multiple users. (default: None)
  -t {literal,file}, --api-key-type {literal,file}
                        The type of the Immich API Key (default: literal)
  -r ROOT_PATH, --root-path ROOT_PATH
                        Additional external library root path in Immich; May be specified multiple times for multiple import paths or external libraries. (default: None)
  -u, --unattended      Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob. (default: False)
  -a ALBUM_LEVELS, --album-levels ALBUM_LEVELS
                        Number of sub-folders or range of sub-folder levels below the root path used for album name creation. Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be 0. If a
                        range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'. If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>.
                        (default: 1)
  -s ALBUM_SEPARATOR, --album-separator ALBUM_SEPARATOR
                        Separator string to use for compound album names created from nested folders. Only effective if -a is set to a value > 1 (default: )
  -R PATTERN [REPL ...], --album-name-post-regex PATTERN [REPL ...]
                        Regex pattern and optional replacement (use "" for empty replacement). Can be specified multiple times. (default: None)
  -c CHUNK_SIZE, --chunk-size CHUNK_SIZE
                        Maximum number of assets to add to an album with a single API call (default: 2000)
  -C FETCH_CHUNK_SIZE, --fetch-chunk-size FETCH_CHUNK_SIZE
                        Maximum number of assets to fetch with a single API call (default: 5000)
  -l {CRITICAL,ERROR,WARNING,INFO,DEBUG}, --log-level {CRITICAL,ERROR,WARNING,INFO,DEBUG}
                        Log level to use. ATTENTION: Log level DEBUG logs API key in clear text! (default: INFO)
  -k, --insecure        Pass to ignore SSL verification (default: False)
  -i IGNORE, --ignore IGNORE
                        Use either literals or glob-like patterns to ignore assets for album name creation. This filter is evaluated after any values passed with --path-filter. May be specified multiple times. (default: None)
  -m {CREATE,CLEANUP,DELETE_ALL}, --mode {CREATE,CLEANUP,DELETE_ALL}
                        Mode for the script to run with. CREATE = Create albums based on folder names and provided arguments; CLEANUP = Create album names based on current images and script arguments, but delete albums if they exist;
                        DELETE_ALL = Delete all albums. If the mode is anything but CREATE, --unattended does not have any effect. Only performs deletion if -d/--delete-confirm option is set, otherwise only performs a dry-run. (default:
                        CREATE)
  -d, --delete-confirm  Confirm deletion of albums when running in mode CLEANUP or DELETE_ALL. If this flag is not set, these modes will perform a dry run only. Has no effect in mode CREATE (default: False)
  -x SHARE_WITH, --share-with SHARE_WITH
                        A user name (or email address of an existing user) to share newly created albums with. Sharing only happens if the album was actually created, not if new assets were added to an existing album. If the the share
                        role should be specified by user, the format <userName>=<shareRole> must be used, where <shareRole> must be one of 'viewer' or 'editor'. May be specified multiple times to share albums with more than one user.
                        (default: None)
  -o {viewer,editor}, --share-role {viewer,editor}
                        The default share role for users newly created albums are shared with. Only effective if --share-with is specified at least once and the share role is not specified within --share-with. (default: viewer)
  -S {0,1,2}, --sync-mode {0,1,2}
                        Synchronization mode to use. Synchronization mode helps synchronizing changes in external libraries structures to Immich after albums have already been created. Possible Modes: 0 = do nothing; 1 = Delete any empty
                        albums; 2 = Delete offline assets AND any empty albums (default: 0)
  -O {False,asc,desc}, --album-order {False,asc,desc}
                        Set sorting order for newly created albums to newest or oldest file first, Immich defaults to newest file first (default: False)
  -A, --find-assets-in-albums
                        By default, the script only finds assets that are not assigned to any album yet. Set this option to make the script discover assets that are already part of an album and handle them as usual. If --find-archived-
                        assets is set as well, both options apply. (default: False)
  -f PATH_FILTER, --path-filter PATH_FILTER
                        Use either literals or glob-like patterns to filter assets before album name creation. This filter is evaluated before any values passed with --ignore. May be specified multiple times. (default: None)
  --set-album-thumbnail {first,last,random,random-all,random-filtered}
                        Set first/last/random image as thumbnail for newly created albums or albums assets have been added to. If set to random-filtered, thumbnails are shuffled for all albums whose assets would not be filtered out or
                        ignored by the ignore or path-filter options, even if no assets were added during the run. If set to random-all, the thumbnails for ALL albums will be shuffled on every run. (default: None)
  --visibility {archive,hidden,locked,timeline}
                        Set this option to automatically set the visibility of all assets that are discovered by the script and assigned to albums. Exception for value 'locked': Assets will not be added to any albums, but to the 'locked' folder only. Also applies if -m/--mode is set to
                        CLEAN_UP or DELETE_ALL; then it affects all assets in the deleted albums. Always overrides -v/--archive. (default: None)
  --find-archived-assets
                        By default, the script only finds assets with visibility set to 'timeline' (which is the default). Set this option to make the script discover assets with visibility 'archive' as well. If -A/--find-assets-in-albums is set as well, both options apply. (default: False)
  --read-album-properties
                        If set, the script tries to access all passed root paths and recursively search for .albumprops files in all contained folders. These properties will be used to set custom options on an per-album level. Check the
                        readme for a complete documentation. (default: False)
  --api-timeout API_TIMEOUT
                        Timeout when requesting Immich API in seconds (default: 20)
  --comments-and-likes-enabled
                        Pass this argument to enable comment and like functionality in all albums this script adds assets to. Cannot be used together with --comments-and-likes-disabled (default: False)
  --comments-and-likes-disabled
                        Pass this argument to disable comment and like functionality in all albums this script adds assets to. Cannot be used together with --comments-and-likes-enabled (default: False)
  --update-album-props-mode {0,1,2}
                        Change how album properties are updated whenever new assets are added to an album. Album properties can either come from script arguments or the .albumprops file. Possible values: 0 = Do not change album
                        properties. 1 = Only override album properties but do not change the share status. 2 = Override album properties and share status, this will remove all users from the album which are not in the SHARE_WITH list.
                        (default: 0)
  --max-retry-count MAX_RETRY_COUNT
                        Number of times to retry an Immich API call if it timed out before failing. (default: 3)
  --threads {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20}
                        Number of threads to fetch assets with in parallel. (default: 4)

```

__Plain example without optional arguments:__
```bash
python3 ./immich_auto_album.py \
  /path/to/external/lib \
  https://immich.mydomain.com/api \
  thisIsMyApiKeyCopiedFromImmichWebGui
```
> [!IMPORTANT]  
> You must pass one root path as the first positional argument to the script. You cannot use `--root-path` alone if you only have a single root path!  
> Pass `--root-path` additionally for each additional root path you want to use.

__Example:__
```bash
python3 ./immich_auto_album.py \
  --root-path /my/second/root_path \
  --root-path /my/third/root_path 
  /my/first/root_path \
  https://immich.mydomain.com/api \
  thisIsMyApiKeyCopiedFromImmichWebGui
```
### Docker

A Docker image is provided to be used as a runtime environment. It can be used to either run the script manually, or via cronjob by providing a crontab expression to the container. The container can then be added to the Immich compose stack directly.  
The container runs rootless, by default with `uid:gid` `1000:1000`. This can be overridden in the `docker` command or `docker-compose` file.

#### Environment Variables
The environment variables are analogous to the script's command line arguments.

| Environment variable         | Mandatory? | Description |
| :--------------------------- | :--------- | :---------- |
| `ROOT_PATH`                  | yes        | A single or a comma separated list of import paths for external libraries in Immich. <br>Refer to [Choosing the correct `root_path`](#choosing-the-correct-root_path).|
| `API_URL`                    | yes        | The root API URL of immich, e.g. https://immich.mydomain.com/api/ |
| `API_KEY`                    | no         | A colon `:` separated list of API Keys to run the script for. Either `API_KEY` or `API_KEY_FILE` must be specified. The `API_KEY` variable takes precedence for ease of manual execution, but it is recommended to use `API_KEY_FILE`. 
| `API_KEY_FILE`               | no         | A colon `:` separated list of absolute paths (from the root of the container) to files containing an Immich API Key, one key per file. The file might be mounted into the container using a volume (e.g. `-v /path/to/api_key.secret:/immich_api_key.secret:ro`). Each file must contain only the value of a single API Key.<br>Note that the user the container is running with must have read access to all API key file. |
| `CRON_EXPRESSION`            | yes        | A [crontab-style expression](https://crontab.guru/) (e.g. `0 * * * *`) to perform album creation on a schedule (e.g. every hour). |
| `RUN_IMMEDIATELY`            | no         | Set to `true` to run the script right away, after running once the script will automatically run again based on the CRON_EXPRESSION |
| `ALBUM_LEVELS`               | no         | Number of sub-folders or range of sub-folder levels below the root path used for album name creation. Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be `0`. If a range should be set, the start level and end level must be separated by a comma. <br>Refer to [How it works](#how-it-works) for a detailed explanation and examples. |
| `ALBUM_SEPARATOR`            | no         | Separator string to use for compound album names created from nested folders. Only effective if `-a` is set to a value `> 1`(default: "` `") |
| `CHUNK_SIZE`                 | no         | Maximum number of assets to add to an album with a single API call (default: `2000`)  |
| `FETCH_CHUNK_SIZE`           | no         | Maximum number of assets to fetch with a single API call (default: `5000`)            |
| `LOG_LEVEL`                  | no         | Log level to use (default: INFO), allowed values: `CRITICAL`,`ERROR`,`WARNING`,`INFO`,`DEBUG` |
| `INSECURE`                   | no         | Set to `true` to disable SSL verification for the Immich API server, useful for self-signed certificates (default: `false`), allowed values: `true`, `false` |
| `IGNORE`                     | no         | A colon `:` separated list of literals or glob-style patterns that will cause an image to be ignored if found in its path. |
| `MODE`                       | no         | Mode for the script to run with. <br> __`CREATE`__ = Create albums based on folder names and provided arguments<br>__`CLEANUP`__ = Create album names based on current images and script arguments, but delete albums if they exist <br> __`DELETE_ALL`__ = Delete all albums. <br> If the mode is anything but `CREATE`, `--unattended` does not have any effect. <br> (default: `CREATE`). <br>Refer to [Cleaning Up Albums](#cleaning-up-albums). |
| `DELETE_CONFIRM`             | no         | Confirm deletion of albums when running in mode `CLEANUP` or `DELETE_ALL`. If this flag is not set, these modes will perform a dry run only. Has no effect in mode `CREATE` (default: `False`). <br>Refer to [Cleaning Up Albums](#cleaning-up-albums).|
| `SHARE_WITH`                 | no         | A single or a colon (`:`) separated list of existing user names (or email addresses of existing users) to share newly created albums with. If the the share role should be specified by user, the format <userName>=<shareRole> must be used, where <shareRole> must be one of `viewer` or `editor`. May be specified multiple times to share albums with more than one user. (default: None) Sharing only happens if an album is actually created, not if new assets are added to it.  <br>Refer to [Automatic Album Sharing](#automatic-album-sharing).|
| `SHARE_ROLE`                 | no         | The role for users newly created albums are shared with. Only effective if `SHARE_WITH` is not empty and no explicit share role was specified for at least one user. (default: viewer), allowed values: `viewer`, `editor` |
| `SYNC_MODE`                  | no         | Synchronization mode to use. Synchronization mode helps synchronizing changes in external libraries structures to Immich after albums have already been created. Possible Modes: <br>`0` = do nothing<br>`1` = Delete any empty albums<br>`2` =  Delete offline assets AND any empty albums<br>(default: `0`)<br>Refer to [Dealing with External Library Changes](#dealing-with-external-library-changes). |
| `ALBUM_ORDER`                | no         | Set sorting order for newly created albums to newest (`desc`) or oldest (`asc`) file first, Immich defaults to newest file first, allowed values: `asc`, `desc` |
| `FIND_ASSETS_IN_ALBUMS`      | no         | By default, the script only finds assets that are not assigned to any album yet. Set this option to make the script discover assets that are already part of an album and handle them as usual. If --find-archived-assets is set as well, both options apply. (default: `False`)<br>Refer to [Assets in Multiple Albums](#assets-in-multiple-albums). |
| `PATH_FILTER`                | no         | A colon `:` separated list of literals or glob-style patterns to filter assets before album name creation. (default: ``)<br>Refer to [Filtering](#filtering). |
| `SET_ALBUM_THUMBNAIL`        | no         | Set first/last/random image as thumbnail (based on image creation timestamp) for newly created albums or albums assets have been added to.<br> Allowed values: `first`,`last`,`random`,`random-filtered`,`random-all`<br>If set to `random-filtered`, thumbnails are shuffled for all albums whose assets would not be filtered out or ignored by the `IGNORE` or `PATH_FILTER` options, even if no assets were added during the run. If set to random-all, the thumbnails for ALL albums will be shuffled on every run. (default: `None`)<br>Refer to [Setting Album Thumbnails](#setting-album-thumbnails). |
| `VISIBILITY`                 | no         | Set this option to automatically set the visibility of all assets that are discovered by the script and assigned to albums.<br>Exception for value 'locked': Assets will not be added to any albums, but to the 'locked' folder only.<br>Also applies if `MODE` is set to CLEAN_UP or DELETE_ALL; then it affects all assets in the deleted albums.<br>Always overrides `ARCHIVE`. (default: `None`)<br>Refer to [Asset Visibility & Locked Folder](#asset-visibility-locked-folder). |
| `FIND_ARCHIVED_ASSETS`       | no         | By default, the script only finds assets with visibility set to 'timeline' (which is the default). Set this option to make the script discover assets with visibility 'archive' as well. If -A/--find-assets-in-albums is set as well, both options apply. (default: `False`)<br>Refer to [Asset Visibility & Locked Folder](#asset-visibility--locked-folder). |
| `READ_ALBUM_PROPERTIES`      | no         | Set to `True` to enable discovery of `.albumprops` files in root paths, allowing to set different album properties for different albums. (default: `False`)<br>Refer to [Setting Album-Fine Properties](#setting-album-fine-properties).<br>Note that the user the container is running with must to your mounted external libraries for this function to work. |
| `API_TIMEOUT`                | no         | Timeout when requesting Immich API in seconds (default: `20`) |
| `COMMENTS_AND_LIKES`         | no         | Set to `1` to explicitly enable Comments & Likes functionality for all albums this script adds assets to, set to `0` to disable. If not set, this setting is left alone by the script. |
| `UPDATE_ALBUM_PROPS_MODE`    | no         | Change how album properties are updated whenever new assets are added to an album. Album properties can either come from script arguments or the `.albumprops` file. Possible values: <br>`0` = Do not change album properties.<br> `1` = Only override album properties but do not change the share status.<br> `2` = Override album properties and share status, this will remove all users from the album which are not in the SHARE_WITH list. |
| `ALBUM_NAME_POST_REGEX1..10` | no         | Up to 10 numbered environment variables `ALBUM_NAME_POST_REGEX1` to `ALBUM_NAME_POST_REGEX10` for album name post processing with regular expressions.<br> Refer to [Album Name Regex](#album-name-regex) |
| `MAX_RETRY_COUNT`            | no         | Maximum number of times an API call is retried if it timed out before failing.<br>(default: `3`)|
| `THREADS`                    | no         | Number of threads to fetch assets with in parallel.<br>Range: `[1..20]` (default: `4`)|

#### Run the container with Docker

To perform a manually triggered __dry run__ (only list albums that __would__ be created), use the following command (make sure not to set the `CRON_EXPRESSION` environment variable):
```bash
docker run \
  -e API_URL="https://immich.mydomain.com/api/" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos" \
  salvoxia/immich-folder-album-creator:latest
```
To actually create albums after performing a dry run, use the following command (setting the `UNATTENDED` environment variable):
```bash
docker run \
  -e UNATTENDED="1" \
  -e API_URL="https://immich.mydomain.com/api/" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos" \
  salvoxia/immich-folder-album-creator:latest
```

To pass the API key by secret file instead of an environment variable, pass `API_KEY_FILE` containing the path to the secret file mounted into the container, use a volume mount to mount the file and run the container with a user that has read access to the screts file:
```bash
docker run \
  -v "./api_key.secret:/api_key.secret:ro"
  -u 1001:1001 \
  -e UNATTENDED="1" \
  -e API_KEY_FILE="/api_key.secret" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos" \
  salvoxia/immich-folder-album-creator:latest
```

To set up the container to periodically run the script, give it a name, pass the TZ variable and a valid crontab expression as environment variable. This example runs the script every hour:
```bash
docker run \
  --name immich-folder-album-creator \
  -e TZ="Europe/Berlin" \
  -e CRON_EXPRESSION="0 * * * *" \
  -e API_URL="https://immich.mydomain.com/api/" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos" \
  salvoxia/immich-folder-album-creator:latest
```

If your external library uses multiple import paths or you have set up multiple external libraries, you can pass multiple paths in `ROOT_PATH` by setting it to a comma separated list of paths:  
```bash
docker run \
  --name immich-folder-album-creator \
  -e TZ="Europe/Berlin" \
  -e CRON_EXPRESSION="0 * * * *" \
  -e API_URL="https://immich.mydomain.com/api/" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos,/external_libs/more_photos" \
  salvoxia/immich-folder-album-creator:latest
```

#### Run the container with Docker-Compose

Adding the container to Immich's `docker-compose.yml` file:
```yml
#
# WARNING: Make sure to use the docker-compose.yml of the current release:
#
# https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml
#
# The compose file on main may not be compatible with the latest release.
#

name: immich

services:
  immich-server:
    container_name: immich_server
    volumes:
     - /path/to/my/photos:/external_libs/photos
  ...
  immich-folder-album-creator:
    container_name: immich_folder_album_creator
    image: salvoxia/immich-folder-album-creator:latest
    restart: unless-stopped
    # Use a UID/GID that has read access to the mounted API key file 
    # and external libraries
    user: 1001:1001
    volumes:
     - /path/to/secret/file:/immich_api_key.secret:ro
     # mount needed for .albumprops to work
     - /path/to/my/photos:/external_libs/photos
    environment:
      API_URL: http://immich_server:2283/api
      API_KEY_FILE: /immich_api_key.secret
      ROOT_PATH: /external_libs/photos
      CRON_EXPRESSION: "0 * * * *"
      TZ: Europe/Berlin
```

This will periodically re-scan the library as per `CRON_EXPRESSION` settings and create albums (the cron script sets `UNATTENDED=1` explicitly).

To perform a manually triggered __dry run__ (only list albums that __would__ be created) in an already running container, use the following command:

```
docker exec immich_folder_album_creator /bin/sh -c "/script/immich_auto_album.sh"
```

To actually create albums after performing the dry run, use the following command (setting the `UNATTENDED` environment variable):

```
docker exec immich_folder_album_creator /bin/sh -c "UNATTENDED=1 /script/immich_auto_album.sh"
```

### Choosing the correct `root_path`
The root path  `/path/to/external/lib/` is the path you have mounted your external library into the Immich container.  
If you are following [Immich's External library Documentation](https://immich.app/docs/guides/external-library), you are using an environment variable called `${EXTERNAL_PATH}` which is mounted to `/usr/src/app/external` in the Immich container. Your `root_path` to pass to the script is `/usr/src/app/external`.

## How it works

The script utilizes [Immich's REST API](https://immich.app/docs/api/) to query all images indexed by Immich, extract the folder for all images that are in the top level of any provided `root_path`, then creates albums with the names of these folders (if not yet exists) and adds the images to the correct albums.

The following arguments influence what albums are created:  
`root_path`, `--album-levels` and `--album-separator`  

  - `root_path` is the base path where images are looked for. Multiple root paths can be specified by adding the `-r` argument as many times as necessary. Only images within that base path will be considered for album creation.
  - `--album-levels` controls how many levels of nested folders are considered when creating albums. The default is `1`. For examples see below.
  - `--album-separator` sets the separator used for concatenating nested folder names to create an album name. It is a blank by default.

__Examples:__  
Suppose you provide an external library to Immich under the path `/external_libs/photos`.
The folder structure of `photos` might look like this:

```
/external_libs/photos/
├── 2020/
│   ├── 02 Feb/
│   │   └── Vacation/
│   ├── 08 Aug/
│   │   └── Vacation/
├── Birthdays/
│   ├── John/
│   └── Jane/
└── Skiing 2023/
```

Albums created for `root_path = /external_libs/photos` (`--album-levels` is implicitly set to `1`):
 - `2020` (containing all images from `2020` and all sub-folders)
 - `Birthdays` (containing all images from Birthdays itself as well as `John` and `Jane`)
 - `Skiing 2023`

 Albums created for `root_path = /external_libs/photos` (`--album-levels` is implicitly set to `1`) and `--ignore "Vacation"`:
 - `2020` (containing all images from `2020`, `2020/02 Feb` and `2020/08 Aug`, but __NOT__ `2020/02 Feb/Vacation` or `2020/08 Aug/Vacation`)
 - `Birthdays` (containing all images from Birthdays itself as well as `John` and `Jane`)
 - `Skiing 2023`

Albums created for `root_path = /external_libs/photos/Birthdays`:
 - `John`
 - `Jane`

 Albums created for `root_path = /external_libs/photos` and `--album-levels = 2`:
 - `2020` (containing all images from `2020` itself, if any)
 - `2020 02 Feb` (containing all images from `2020/02 Feb` itself, `2020/02 Feb/Vacation`)
 - `2020 08 Aug` (containing all images from `2020/08 Aug` itself, `2020/08 Aug/Vacation`)
 - `Birthdays John` (containing all images from `Birthdays/John`)
 - `Birthdays Jane` (containing all images from `Birthdays/Jane`)
 - `Skiing 2023`

 Albums created for `root_path = /external_libs/photos`, `--album-levels = 3` and `--album-separator " - "` :
 - `2020` (containing all images from `2020` itself, if any)
 - `2020 - 02 Feb` (containing all images from `2020/02 Feb` itself, if any)
 - `2020 - 02 Feb - Vacation` (containing all images from `2020/02 Feb/Vacation`)
 - `2020 - 08 Aug - Vacation` (containing all images from `2020/02 Aug/Vacation`)
 - `Birthdays - John`
 - `Birthdays - Jane`
 - `Skiing 2023`

  Albums created for `root_path = /external_libs/photos`, `--album-levels = -1` and `--album-separator " - "` :
 - `2020` (containing all images from `2020` itself, if any)
 - `02 Feb` (containing all images from `2020/02 Feb` itself, if any)
 - `Vacation` (containing all images from `2020/02 Feb/Vacation` AND `2020/08 Aug/Vacation`)
 - `John` (containing all images from `Birthdays/John`)
 - `Jane` (containing all images from `Birthdays/Jane`)
 - `Skiing 2023`
 
 ## Album Level Ranges

 It is possible to specify not just a number for `--album-levels`, but a range from level x to level y in the folder structure that should make up an album's name:  
 `--album-levels="2,3"`  
 The range is applied to the folder structure beneath `root_path` from the top for positive levels and from the bottom for negative levels.
 Suppose the following folder structure for an external library with the script's `root_path` set to `/external_libs/photos`:
 ```
/external_libs/photos/2020/2020 02 Feb/Vacation
/external_libs/photos/2020/2020 08 Aug/Vacation
```
 - `--album-levels="2,3"` will create albums (for this folder structure, this is equal to `--album-levels="-2"`)
    - `2020 02 Feb Vacation`
    - `2020 08 Aug Vacation`
  - `--album-levels="2,2"` will create albums (for this folder structure, this is equal to `--album-levels="-2,-2"`)
    - `2020 02 Feb`
    - `2020 08 Aug`

> [!IMPORTANT]  
> When passing negative ranges as album levels, you __must__ pass the argument in the form `--album-levels="-2,-2"`. Emphasis is on the equals sign `=` separating the option from the value. Otherwise, you might get an error `argument -a/--album-levels: expected one argument`!

> [!WARNING]  
> Note that with negative `album-levels` or album level ranges, images from different parent folders will be mixed in the same album if they reside in sub-folders with the same name (see `Vacation` in example above).

Since Immich does not support real nested albums ([yet?](https://github.com/immich-app/immich/discussions/2073)), neither does this script.

## Filtering

It is possible filter images by either specifying keywords or path patterns to either specifically filter for or ignore assets based on their path. Two options control this behavior.  
Internally, the script converts literals to glob-patterns that will match a path if the specified literal occurs anywhere in it. Example: `--ignore Feb` is equal to `--ignore **/*Feb*/**`.

The following wild-cards are supported:  
| Pattern | Meaning                                                                                     |
|---------|---------------------------------------------------------------------------------------------|
|`*`      | Matches everything (even nothing) within one folder level                                   |
|`?`      | Matches any single character                                                                |
|`[]`     | Matches one character in the brackets, e.g. `[a]` literally matches `a`                     |
|`[!]`    | Matches one character *not* in the brackets, e.h. `[!a]` matches any character **but** `a`  |


### Ignoring Assets
The option `-i / --ignore` can be specified multiple times for each literal or glob-style path pattern.  
When using Docker, the environment variable `IGNORE` accepts a colon-separated `:` list of literals or glob-style patterns. If an image's path **below the root path** matches the pattern, it will be ignored.  

### Filtering for Assets
The option `-f / ---path-filter` can be specified multiple times for each literal or glob-style path pattern. 
When using Docker, the environment variable `PATH_FILTER` accepts a colon-separated `:` of literals or glob-style patterns. If an image's path **below the root path** does **NOT** match the pattern, it will be ignored.

> [!TIP]  
> When working with path filters, consider setting the `-A / --find-assets-in-albums` option or Docker environment variable `FIND_ASSETS_IN_ALBUMS` for the script to discover assets that are already part of an album. That way, assets can be added to multiple albums by the script. Refer to the [Assets in Multiple Albums](#assets-in-multiple-albums) section for more information.

### Filter Examples
Consider the following folder structure:  
```
/external_libs/photos/
├── 2020/
│   ├── 02 Feb/
│   │   └── Vacation/
│   ├── 08 Aug/
│   │   └── Vacation/
├── Birthdays/
│   ├── John/
│   └── Jane/
└── Skiing 2023/
```

- To only create a `Birthdays` album with all images directly in `Birthdays` or in any subfolder on any level, run the script with the following options:  
  - `root_path=/external_libs/photos`
  - `--album-level=1`
  - `--path-filter Birthdays/**`
- To only create albums for the 2020s (all 202x years), but with the album names like `2020 02 Feb`, run the script with the following options:
  - `root_path=/external_libs/photos`
  - `--album-level=2`
  - `--path-filter=202?/**`
- To only create albums for 2020s (all 202x years) with the album names like `2020 02 Feb`, but only with images in folders **one level** below `2020` and **not** any of the `Vacation` images, run the script with the following options:
  - `root_path=/external_libs/photos`
  - `--album-level=2`
  - `--path-filter=202?/*/*`
- To create a `Vacation` album with all vacation images, run the script with the following options:
  - `root_path=/external_libs/photos`
  - `--album-level=-1`
  - `--path-filter=**/Vacation/*`

## Album Name Regex

As a last step it is possible to run search and replace on Album Names. This can be repetitive with the following syntax: `-R PATTERN [REPLACEMENT] [-R PATTERN [REPLACEMENT]]` (equal to `--album-name-post-regex`)
  * PATTERN should be an regex
  * REPLACEMENT is optional default ''
The search and replace operations are performed in the sequence the patterns and replacements are passed to the script.

For Docker, these patterns are passed in numbered environment variables starting with `ALBUM_NAME_POST_REGEX1` up to `ALBUM_NAME_POST_REGEX10`. These are passed to the script in ascending order.

### Regex Examples
Consider the following folder structure where you have a YYYY/MMDD, YYYY/DD MMM or similar structure: 
```
/external_libs/photos/
└──  2020/
   └── 02 Feb My Birthday
   └── 0408_Cycling_Holidays_in_the_Alps
```

In a default way, the script would create Album as `2020 02 Feb My Birthday` and `2020 0408_Cycling_Holidays_in_the_Alps`.  
As we see, the album names get pretty long and as Immich extracts EXIF dates, there is no need for these structed dates in album name. Furthermore, the underscores may be good for file operations but don't look nice in our album names. Cleaning up the album names can be accomplished with two regular expressions in sequence:

```bash
python3 immich_auto_album.py /mnt/library http://localhost:2283/api <key> \
  --album-levels 2 \
  --album-separator '' \
  --album-name-post-regex '[\d]+_|\d+\s\w{3}' \
  --album-name-post-regex '_' ' '
```
The first pattern only specifies a regular expression and no replacement, which means any matching string will effectively be removed from the album name.  
The second pattern specifies to replace underscores `_` with a blank ` `.  
As a result, the album names will be `Cycling holidays in the Alps` and `My Birthday`.

>[!IMPORTANT]  
>When using this feature with Docker, the regular expressions need to retain the single quotes `'`.
>In `docker-compose`, backslashes must be escaped as well!

Example when running from command line:
```bash
docker run \
  -e ROOT_PATH="/external_libs/photos" \
  -e API_URL=" http://localhost:2283/api" \
  -e API_KEY="<key>" \
  -e ALBUM_LEVELS="2" \
  -e ALBUM_SEPARATOR="" \
  -e ALBUM_NAME_POST_REGEX1="'[\d]+_|\d+\s\w{3}'" \
  -e ALBUM_NAME_POST_REGEX2="'_' ' '"
```

Example when using `docker-compose`:
```yaml
---
services:
  immich-folder-album-creator:
    container_name: immich_folder_album_creator
    image: salvoxia/immich-folder-album-creator:latest
    restart: unless-stopped
    environment:
      API_URL: http://immich_server:2283/api
      API_KEY: <key>
      ROOT_PATH: /external_libs/photos
      ALBUM_LEVELS: 2
      ALBUM_SEPARATOR: ""
      # backslashes must be escaped in YAML
      ALBUM_NAME_POST_REGEX1: "'[\\d]+_|\\d+\\s\\w{3}'"
      ALBUM_NAME_POST_REGEX2: "'_' ' '"
      LOG_LEVEL: DEBUG
      CRON_EXPRESSION: "0 * * * *"
      TZ: Europe/Berlin
```


## Automatic Album Sharing

The scripts support sharing newly created albums with a list of existing users. The sharing role (`viewer` or `editor`) can be specified for all users at once or individually per user.

### Album Sharing Examples (Bare Python Script)
Two arguments control this feature:
  - `-o / --share-role`: The default role for users an album is shared with. Allowed values are `viewer` or `editor`. This argument is optional and defaults to `viewer`.
  - `-x / --share-with`: Specify once per user to share with. The value should be either the user name or the user's email address as specified in Immich. If the user name is used and it contains blanks ` `, it must be wrapped in double quotes `"`. To override the default share role and specify a role explicitly for this user, the format `<userName>=<shareRole>` must be used (refer to examples below).

To share new albums with users `User A` and `User B` as `viewer`, use the following call:
```bash
python3 ./immich_auto_album.py \
  --share-with "User A" \
  --share-with "User B" \
  /path/to/external/lib \
  https://immich.mydomain.com/api \
  thisIsMyApiKeyCopiedFromImmichWebGui
```

To share new albums with users `User A` and `User B` as `editor`, use the following call:
```bash
python3 ./immich_auto_album.py \
  --share-with "User A" \
  --share-with "User B" \
  --share-role "editor" \
  /path/to/external/lib \
  https://immich.mydomain.com/api \
  thisIsMyApiKeyCopiedFromImmichWebGui
```

To share new albums with users `User A` and a user with mail address `userB@mydomain.com`, but `User A` should be an editor, use the following call:
```bash
python3 ./immich_auto_album.py \
  --share-with "User A=editor" \
  --share-with "userB@mydomain.com" \
  path/to/external/lib \
  https://immich.mydomain.com/api \
  thisIs
```

Per default these share settings are applied once when the album is created and remain unchanged if an asset is added to an album later. If you want to override the share state whenever an asset is added to an album you can set `--update-album-props-mode` to `2`. Note that this will completely override all shared users, any changes made within Immich will be lost.

### Album Sharing Examples (Docker)
Two environment variables control this feature:
  - `SHARE_ROLE`: The default role for users an album is shared with. Allowed values are `viewer` or `editor`. This argument is optional and defaults to `viewer`.
  - `SHARE_WITH`: A colon `:` separated list of either names or email addresses (or a mix) of existing users. To override the default share role and specify a role explicitly for each user, the format `<userName>=<shareRole>` must be used (refer to examples below).

To share new albums with users `User A` and `User B` as `viewer`, use the following call:
```bash
docker run \
  -e SHARE_WITH="User A:User B" \
  -e UNATTENDED="1" \
  -e API_URL="https://immich.mydomain.com/api/" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos" \
  salvoxia/immich-folder-album-creator:latest \
  /script/immich_auto_album.sh
```

To share new albums with users `User A` and `User B` as `editor`, use the following call:
```bash
docker run \
  -e SHARE_WITH="User A:User B" \
  -e SHARE_ROLE="editor" \
  -e UNATTENDED="1" \
  -e API_URL="https://immich.mydomain.com/api/" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos" \
  salvoxia/immich-folder-album-creator:latest \
  /script/immich_auto_album.sh
```

To share new albums with users `User A` and a user with mail address `userB@mydomain.com`, but `User A` should be an editor, use the following call:
```bash
docker run \
  -e SHARE_WITH="User A=editor:userB@mydomain.com" \
  -e UNATTENDED="1" \
  -e API_URL="https://immich.mydomain.com/api/" \
  -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -e ROOT_PATH="/external_libs/photos" \
  salvoxia/immich-folder-album-creator:latest \
  /script/immich_auto_album.sh
```

Per default these share settings are applied once when the album is created and remain unchanged if an asset is added to an album later. If you want to override the share state whenever an asset is added to an album you can set `UPDATE_ALBUM_PROPS_MODE` to `2`. Note that this will completely override all shared users, any changes made within Immich will be lost.


## Cleaning Up Albums

The script supports different run modes (option `-m`/`--mode` or env variable `MODE` for Docker). The default mode is `CREATE`, which is used to create albums.
The other two modes are `CLEANUP` and `DELETE_ALL`.
> [!CAUTION]  
> Regardless of the mode you are using, deleting albums cannot be undone! The only option is to let the script run again and create new albums base on the passed arguments and current assets in Immich.

To prevent accidental deletions, setting the mode to `CLEANUP` or `DELETE_ALL` alone will not actually delete any albums, but only perform a dry run. The dry run prints a list of albums that the script __would__ delete.  
To actually delete albums, the option `-d/--delete-confirm` (or env variable `DELETE_CONFIRM` for Docker) must be set.

### `CLEANUP`
The script will generate album names using the script's arguments and the assets found in Immich, but instead of creating the albums, it will delete them (if they exist). This is useful if a large number of albums was created with no/the wrong `--album-separator` or `--album-levels` settings.

### `DELETE_ALL`
> [!CAUTION]  
> As the name suggests, this mode blindly deletes **ALL** albums from Immich. Use with caution!


## Assets in Multiple Albums

By default, the script only fetches assets from Immich that are not assigned to any album yet. This makes querying assets in large libraries very fast. However, if assets should be part of either manually created albums as well as albums based on the folder structure, or if multiple script passes with different album level settings should create differently named albums with overlapping contents, the option `--find-assets-in-albums` (bare Python) or environment variable `FIND_ASSETS_IN_ALBUMS` (Docker) may be set.  
In that case, the script will request all assets from Immich and add them to their corresponding folders, even if the also are part of other albums.
> [!TIP]  
> This option can be especially useful when [Filtering for Assets](#filtering-for-assets).


## Setting Album Thumbnails

The script supports automatically setting album thumbnails by specifying the `--set-album-thumbnail` option (bare Python) or `SET_ALBUM_THUMBNAIL` environment variable (Docker). There are several options to choose from for thumbnail selection:
  - `first`: Sets the first image as thumbnail based on image creation timestamps
  - `last`: Sets the last image as thumbnail based on image creation timestamps
  - `random`: Sets the thumbnail to a random image

When using one of the values above, the thumbnail of an album will be updated whenever assets are added.

Furthermore, the script supports two additional modes that are applied  __even if no assets were added to the album__:
  - `random-all`: In this mode the thumbnail for __all albums__ will be shuffled every time the script runs, ignoring any `root_path`, `--ignore` or `--path-filter` values.
  - `random-filtered`: Using this mode, the thumbnail for an albums will be shuffled every run if the album is not ignored by `root_path` or due to usage of the `--ignore` or `--path-filter` options.
  
> [!CAUTION]  
> Updating album thumbnails cannot be reverted!

## Setting Album-Fine Properties

This script supports defining album properties on a per-folder basis. For example, it is possible to share albums with different users using different roles or disable comments and likes for different albums. For a full list of options see the example below.  
This is achieved by placing `.albumprops` files in each folder these properties should apply to later. The script will scan for all `.albumprops` files and apply the settings when creating albums or adding assets to existing albums.

### Prerequisites

This function requires that all `root_paths` passed to the script are also accessible to it on a file-system level.
  - Docker: All root paths must be mounted under the same path to the `immich-folder-album-creator` container as they are mounted to the Immich container
  - Docker: The container must run with a user/group ID that has read access to the mounted root paths to be able to discover and read the `.albumprops` files
  - Bare Python Script: The script must have access to all root paths under the same path as they are mounted into the Immich container
    Either mount the folders into Immich under the same path as they are on the Immich host, or create symlinks for the script to access

### `.albumprops` File Format

A file named `.albumprops` may be placed into any folder of an external library.
The file itself is a YAML formatted text file with the following properties:
```yaml
# Album Name overriding the album name generated from folder names
override_name: "Your images are in another album"
description: "This is a very informative text describing the album"
share_with:
  # either provide user name
  - user: "user1"
    role: "editor"
  # or provide user mail address
  - user: "user2@example.org"
    role: "viewer"
  # role is optional and defaults to "viewer" if not specified
  - user: "user3@example.org"
  # Special role "none" can be used to remove inherited users
  - user: "user4"
    role: "none"
# Set album thumbnail, valid values: first, last, random or fully qualified path of an asset that is (or will be) assigned to the album
thumbnail_setting: "first"
# Sort order in album, valid values: asc, desc
sort_order: "desc"
# Set the visibility of assets that are getting added to that album, valid values: archive, hidden, locked, timeline
visibility: 'timeline'
# Flag indicating whether assets in this albums can be commented on and liked
comments_and_likes_enabled: false
# Flag indicating whether properties should be inherited down the directory tree
inherit: true
# List of property names that should be inherited (if not specified, all properties are inherited)
inherit_properties:
  - "description"
  - "share_with"
  - "visibility"
```
All properties are optional.  
The scripts expects the file to be in UTF-8 encoding.

#### Property Inheritance

The script supports property inheritance from parent folders through the `inherit` and `inherit_properties` settings:

- **`inherit: true`**: Enables inheritance of properties from parent `.albumprops` files
- **`inherit_properties`**: Specifies which properties to inherit (if omitted, all properties are inherited)

##### Inheritance Rules

1. **Inheritance Chain**: Properties are inherited from the root path down to the current folder
2. **Property Precedence**: Properties in deeper folders override those in parent folders
3. **Inheritance Termination**: If a folder has `inherit: false` or no `inherit` property, while having a `.albumprops`.file, the inheritance chain stops at that folder

##### Special `share_with` Inheritance

The `share_with` property has special inheritance behavior:
- **Addition**: Users from parent folders are automatically included
- **Modification**: User roles can be changed by specifying the same user with a different role
- **Removal**: Users can be removed by setting their role to `"none"`

##### Album Merging Behavior

When multiple directories use the same `override_name` and contribute to a single album, the following rules apply:

1. **Most Restrictive Role Wins**: If the same user is specified with different roles across multiple directories, the most restrictive role is applied:
   - `viewer` is more restrictive than `editor`
   - Example: User specified as `editor` in one directory and `viewer` in another → final role is `viewer`

2. **User Removal is Permanent**: If a user is set to `role: "none"` in any directory contributing to the album, they cannot be re-added by other directories:
   - Once removed with `role: "none"`, the user is permanently excluded from that album
   - Subsequent attempts to add the same user with any role will be ignored

3. **User Accumulation**: Users from all contributing directories are combined, following the above precedence rules

This ensures consistent and predictable behavior when multiple folder structures contribute to the same album via `override_name`.


##### Inheritance Examples

**Example 1: Basic Inheritance**

`/photos/.albumprops`:
```yaml
inherit: true
description: "Family photos"
share_with:
  - user: "dad"
    role: "editor"
```

`/photos/2023/.albumprops`:
```yaml
inherit: true
share_with:
  - user: "mom"
    role: "viewer"
```

Result for `/photos/2023/vacation/`:
```yaml
# - description: "Family photos" (inherited)
# - share_with: dad (editor), mom (viewer)
```

**Example 2: Property Override and User Management**

`/photos/.albumprops`:
```yaml
inherit: true
description: "Family photos"
visibility: "timeline"
share_with:
  - user: "dad"
    role: "editor"
  - user: "mom" 
    role: "viewer"
```

`/photos/private/.albumprops`:
```yaml
inherit: true
inherit_properties: ["description"]  # Only inherit description
visibility: "archive"  # Override visibility
share_with:
  - user: "mom"
    role: "none"  # Remove mom from sharing
  - user: "admin"
    role: "editor"  # Add admin
```

Result for `/photos/private/secrets/`:
```yaml
# - description: "Family photos" (inherited)
# - visibility: "archive" (overridden, not inherited due to inherit_properties)
# - share_with: dad (editor, inherited), admin (editor, added)
# - mom is removed from sharing
```

**Example 3: Stopping Inheritance**

`/photos/.albumprops`:
```yaml
inherit: true
description: "Family photos"
share_with:
  - user: "family"
    role: "viewer"
```

`/photos/work/.albumprops`:
```yaml
inherit: false  # Stop inheritance
description: "Work photos"
share_with:
  - user: "colleague"
    role: "editor"
```

Result for `/photos/work/project/`:
```yaml
# - description: "Work photos" (from /photos/work/, no inheritance)
# - share_with: colleague (editor, no family member inherited)
```

**Example 4: Album Merging with `override_name`**

`/photos/2023/Christmas/.albumprops`:
```yaml
override_name: "Family Photos"
description: "Family photos"
inherit: true
share_with:
  - user: "dad"
    role: "editor"
```

`/photos/2023/Christmas/Cookies/.albumprops`:
```yaml
inherit: true
share_with:
  - user: "mom"
    role: "viewer"
```

`/photos/2023/Vacation/.albumprops`:
```yaml
override_name: "Family Photos"
description: "Family photos"
share_with:
  - user: "dad"
    role: "viewer"  # More restrictive than editor
```

Result: Single album "Family Photos" containing all photos from all three directories:
```yaml
# - name: "Family Photos" (from override_name)
# - description: "Family photos" (inherited/specified)
# - share_with: dad (viewer - most restrictive wins), mom (viewer)
```

**Example 5: User Removal with `role: "none"`**

`/photos/family/.albumprops`:
```yaml
override_name: "Shared Album"
share_with:
  - user: "dad"
    role: "editor"
  - user: "mom"
    role: "viewer"
  - user: "child"
    role: "viewer"
```

`/photos/family/private/.albumprops`:
```yaml
override_name: "Shared Album"  # Same album name
share_with:
  - user: "child"
    role: "none"  # Remove child from sharing
  - user: "grandpa"
    role: "editor"
```

`/photos/family/work/.albumprops`:
```yaml
override_name: "Shared Album"  # Same album name
share_with:
  - user: "child"
    role: "viewer"  # This will be ignored - child was set to "none"
  - user: "colleague"
    role: "viewer"
```

Result: Single album "Shared Album" containing photos from all directories:
```yaml
# - name: "Shared Album"
# - share_with: dad (editor), mom (viewer), grandpa (editor), colleague (viewer)
# - child is permanently removed and cannot be re-added
```

>[!IMPORTANT]  
>The `override_name` property makes it possible assign assets to an album that does not have anything to do with their folder name. That way, it is also possible to merge assets from different folders (even under different `root_paths`) into the same album.  
>If the script finds multiple `.albumprops` files using the same `override_name` property, it enforced that all properties that exist in at least one of the `.albumprops` files are identical in all files that use the same `override_name`. If this is not the case, the script will exit with an error.

>[!TIP]
> Note the possibility to set `thumbnail_setting` to an absolute asset path. This asset must be part of the album once the script has run for Immich to accept it as album thumbnail / cover. This is only possible in `.albumprops` files, as such a setting would not make much sense as a global option.

### Enabling `.albumprops` discovery

To enable Album-Fine Properties, pass the option `--read-album-properties` (Bare Python) or set the environment variable `READ_ALBUM_PROPERTIES` to `1` (Docker) to enable scanning for `.albumprops` files and use the values found there to created the albums.

### Property Precedence

In case the script is provided with `--share-with`, `--share-role`, `--archive`, `--set-album-thumbnail` options (or `SHARE_WITH`, `SHARE_ROLE`, `ARCHIVE`, or `SET_ALBUM_THUMBNAIL` environment variables for Docker), properties in `.albumprops` always take precedence. Options passed to the script only have effect if no `.albumprops` file is found for an album or the specific property is missing.

Example:
```yaml
share_with:
  - user: Dad
    role: editor
```
If the script is called with `--share-with "Mom"` and `--archive`, the album created from the folder the file above resides in will only be shared with user `Dad` using `editor` permissions, and assets will be archived. All other albums will be shared with user `Mom` (using `viewer` permissions, as defined by default) and assets will be archived.

### Example: Always add files in a specific folder to Immich Locked Folder

In order to always add files incoming to a specific external library folder to Immich's Locked Folder, add the following `.albumprops` file to that folder:
```yaml
visibility: 'locked'
```

## Mass Updating Album Properties

The script supports updating album properties after the fact, i.e. after they already have been created. Useful examples for this are mass sharing albums or enabling/disabling the "Comments and Likes" functionality. All album properties supported by `.albumprops` files (Refer to [Setting Album-Fine Properties](#setting-album-fine-properties)) are supported. They can be provided either by placing an `.albumprops` file in each folder, or by passing the appropriate argument to the script.
Updating already existing albums is done by setting the `--find-assets-in-albums` argument (or appropriate [environment variable](#environment-variables)) to discover assets that are already assigned to albums, and also setting the `--update-album-props-mode` argument ((or appropriate [environment variable](#environment-variables))).  
When setting `--update-album-props-mode` to `1`, all album properties __except__ the shared status are updated. When setting it to `2`, the shared status is updated as well.
By applying `--path-filter` and/or `--ignore` options, it is possible to get a more fine granular control over the albums to update.

>[!IMPORTANT]
> The shared status is always updated to match exactly the users and roles provided to the script, the changes are not additive.

### Examples:
1. Share all albums (either existing or newly ) created from a `Birthdays` folder with users `User A` and `User B`:
    ```bash
    python3 ./immich_auto_album.py \
      --find-assets-in-albums \
      --update-album-props-mode 2 \
      --share-with "User A" \
      --share-with "User B" \
      --path-filter "Birthdays/**" \
      /path/to/external/lib \
      https://immich.mydomain.com/api \
      thisIsMyApiKeyCopiedFromImmichWebGui
    ```

    To unshare the same albums simply run the same command without the `--share-with` arguments. The script will make sure all identified albums are shared with all people passed in `--share-with`, that is no-one.
    ```bash 
    python3 ./immich_auto_album.py \
      --find-assets-in-albums \
      --update-album-props-mode 2 \
      --path-filter "Birthdays/**" \
      /path/to/external/lib \
      https://immich.mydomain.com/api \
      thisIsMyApiKeyCopiedFromImmichWebGui
    ```

2. Disable comments and likes in all albums but the ones created from a `Birthdays` folder, without changing the "shared with" settings:
    ```bash
    python3 ./immich_auto_album.py \
      --find-assets-in-albums \
      --update-album-props-mode 1 \
      --disable-comments-an-likes \
      --ignore "Birthdays/**" \
      /path/to/external/lib \
      https://immich.mydomain.com/api \
      thisIsMyApiKeyCopiedFromImmichWebGui
    ```


## Asset Visibility & Locked Folder

In Immich, assets being 'archived' means they are hidden from the main timeline and only show up in their respective albums and the 'Archive' in the sidebar menu. Immich v1.133.0 also introduced the concept of a locked folder. The user must enter a PIN code to access the contents of the locked folder. Assets that are moved to the locked folder cannot be part of any albums and naturally are not displayed in the timeline.

This script supports both concepts with the option/environment variable `--visibility`/`VISIBILITY`. Allowed values are:
  - `archive`: Assets are archived after getting added to an album
  - `locked`: No albums get created, but all discovered assets after filtering are moved to the locked folder
  - `timeline`: All assets are shown in the timeline after getting added to an album

Visibility may be on an per-album basis using [Album Properties](#setting-album-fine-properties).
>[!IMPORTANT]  
>Archiving images has the side effect that they are no longer detected by the script with default options. This means that if an album that was created with the `--archive` option set is deleted from the Immich user interface, the script will no longer find the images even though they are no longer assigned to an album.  
To make the script find also archived images, run the script with the option `--find-archived-assets` or Docker environment variable `FIND_ARCHIVED_ASSETS=true`.

By combining `--find-archived-assets`/`FIND_ARCHIVED_ASSETS=true` with `--visibility timeline`/`VISIBILITY timeline`, archived assets can be 'un-archived'.

>[!WARNING]  
>If the script is used to delete albums using `--mode=CLEANUP` or `--mode=DELETE_ALL` with the `--archive` option set, the script will not respect [album-fine properties](#setting-album-fine-properties) for visibility but only the global option passed when running it in that mode! That way you can decide what visibility to set for assets after their albums have been deleted.

### Locked Folder Considerations
When setting `--visibility`/`VISIBILITY` to `locked`, the script will move all discovered assets to the Locked Folder, removing them from any albums they might already be part of. The affected assets are determined by the following options/environment variables:
  - `--find-archived-assets`/`FIND_ARCHIVED_ASSETS`
  - `--find-assets-in-albums`/`FIND_ASSETS_IN_ALBUMS`
  - `--ignore`/`IGNORE`
  - `--path-filter`/`PATH_FILTER`

> [!CAUTION]  
> When running with `--find-assets-in-albums`/`FIND_ASSETS_IN_ALBUMS` and `--visibility`/`VISIBILITY` set to `locked`, the script will move all assets for matching albums to the locked folder, leaving empty albums behind.
When also running with `--sync-mode`/`SYNC_MODE` set to `1` or `2`, those empty albums will be deleted after that as well!

Removing assets from the locked folder and making it available to the script again must be done using the Immich User Interface.


## Dealing with External Library Changes

Due to their nature, external libraries may be changed by the user without Immich having any say in it.  
Two examples of this are the user deleting or renaming folders in their external libraries after the script has created albums, or the user moving single files from one folder to another. The script would create new albums from renamed folders or add images to their new album after they have been moved.  
Immich itself deals with this by marking images/videos it no longer sees in their original location as "offline". This can lead to albums being completely populated by "offline" files only (if the folder was renamed or deleted) while they exist normally in a new album or with single images being offline in one album, while existing normally in their new albums.  
As of version 1.116.0, Immich no longer shows "offline" assets in the main timeline, but only in the Trash, together with deleted assets. If the trash is emptied, Immich forgets about these "offline" assets. If the asset is available again, it is removed from the trash and shows up as normal in the main timeline.

This script offers two levels of synchronization options to deal with these issues with an option called `Sync Mode`. It is an optional argument / environment variable that may have values from 0 to 2.
The following behaviors wil be triggered by the different values:
  - `0`: No syncing (default)
  - `1`: Delete all empty albums at the end of a run
  - `2`: Delete ("forget") all offline assets, then delete all empty albums

Option `1` leaves it up to the user to clear up "offline" assets by emptying the trash or restoring access to the files. Only if after any of these actions empty albums are left behind, they are automatically removed.  
Option `2` will first delete all "offline" assets automatically, then do the same with any empty albums left.  

> [!IMPORTANT]  
> For Immich v1.116.0 - v1.127.x finding offline assets has been broken. Immich fixed the issue with v1.128.0.

> [!IMPORTANT]  
> If your library is on a network share or external drive that might be prone to not being available all the time, avoid using `Sync Mode = 2`.

> [!CAUTION]  
> It is __not__ possible for the script to distinguish between an album that was left behind empty after Offline Asset Removal and a manually created album with no images added to it! All empty albums of that user will be deleted!

It is up to you whether you want to use the full capabilities Sync Mode offers, parts of it or none.  
An example for the Immich `docker-compose.yml` stack when using full Sync Mode might look like this:

### `docker-compose` example passing the API key as environment variable
```yml
#
# WARNING: Make sure to use the docker-compose.yml of the current release:
#
# https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml
#
# The compose file on main may not be compatible with the latest release.
#

name: immich

services:
  immich-server:
    container_name: immich_server
    volumes:
     - /path/to/my/photos:/external_libs/photos
  ...
  immich-folder-album-creator:
    container_name: immich_folder_album_creator
    image: salvoxia/immich-folder-album-creator:latest
    restart: unless-stopped
    environment:
      API_URL: http://immich_server:2283/api
      API_KEY: "This_Is_My_API_Key_Generated_In_Immich"
      ROOT_PATH: /external_libs/photos
      # Run every full hour
      CRON_EXPRESSION: "0 * * * *"
      TZ: Europe/Berlin
      # Remove offline assets and delete empty albums after each run
      SYNC_MODE: "2"
```

### `docker-compose` example using a secrets file for the API key
```yml
#
# WARNING: Make sure to use the docker-compose.yml of the current release:
#
# https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml
#
# The compose file on main may not be compatible with the latest release.
#

name: immich

services:
  immich-server:
    container_name: immich_server
    volumes:
     - /path/to/my/photos:/external_libs/photos
  ...
  immich-folder-album-creator:
    container_name: immich_folder_album_creator
    image: salvoxia/immich-folder-album-creator:latest
    restart: unless-stopped
    # Use a UID/GID that has read access to the mounted API key file 
    user: 1001:1001
    volumes:
     - /path/to/secret/file:/immich_api_key.secret:ro
    environment:
      API_URL: http://immich_server:2283/api
      API_KEY_FILE: "/immich_api_key.secret"
      ROOT_PATH: /external_libs/photos
      # Run every full hour
      CRON_EXPRESSION: "0 * * * *"
      TZ: Europe/Berlin
      # Remove offline assets and delete empty albums after each run
      SYNC_MODE: "2"
```
