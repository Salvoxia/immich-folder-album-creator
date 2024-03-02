import requests
import os
import argparse
import logging
import sys
import datetime
from collections import defaultdict


parser = argparse.ArgumentParser(description="Create Immich Albums from an external library path based on the top level folders", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("root_path", help="The external libarary's root path in Immich")
parser.add_argument("api_url", help="The root API URL of immich, e.g. https://immich.mydomain.com/api/")
parser.add_argument("api_key", help="The Immich API Key to use")
parser.add_argument("-u", "--unattended", action="store_true", help="Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob.")
parser.add_argument("-a", "--album-levels", default=1, type=int, help="Number of levels of sub-folder for which to create separate albums")
parser.add_argument("-s", "--album-separator", default=" ", type=str, help="Separator string to use for compound album names created from nested folders. Only effective if -a is set to a value > 1")
parser.add_argument("-c", "--chunk-size", default=2000, type=int, help="Maximum number of assets to add to an album with a single API call")
parser.add_argument("-C", "--fetch-chunk-size", default=5000, type=int, help="Maximum number of assets to fetch with a single API call")
parser.add_argument("-l", "--log-level", default="INFO", choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'], help="Log level to use")
args = vars(parser.parse_args())
# set up logger to log in logfmt format
logging.basicConfig(level=args["log_level"], stream=sys.stdout, format='time=%(asctime)s level=%(levelname)s msg=%(message)s')
logging.Formatter.formatTime = (lambda self, record, datefmt=None: datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).astimezone().isoformat(sep="T",timespec="milliseconds"))


root_path = args["root_path"]
root_url = args["api_url"]
api_key = args["api_key"]
number_of_images_per_request = args["chunk_size"]
number_of_assets_to_fetch_per_request = args["fetch_chunk_size"]
unattended = args["unattended"]
album_Levels = args["album_levels"]
album_level_separator = args["album_separator"]
logging.debug("root_path = %s", root_path)
logging.debug("root_url = %s", root_path)
logging.debug("api_key = %s", api_key)
logging.debug("number_of_images_per_request = %d", number_of_images_per_request)
logging.debug("number_of_assets_to_fetch_per_request = %d", number_of_assets_to_fetch_per_request)
logging.debug("unattended = %s", unattended)
logging.debug("album_Levels = %d", album_Levels)
logging.debug("album_level_separator = %s", album_level_separator)

# Yield successive n-sized 
# chunks from l. 
def divide_chunks(l, n): 
      
    # looping till length l 
    for i in range(0, len(l), n):  
        yield l[i:i + n] 
  

requests_kwargs = {
    'headers' : {
        'x-api-key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
}
if root_path[-1] != '/':
    root_path = root_path + '/'
if root_url[-1] != '/':
    root_url = root_url + '/'

logging.info("Requesting all assets")
assets = []
# Initial API call, let's fetch our first chunk
r = requests.get(root_url+'asset?take='+str(number_of_assets_to_fetch_per_request), **requests_kwargs)
assert r.status_code == 200
logging.debug("Received %s assets with chunk 1", len(r.json()))
assets = assets + r.json()

# If we got a full chunk size back, let's perfrom subsequent calls until we get less than a full chunk size
skip = 0
while len(r.json()) == number_of_assets_to_fetch_per_request:
    skip += number_of_assets_to_fetch_per_request
    r = requests.get(root_url+'asset?take='+str(number_of_assets_to_fetch_per_request)+'&skip='+str(skip), **requests_kwargs)
    if skip == number_of_assets_to_fetch_per_request and assets == r.json():
        logging.info("Non-chunked Immich API detected, stopping fetching assets since we already got all in our first call")
        break
    assert r.status_code == 200
    logging.debug("Received %s assets with chunk", len(r.json()))
    assets = assets + r.json()
logging.info("%d photos found", len(assets))



logging.info("Sorting assets to corresponding albums using folder name")
album_to_assets = defaultdict(list)
for asset in assets:
    asset_path = asset['originalPath']
    if root_path not in asset_path:
        continue
    # Chunks of the asset's path below root_path
    path_chunks = asset_path.replace(root_path, '').split('/') 
    # A single chunk means it's just the image file in no sub folder, ignore
    if len(path_chunks) == 1:
        continue
    album_name_chunks = ()
    # either use as many path chunks as we have (excluding the asset name itself),
    # or the specified album levels
    album_name_chunk_size = min(len(path_chunks)-1, album_Levels)
    # Copy album name chunks from the path to use as album name
    album_name_chunks = path_chunks[:album_name_chunk_size]
    album_name = album_level_separator.join(album_name_chunks)
    # Check that the extracted album name is not actually a file name in root_path
    album_to_assets[album_name].append(asset['id'])

album_to_assets = {k:v for k, v in sorted(album_to_assets.items(), key=(lambda item: item[0]))}

logging.info("%d albums identified", len(album_to_assets))
logging.info("Album list: %s", list(album_to_assets.keys()))
if not unattended:
    print("Press Enter to continue, Ctrl+C to abort")
    input()


album_to_id = {}

logging.info("Listing existing albums on immich")
r = requests.get(root_url+'album', **requests_kwargs)
assert r.status_code == 200
albums = r.json()
album_to_id = {album['albumName']:album['id'] for album in albums }
logging.info("%d existing albums identified", len(albums))


logging.info("Creating albums if needed")
cpt = 0
for album in album_to_assets:
    if album in album_to_id:
        continue
    data = {
        'albumName': album,
        'description': album
    }
    r = requests.post(root_url+'album', json=data, **requests_kwargs)
    assert r.status_code in [200, 201]
    album_to_id[album] = r.json()['id']
    logging.info('Album %s added!', album)
    cpt += 1
logging.info("%d albums created", cpt)


logging.info("Adding assets to albums")
# Note: Immich manages duplicates without problem, 
# so we can each time ad all assets to same album, no photo will be duplicated 
for album, assets in album_to_assets.items():
    id = album_to_id[album]
    
    # Divide our assets into chunks of number_of_images_per_request,
    # So the API can cope
    assets_chunked = list(divide_chunks(assets, number_of_images_per_request))
    for assets_chunk in assets_chunked:
        data = {'ids':assets_chunk}
        r = requests.put(root_url+f'album/{id}/assets', json=data, **requests_kwargs)
        if r.status_code not in [200, 201]:
            print(album)
            print(r.json())
            print(data)
            continue
        assert r.status_code in [200, 201]
        response = r.json()

        cpt = 0
        for res in response:
            if not res['success']:
                if  res['error'] != 'duplicate':
                    logging.warning("Error adding an asset to an album: %s", res['error'])
            else:
                cpt += 1
        if cpt > 0:
            logging.info("%d new assets added to %s", cpt, album)

logging.info("Done!")
