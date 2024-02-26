# Immich Folder Album Creator

This is a python script designed to automatically create albums in [Immich](https://immich.app/) from a folder structure mounted into the Immich container.
This is useful for automatically creating and populating albums for external libraries.

__Current compatibility:__ Immich v1.95.x and below

## Disclaimer
This script is mostly based on the following original script: [REDVM/immich_auto_album.py](https://gist.github.com/REDVM/d8b3830b2802db881f5b59033cf35702)

## Installation

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
```bash
python3 ./immich_auto_album.py
usage: immich_auto_album.py [-h] [-u] [-c CHUNK_SIZE] [-C FETCH_CHUNK_SIZE] [-l {CRITICAL,ERROR,WARNING,INFO,DEBUG}] root_path api_url api_key

Create Immich Albums from an external library path based on the top level folders

positional arguments:
  root_path             The external libarary's root path in Immich
  api_url               The root API URL of immich, e.g. https://immich.mydomain.com/api/
  api_key               The Immich API Key to use

options:
  -h, --help            show this help message and exit
  -u, --unattended      Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob. (default: False)
  -c CHUNK_SIZE, --chunk-size CHUNK_SIZE
                        Maximum number of assets to add to an album with a single API call (default: 2000)
  -C FETCH_CHUNK_SIZE, --fetch-chunk-size FETCH_CHUNK_SIZE
                        Maximum number of assets to fetch with a single API call (default: 5000)
  -l {CRITICAL,ERROR,WARNING,INFO,DEBUG}, --log-level {CRITICAL,ERROR,WARNING,INFO,DEBUG}
                        Log level to use (default: INFO)
```

### Docker

A Docker image is provided to be used as a runtime environment. It can be used to either run the script manually, or via cronjob by providing a crontab expression to the container. The container can then be added to the Immich compose stack directly.

#### Environment Variables
The environment variables are analoguous to the script's command line arguments.

| Environment varible   |  Mandatory? | Description   |
| :------------------- | :----------- | :------------ |
| ROOT_PATH            | yes | The external libarary's root path in Immich                                      |
| API_URL            | yes | The root API URL of immich, e.g. https://immich.mydomain.com/api/                  |
| API_KEY            | yes | The Immich API Key to use                                                          |
| CHUNK_SIZE         | no | Maximum number of assets to add to an album with a single API call (default: 2000)  |
| FETCH_CHUNK_SIZE   | no | Maximum number of assets to fetch with a single API call (default: 5000)            |
| LOG_LEVEL          | no | Log level to use (default: INFO), allowed values: CRITICAL,ERROR,WARNING,INFO,DEBUG |

#### Run the container with Docker

To perform a manually triggered run, use the following command:

```bash
docker run -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest /script/immich_auto_album.sh
```

To set up the container to periodically run the script, give it a name, pass the TZ variable and a valid crontab expression as environment variable. This example runs the script every hour:
```bash
docker run --name immich-folder-album-creator -e TZ="Europe/Berlin" -e CRON_EXPRESSION="0 * * * *" -e API_URL="https://immich.mydomain.com/api/" -e API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" -e ROOT_PATH="/external_libs/photos" salvoxia/immich-folder-album-creator:latest
```

### Run the container with Docker-Compose

Adding the container to Immich's `docker-compose.yml` file:
```yml
version: "3.8"

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

## How it works

The script utilizies [Immich's REST API](https://immich.app/docs/api/) to query all images indexed by Immich, extract the folder for all images that are in the top level of a provided `root_path`, then creates albums with the names of these folders (if not yet exists) and adds the images to the correct albums.

It is important to understand the concept of `root_path`. Suppose you provide an external library to Immich under the path `/external_libs/photos`.
The folder structure of `photos` might look like this:
```
/external_libs/photos/Birthdays/John
/external_libs/photos/Birthdays/Jane
/external_libs/photos/Skiing 2023
/external_libs/photos/Vacation 2020 02
```
If you set `root_path` to `/external_libs/photos`, the script will create three albums:
 - Birthdays
 - Skiing 2023
 - Vacation 2020 02

All photos from John's and Jane's birthdays will be added to the `Birthdays` album.

If you set `root_path` to `/external_libs/photos/Birthdays`, only two albums will be created:
 - John
 - Jane

Since Immich does not support nested albums ([yet?](https://github.com/immich-app/immich/discussions/2073)), neither does this script.

