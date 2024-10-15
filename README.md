[![Docker][docker-image]][docker-url]

[docker-image]: https://img.shields.io/docker/pulls/salvoxia/immich-folder-album-creator.svg
[docker-url]: https://hub.docker.com/r/salvoxia/immich-folder-album-creator/

# Immich Folder Album Creator

This is a python script designed to automatically create albums in [Immich](https://immich.app/) from a folder structure mounted into the Immich container.
This is useful for automatically creating and populating albums for external libraries.
Using the provided docker image, the script can simply be added to the Immich compose stack and run along the rest of Immich's containers.

__Current compatibility:__ Immich v1.106.1 - v1.118.x

## Disclaimer
This script is mostly based on the following original script: [REDVM/immich_auto_album.py](https://gist.github.com/REDVM/d8b3830b2802db881f5b59033cf35702)

# Table of Contents
1. [Usage (Bare Python Script)](#bare-python-script)
2. [Usage (Docker)](#docker)
3. [Choosing the correct `root_path`](#choosing-the-correct-root_path)
4. [How It Works (with Examples)](#how-it-works)
5. [Filtering](#filtering)
6. [Automatic Album Sharing](#automatic-album-sharing)
7. [Cleaning Up Albums](#cleaning-up-albums)
8. [Assets in Multiple Albums](#assets-in-multiple-albums)
9. [Setting Album Thumbnails](#setting-album-thumbnails)
10. [Automatic Archiving](#automatic-archiving)
11. [Dealing with External Library Changes](#dealing-with-external-library-changes)

## Usage
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
    usage: immich_auto_album.py [-h] [-r ROOT_PATH] [-u] [-a ALBUM_LEVELS] [-s ALBUM_SEPARATOR] [-c CHUNK_SIZE] [-C FETCH_CHUNK_SIZE] [-l {CRITICAL,ERROR,WARNING,INFO,DEBUG}] [-k] [-i IGNORE] [-m {CREATE,CLEANUP,DELETE_ALL}] [-d] [-x SHARE_WITH] [-o {viewer,editor}] [-S {0,1,2}]
                            [-O {False,asc,desc}] [-A] [-f PATH_FILTER] [--set-album-thumbnail {first,last,random,random-all,random-filtered}] [-v] [--find-archived-assets]
                            root_path api_url api_key

    Create Immich Albums from an external library path based on the top level folders

    positional arguments:
      root_path             The external libarary's root path in Immich
      api_url               The root API URL of immich, e.g. https://immich.mydomain.com/api/
      api_key               The Immich API Key to use

    options:
      -h, --help            show this help message and exit
      -r ROOT_PATH, --root-path ROOT_PATH
                            Additional external libarary root path in Immich; May be specified multiple times for multiple import paths or external libraries. (default: None)
      -u, --unattended      Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob. (default: False)
      -a ALBUM_LEVELS, --album-levels ALBUM_LEVELS
                            Number of sub-folders or range of sub-folder levels below the root path used for album name creation. Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be 0. If a range should be set, the start level and end level
                            must be separated by a comma like '<startLevel>,<endLevel>'. If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>. (default: 1)
      -s ALBUM_SEPARATOR, --album-separator ALBUM_SEPARATOR
                            Separator string to use for compound album names created from nested folders. Only effective if -a is set to a value > 1 (default: )
      -c CHUNK_SIZE, --chunk-size CHUNK_SIZE
                            Maximum number of assets to add to an album with a single API call (default: 2000)
      -C FETCH_CHUNK_SIZE, --fetch-chunk-size FETCH_CHUNK_SIZE
                            Maximum number of assets to fetch with a single API call (default: 5000)
      -l {CRITICAL,ERROR,WARNING,INFO,DEBUG}, --log-level {CRITICAL,ERROR,WARNING,INFO,DEBUG}
                            Log level to use (default: INFO)
      -k, --insecure        Set to true to ignore SSL verification (default: False)
      -i IGNORE, --ignore IGNORE
                            Use either literals or glob-like patterns to ignore assets for album name creation. This filter is evaluated after any values passed with --path-filter. May be specified multiple times. (default: None)
      -m {CREATE,CLEANUP,DELETE_ALL}, --mode {CREATE,CLEANUP,DELETE_ALL}
                            Mode for the script to run with. CREATE = Create albums based on folder names and provided arguments; CLEANUP = Create album nmaes based on current images and script arguments, but delete albums if they exist; DELETE_ALL = Delete all albums. If the mode is anything but CREATE, --unattended does not have any effect. Only performs deletion if -d/--delete-confirm option is set, otherwise only performs a dry-run. (default: CREATE)
      -d, --delete-confirm  Confirm deletion of albums when running in mode CLEANUP or DELETE_ALL. If this flag is not set, these modes will perform a dry run only. Has no effect in mode CREATE (default: False)
      -x SHARE_WITH, --share-with SHARE_WITH
                            A user name (or email address of an existing user) to share newly created albums with. Sharing only happens if the album was actually created, not if new assets were added to an existing album. If the the share role should be specified by user, the format
                            <userName>=<shareRole> must be used, where <shareRole> must be one of 'viewer' or 'editor'. May be specified multiple times to share albums with more than one user. (default: None)
      -o {viewer,editor}, --share-role {viewer,editor}
                            The default share role for users newly created albums are shared with. Only effective if --share-with is specified at least once and the share role is not specified within --share-with. (default: viewer)
      -S {0,1,2}, --sync-mode {0,1,2}
                            Synchronization mode to use. Synchronization mode helps synchronizing changes in external libraries structures to Immich after albums have already been created. Possible Modes: 0 = do nothing; 1 = Delete any empty albums; 2 = Delete offline assets AND any empty albums (default: 0)
      -O {False,asc,desc}, --album-order {False,asc,desc}
                            Set sorting order for newly created albums to newest or oldest file first, Immich defaults to newest file first (default: False)
      -A, --find-assets-in-albums
                            By default, the script only finds assets that are not assigned to any album yet. Set this option to make the script discover assets that are already part of an album and handle them as usual. If --find-archived-assets is set as well, both options apply. (default:
                            False)
      -f PATH_FILTER, --path-filter PATH_FILTER
                            Use either literals or glob-like patterns to filter assets before album name creation. This filter is evaluated before any values passed with --ignore. May be specified multiple times. (default: None)
      --set-album-thumbnail {first,last,random,random-all,random-filtered}
                            Set first/last/random image as thumbnail for newly created albums or albums assets have been added to. If set to random-filtered, thumbnails are shuffled for all albums whose assets would not be filtered out or ignored by the ignore or path-filter options, even if no assets were added during the run. If set to random-all, the thumbnails for ALL albums will be shuffled on every run. (default: None)
      -v, --archive         Set this option to automatically archive all assets that were newly added to albums. If this option is set in combination with --mode = CLEANUP or DELETE_ALL, archived images of deleted albums will be unarchived. Archiving hides the assets from Immich's timeline.
                            (default: False)
      --find-archived-assets
                            By default, the script only finds assets that are not archived in Immich. Set this option to make the script discover assets that are already archived. If -A/--find-assets-in-albums is set as well, both options apply. (default: False)
    ```

__Plain example without optional arguments:__
```bash
python3 ./immich_auto_album.py /path/to/external/lib https://immich.mydomain.com/api thisIsMyApiKeyCopiedFromImmichWebGui
```

### Docker

A Docker image is provided to be used as a runtime environment. It can be used to either run the script manually, or via cronjob by providing a crontab expression to the container. The container can then be added to the Immich compose stack directly.

#### Environment Variables
The environment variables are analoguous to the script's command line arguments.

| Environment varible   |  Mandatory? | Description   |
| :------------------- | :----------- | :------------ |
| ROOT_PATH            | yes | A single or a comma separated list of import paths for external libraries in Immich. <br>Refer to [Choosing the correct `root_path`](#choosing-the-correct-root_path).|
| API_URL            | yes | The root API URL of immich, e.g. https://immich.mydomain.com/api/ |
| API_KEY            | yes | The Immich API Key to use  
| CRON_EXPRESSION    | yes | A [crontab-style expression](https://crontab.guru/) (e.g. `0 * * * *`) to perform album creation on a schedule (e.g. every hour). |
| ALBUM_LEVELS       | no | Number of sub-folders or range of sub-folder levels below the root path used for album name creation. Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be `0`. If a range should be set, the start level and end level must be separated by a comma. <br>Refer to [How it works](#how-it-works) for a detailed explanation and examples. |
| ALBUM_SEPARATOR    | no | Separator string to use for compound album names created from nested folders. Only effective if `-a` is set to a value `> 1`(default: "` `") |
| CHUNK_SIZE         | no | Maximum number of assets to add to an album with a single API call (default: `2000`)  |
| FETCH_CHUNK_SIZE   | no | Maximum number of assets to fetch with a single API call (default: `5000`)            |
| LOG_LEVEL          | no | Log level to use (default: INFO), allowed values: `CRITICAL`,`ERROR`,`WARNING`,`INFO`,`DEBUG` |
| INSECURE           | no | Set to `true` to disable SSL verification for the Immich API server, useful for self-signed certificates (default: `false`), allowed values: `true`, `false` |
| IGNORE             | no | A colon `:` separated list of literals or glob-style patterns that will cause an image to be ignored if found in its path. |
| MODE               | no | Mode for the script to run with. <br> __`CREATE`__ = Create albums based on folder names and provided arguments<br>__`CLEANUP`__ = Create album nmaes based on current images and script arguments, but delete albums if they exist <br> __`DELETE_ALL`__ = Delete all albums. <br> If the mode is anything but `CREATE`, `--unattended` does not have any effect. <br> (default: `CREATE`). <br>Refer to [Cleaning Up Albums](#cleaning-up-albums). |
| DELETE_CONFIRM     | no | Confirm deletion of albums when running in mode `CLEANUP` or `DELETE_ALL`. If this flag is not set, these modes will perform a dry run only. Has no effect in mode `CREATE` (default: `False`). <br>Refer to [Cleaning Up Albums](#cleaning-up-albums).|
| SHARE_WITH     | no | A single or a colon (`:`) separated list of existing user names (or email addresses of existing users) to share newly created albums with. If the the share role should be specified by user, the format <userName>=<shareRole> must be used, where <shareRole> must be one of `viewer` or `editor`. May be specified multiple times to share albums with more than one user. (default: None) Sharing only happens if an album is actually created, not if new assets are added to it.  <br>Refer to [Automatic Album Sharing](#automatic-album-sharing).|
| SHARE_ROLE     | no | The role for users newly created albums are shared with. Only effective if `SHARE_WITH` is not empty and no explicit share role was specified for at least one user. (default: viewer), allowed values: `viewer`, `editor` |
| SYNC_MODE     | no | Synchronization mode to use. Synchronization mode helps synchronizing changes in external libraries structures to Immich after albums have already been created. Possible Modes: <br>`0` = do nothing<br>`1` = Delete any empty albums<br>`2` =  Delete offline assets AND any empty albums<br>(default: `0`)<br>Refer to [Dealing with External Library Changes](#dealing-with-external-library-changes). |
| ALBUM_ORDER     | no | Set sorting order for newly created albums to newest (`desc`) or oldest (`asc`) file first, Immich defaults to newest file first, allowed values: `asc`, `desc` |
| FIND_ASSETS_IN_ALBUMS     | no | By default, the script only finds assets that are not assigned to any album yet. Set this option to make the script discover assets that are already part of an album and handle them as usual. If --find-archived-assets is set as well, both options apply. (default: `False`)<br>Refer to [Assets in Multiple Albums](#assets-in-multiple-albums). |
| PATH_FILTER     | no | A colon `:` separated list of literals or glob-style patterns to filter assets before album name creation. (default: ``)<br>Refer to [Filtering](#filtering). |
| SET_ALBUM_THUMBNAIL | no | Set first/last/random image as thumbnail (based on image creation timestamp) for newly created albums or albums assets have been added to.<br> Allowed values: `first`,`last`,`random`,`random-filtered`,`random-all`<br>If set to `random-filtered`, thumbnails are shuffled for all albums whose assets would not be filtered out or ignored by the `IGNORE` or `PATH_FILTER` options, even if no assets were added during the run. If set to random-all, the thumbnails for ALL albums will be shuffled on every run. (default: `None`)<br>Refer to [Setting Album Thumbnails](#setting-album-thumbnails). |
| ARCHIVE     | no | Set this option to automatically archive all assets that were newly added to albums.<br>If this option is set in combination with `MODE` = `CLEANUP` or `DELETE_ALL`, archived images of deleted albums will be unarchived.<br>Archiving hides the assets from Immich's timeline. (default: `False`)<br>Refer to [Automatic Archiving](#automatic-archiving). |
| FIND_ARCHIVED_ASSETS     | no | By default, the script only finds assets that are not archived in Immich. Set this option make the script discover assets that are already archived. If -A/--find-assets-in-albums is set as well, both options apply. (default: `False`)<br>Refer to [Automatic Archiving](#automatic-archiving). |

#### Run the container with Docker

To perform a manually triggered __dry run__ (only list albums that __would__ be created), use the following command:
```bash
docker run -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest /script/immich_auto_album.sh
```
To actually create albums after performing a dry run, use the following command (setting the `UNATTENDED` environment variable):
```bash
docker run -e UNATTENDED="1" -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest /script/immich_auto_album.sh
```

To set up the container to periodically run the script, give it a name, pass the TZ variable and a valid crontab expression as environment variable. This example runs the script every hour:
```bash
docker run --name immich-folder-album-creator -e TZ="Europe/Berlin" -e CRON_EXPRESSION="0 * * * *" -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest
```

If your external library uses multiple import paths or you have set up multiple external libraries, you can pass multiple paths in `ROOT_PATH` by setting it to a comma separated list of paths:  
```bash
docker run --name immich-folder-album-creator -e TZ="Europe/Berlin" -e CRON_EXPRESSION="0 * * * *" -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos,/external_libs/more_photos" salvoxia/immich-folder-album-creator:latest
```

### Run the container with Docker-Compose

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
    environment:
      API_URL: http://immich_server:3001/api
      API_KEY: xxxxxxxxxxxxxxxxx
      ROOT_PATH: /external_libs/photos
      CRON_EXPRESSION: "0 * * * *"
      TZ: Europe/Berlin

```

## Choosing the correct `root_path`
The root path  `/path/to/external/lib/` is the path you have mounted your external library into the Immich container.  
If you are following [Immich's External library Documentation](https://immich.app/docs/guides/external-library), you are using an environment variable called `${EXTERNAL_PATH}` which is mounted to `/usr/src/app/external` in the Immich container. Your `root_path` to pass to the script is `/usr/src/app/external`.

## How it works

The script utilizies [Immich's REST API](https://immich.app/docs/api/) to query all images indexed by Immich, extract the folder for all images that are in the top level of any provided `root_path`, then creates albums with the names of these folders (if not yet exists) and adds the images to the correct albums.

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
 - `2020 02 Feb` (containing all images from `2020/02 Feb` itself, `2020/02 Feb/Vacation` and `2020/02 Aug/Vacation`)
 - `Birthdays John` (containing all imags from `Birthdays/John`)
 - `Birthdays Jane` (containing all imags from `Birthdays/John`)
 - `Skiing 2023`

 Albums created for `root_path = /external_libs/photos`, `--album-levels = 3` and `--album-separator " - "` :
 - `2020` (containing all images from `2020` itself, if any)
 - `2020 - 02 Feb` (containing all images from `02 Feb` itself, if any)
 - `2020 - 02 Feb - Vacation` (containing all imags from `2020/02 Feb/Vacation`)
 - `2020 - 08 Aug - Vacation` (containing all imags from `2020/02 Aug/Vacation`)
 - `Birthdays - John`
 - `Birthdays - Jane`
 - `Skiing 2023`

  Albums created for `root_path = /external_libs/photos`, `--album-levels = -1` and `--album-separator " - "` :
 - `2020` (containing all images from `2020` itself, if any)
 - `02 Feb` (containing all images from `2020/02 Feb` itself, if any)
 - `Vacation` (containing all images from `2020/02 Feb/Vacation` AND `2020/08 Aug/Vacation`)
 - `John` (containing all imags from `Birthdays/John`)
 - `Jane` (containing all imags from `Birthdays/Jane`)
 - `Skiing 2023`
 
 ### Album Level Ranges

 It is possible to specify not just a number for `--album-levels`, but a range from level x to level y in the folder structure that should make up an album's name:  
 `--album-levels="2,3"`  
 The range is applied to the folder structure beneath `root_path` from the top for positive levels and from the bottom for negative levels.
 Suppose the following folder structure for an external library with the script's `root_path` set to `/external_libs/photos`:
 ```
/external_libs/photos/2020/2020 02 Feb/Vacation
/external_libs/photos/2020/2020 08 Aug/Vacation
```
 - `--album-levels="2,3"` will create albums (for this folder structure, this is equal to `--album-levels="-2"`)
    - `2020 02 Feb Facation`
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
When using Docker, the environment variable `IGNORE` accepts a semicolon-separated `:` list of literals or glob-style patterns. If an image's path **below the root path** matches the pattern, it will be ignored.  

### Filtering for Assets
The option `-f / ---path-filter` can be specified multiple times for each literal or glob-style path pattern. 
When using Docker, the environment variable `PATH_FILTER` accepts a semicolon-separated `:` of literals or glob-style patterns. If an image's path **below the root path** does **NOT** match the pattern, it will be ignored.

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


## Automatic Album Sharing

The scripts support sharing newly created albums with a list of existing users. The sharing role (`viewer` or `editor`) can be specified for all users at once or individually per user.

### Album Sharing Examples (Bare Python Script)
Two arguments control this feature:
  - `-o / --share-role`: The default role for users an album is shared with. Allowed values are `viewer` or `editor`. This argument is optional and defaults to `viewer`.
  - `-x / --share-with`: Specify once per user to share with. The value should be either the user name or the user's email address as specified in Immich. If the user name is used and it contains blanks ` `, it must be wrapped in double quotes `"`. To override the default share role and specify a role explicitly for this user, the format `<userName>=<shareRole>` must be used (refer to examples below).

To share new albums with users `User A` and `User B` as `viewer`, use the following call:
```bash
python3 ./immich_auto_album.py --share-with "User A" --share-with "User B" /path/to/external/lib https://immich.mydomain.com/api thisIsMyApiKeyCopiedFromImmichWebGui
```

To share new albums with users `User A` and `User B` as `editor`, use the following call:
```bash
python3 ./immich_auto_album.py --share-with "User A" --share-with "User B" --share-role "editor" /path/to/external/lib https://immich.mydomain.com/api thisIsMyApiKeyCopiedFromImmichWebGui
```

To share new albums with users `User A` and a user with mail address `userB@mydomain.com`, but `User A` should be an editor, use the following call:
```bash
python3 ./immich_auto_album.py --share-with "User A=editor" --share-with "userB@mydomain.com" /path/to/external/lib https://immich.mydomain.com/api thisIs
```


### Album Sharing Examples (Docker)
Two environment variables control this feature:
  - `SHARE_ROLE`: The default role for users an album is shared with. Allowed values are `viewer` or `editor`. This argument is optional and defaults to `viewer`.
  - `SHARE_WITH`: A colon `:` separated list of either names or email addresses (or a mix) of existing users. To override the default share role and specify a role explicitly for each user, the format `<userName>=<shareRole>` must be used (refer to examples below).

To share new albums with users `User A` and `User B` as `viewer`, use the following call:
```bash
docker run -e SHARE_WITH="User A:User B" -e UNATTENDED="1" -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest /script/immich_auto_album.sh
```

To share new albums with users `User A` and `User B` as `editor`, use the following call:
```bash
docker run -e SHARE_WITH="User A:User B" -e SHARE_ROLE="editor" -e UNATTENDED="1" -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest /script/immich_auto_album.sh
```

To share new albums with users `User A` and a user with mail address `userB@mydomain.com`, but `User A` should be an editor, use the following call:
```bash
docker run -e SHARE_WITH="User A=editor:userB@mydomain.com" -e UNATTENDED="1" -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest /script/immich_auto_album.sh
```


## Cleaning Up Albums

The script supports differnt run modes (option `-m`/`--mode` or env variable `MODE` for Docker). The default mode is `CREATE`, which is used to create albums.
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

## Automatic Archiving

In Immich, 'archiving' an image means to hide it from the main timeline.  
This script is capable of automatically archiving images it added to albums during the run to hide them from the timeline. To achieve this, run the script with option `--archive` or Docker environment variable `ARCHIVE=true`.  

>[!IMPORTANT]  
>Archiving images has the side effect that they are no longer detected by the script with default options. This means that if an album that was created with the `--archive` option set is deleted from the Immich user interface, the script will no longer find the images even though they are no longer assigned to an album.  
To make the script find also archived images, run the script with the option `--find-archived-assets` or Docker environment variable `FIND_ARCHIVED_ASSETS=true`.

>[!WARNING]  
>If the script is used to delete albums using `--mode=CLEANUP` or `--mode=DELETE_ALL` with the `--archive` option set, the script will automatically unarchive all assets of deleted albums to revert them to their prior state. If you manually archived selected assets in albums, this will be reverted!

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
> If your library is on a network share or external drive that might be prone to not being available all the time, avoid using `Sync Mode = 2`.

> [!CAUTION]  
> It is __not__ possible for the script to distinguish between an album that was left behind empty after Offline Asset Removal and a manually created album with no images added to it! All empty albums of that user will be deleted!

It is up to you whether you want to use the full capabilities Sync Mode offers, parts of it or none.  
An example for the Immich `docker-compose.yml` stack when using full Sync Mode might look like this:
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
      API_URL: http://immich_server:3001/api
      API_KEY: xxxxxxxxxxxxxxxxx
      ROOT_PATH: /external_libs/photos
      CRON_EXPRESSION: "0 * * * *"
      TZ: Europe/Berlin
      # Remove offline assets and delete empty albums after each run
      SYNC_MODE: "2"
```
