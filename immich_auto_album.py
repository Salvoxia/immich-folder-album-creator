import requests
import argparse
import logging
import sys
import datetime
from collections import defaultdict
import urllib3

# Trying to deal with python's isnumeric() function
# not recognizing negative numbers
def is_integer(str):
    try:
        int(str)
        return True
    except ValueError:
        return False

parser = argparse.ArgumentParser(description="Create Immich Albums from an external library path based on the top level folders", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("root_path", action='append', help="The external libarary's root path in Immich")
parser.add_argument("api_url", help="The root API URL of immich, e.g. https://immich.mydomain.com/api/")
parser.add_argument("api_key", help="The Immich API Key to use")
parser.add_argument("-r", "--root-path", action="append", help="Additional external libarary root path in Immich; May be specified multiple times for multiple import paths or external libraries.")
parser.add_argument("-u", "--unattended", action="store_true", help="Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob.")
parser.add_argument("-a", "--album-levels", default="1", type=str, help="Number of sub-folders or range of sub-folder levels below the root path used for album name creation. Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be 0. If a range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'. If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>.")
parser.add_argument("-s", "--album-separator", default=" ", type=str, help="Separator string to use for compound album names created from nested folders. Only effective if -a is set to a value > 1")
parser.add_argument("-c", "--chunk-size", default=2000, type=int, help="Maximum number of assets to add to an album with a single API call")
parser.add_argument("-C", "--fetch-chunk-size", default=5000, type=int, help="Maximum number of assets to fetch with a single API call")
parser.add_argument("-l", "--log-level", default="INFO", choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'], help="Log level to use")
parser.add_argument("-k", "--insecure", action="store_true", help="Set to true to ignore SSL verification")
parser.add_argument("-i", "--ignore", default="", type=str, help="A string containing a list of folders, sub-folder sequences or file names separated by ':' that will be ignored.")
args = vars(parser.parse_args())
# set up logger to log in logfmt format
logging.basicConfig(level=args["log_level"], stream=sys.stdout, format='time=%(asctime)s level=%(levelname)s msg=%(message)s')
logging.Formatter.formatTime = (lambda self, record, datefmt=None: datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).astimezone().isoformat(sep="T",timespec="milliseconds"))

root_paths = args["root_path"]
root_url = args["api_url"]
api_key = args["api_key"]
number_of_images_per_request = args["chunk_size"]
number_of_assets_to_fetch_per_request = args["fetch_chunk_size"]
unattended = args["unattended"]
album_levels = args["album_levels"]
# Album Levels Range handling
album_levels_range_arr = ()
album_level_separator = args["album_separator"]
insecure = args["insecure"]
ignore_albums = args["ignore"]
logging.debug("root_path = %s", root_paths)
logging.debug("root_url = %s", root_url)
logging.debug("api_key = %s", api_key)
logging.debug("number_of_images_per_request = %d", number_of_images_per_request)
logging.debug("number_of_assets_to_fetch_per_request = %d", number_of_assets_to_fetch_per_request)
logging.debug("unattended = %s", unattended)
logging.debug("album_levels = %s", album_levels)
#logging.debug("album_levels_range = %s", album_levels_range)
logging.debug("album_level_separator = %s", album_level_separator)
logging.debug("insecure = %s", insecure)
logging.debug("ignore = %s", ignore_albums)

# Verify album levels
if is_integer(album_levels) and album_levels == 0:
    parser.print_help()
    exit(1)

if insecure:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Verify album levels range
if not is_integer(album_levels):
    album_levels_range_split = album_levels.split(",")
    if (len(album_levels_range_split) != 2 
            or not is_integer(album_levels_range_split[0]) 
            or not is_integer(album_levels_range_split[1]) 
            or int(album_levels_range_split[0]) == 0
            or int(album_levels_range_split[1]) == 0
            or (int(album_levels_range_split[0]) >= 0 and int(album_levels_range_split[1]) < 0) 
            or (int(album_levels_range_split[0]) < 0 and int(album_levels_range_split[1]) >= 0)
            or (int(album_levels_range_split[0]) < 0 and int(album_levels_range_split[1]) < 0) and int(album_levels_range_split[0]) > int(album_levels_range_split[1])):
        logging.error("Invalid album_levels range format! If a range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'. If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>.")
        exit(1)
    album_levels_range_arr = album_levels_range_split
    # Convert to int
    album_levels_range_arr[0] = int(album_levels_range_split[0])
    album_levels_range_arr[1] = int(album_levels_range_split[1])
    # Special case: both levels are negative and end level is -1, which is equivalent to just negative album level of start level
    if(album_levels_range_arr[0] < 0 and album_levels_range_arr[1] == -1):
        album_levels = album_levels_range_arr[0]
        album_levels_range_arr = ()
        logging.debug("album_levels is a range with negative start level and end level of -1, converted to album_levels = %d", album_levels)
    else:
        logging.debug("valid album_levels range argument supplied")
        logging.debug("album_levels_start_level = %d", album_levels_range_arr[0])
        logging.debug("album_levels_end_level = %d", album_levels_range_arr[1])
        # Deduct 1 from album start levels, since album levels start at 1 for user convenience, but arrays start at index 0
        if album_levels_range_arr[0] > 0:
            album_levels_range_arr[0] -= 1
            album_levels_range_arr[1] -= 1

if not ignore_albums == "":
    ignore_albums = ignore_albums.split(":")
else:
    ignore_albums = False

# Request arguments for API calls
requests_kwargs = {
    'headers' : {
        'x-api-key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    },
    'verify' : not insecure
}

# Yield successive n-sized 
# chunks from l. 
def divide_chunks(l, n): 
      
    # looping till length l 
    for i in range(0, len(l), n):  
        yield l[i:i + n] 
  
# Create album names from provided path_chunks string array
# based on supplied album_levels argument (either by level range or absolute album levels)
def create_album_name(path_chunks):
    album_name_chunks = ()
    logging.debug("path chunks = %s", list(path_chunks))
    # Check which path to take: album_levels_range or album_levels
    if len(album_levels_range_arr) == 2:
        if album_levels_range_arr[0] < 0:
            album_levels_start_level_capped = min(len(path_chunks), abs(album_levels_range_arr[0]))
            album_levels_end_level_capped =  album_levels_range_arr[1]+1
            album_levels_start_level_capped *= -1
        else:
            album_levels_start_level_capped = min(len(path_chunks)-1, album_levels_range_arr[0])
            # Add 1 to album_levels_end_level_capped to include the end index, which is what the user intended to. It's not a problem
            # if the end index is out of bounds.
            album_levels_end_level_capped =  min(len(path_chunks)-1, album_levels_range_arr[1]) + 1
        logging.debug("album_levels_start_level_capped = %d", album_levels_start_level_capped)
        logging.debug("album_levels_end_level_capped = %d", album_levels_end_level_capped)
        # album start level is not equal to album end level, so we want a range of levels
        if album_levels_start_level_capped is not album_levels_end_level_capped:
            
            # if the end index is out of bounds.
            if album_levels_end_level_capped < 0 and abs(album_levels_end_level_capped) >= len(path_chunks):
                album_name_chunks = path_chunks[album_levels_start_level_capped:]
            else:
                album_name_chunks = path_chunks[album_levels_start_level_capped:album_levels_end_level_capped]
        # album start and end levels are equal, we want exactly that level
        else:
            # create on-the-fly array with a single element taken from 
            album_name_chunks = [path_chunks[album_levels_start_level_capped]]
    else:
        album_levels_int = int(album_levels)
        # either use as many path chunks as we have,
        # or the specified album levels
        album_name_chunk_size = min(len(path_chunks), abs(album_levels_int))
        if album_levels_int < 0:
            album_name_chunk_size *= -1

        # Copy album name chunks from the path to use as album name
        album_name_chunks = path_chunks[:album_name_chunk_size]
        if album_name_chunk_size < 0:
            album_name_chunks = path_chunks[album_name_chunk_size:]
    logging.debug("album_name_chunks = %s", album_name_chunks)
    return album_level_separator.join(album_name_chunks)

# Fetches assets from the Immich API
# Takes different API versions into account for compatibility
def fetchServerVersion():
    # This API call was only introduced with version 1.106.1, so it will fail
    # for older versions.
    # Initialize the version with the latest version without this API call
    version = {'major': 1, 'minor': 105, "patch": 1}
    r = requests.get(root_url+'server-info/version', **requests_kwargs)
    assert r.status_code == 200 or r.status_code == 404
    if r.status_code == 200:
        version = r.json()
        logging.info("Detected Immich server version %s.%s.%s", version['major'], version['minor'], version['patch'])
    else:
        logging.info("Detected Immich server version %s.%s.%s or older", version['major'], version['minor'], version['patch'])
    return version

# Fetches assets from the Immich API
# Takes different API versions into account for compatibility
def fetchAssets():
    if version['major'] == 1 and version['minor'] <= 105:
        return fetchAssetsLegacy()
    else:
        return fetchAssetsMinorV106()


# Fetches assets from the Immich API
# Uses the legacy GET /asset call which only exists up to v1.105.x
def fetchAssetsLegacy():
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
    return assets

# Fetches assets from the Immich API
# Uses the /search/meta-data call. Much more efficient than the legacy method
# since this call allows to filter for assets that are not in an album only.
def fetchAssetsMinorV106():
    assets = []
    # prepare request body
    body = {}
    body['isNotInAlbum'] = 'true'
    # This API call allows a maximum page size of 1000
    number_of_assets_to_fetch_per_request_search = min(1000, number_of_assets_to_fetch_per_request)
    body['size'] = number_of_assets_to_fetch_per_request_search
    # Initial API call, let's fetch our first chunk
    page = 1
    body['page'] = str(page)
    r = requests.post(root_url+'search/metadata', json=body, **requests_kwargs)
    r.raise_for_status()
    responseJson = r.json()
    assetsReceived = responseJson['assets']['items']
    logging.debug("Received %s assets with chunk %s", len(assetsReceived), page)

    assets = assets + assetsReceived
    # If we got a full chunk size back, let's perfrom subsequent calls until we get less than a full chunk size
    while len(assetsReceived) == number_of_assets_to_fetch_per_request_search:
        page += 1
        body['page'] = page
        r = requests.post(root_url+'search/metadata', json=body, **requests_kwargs)
        assert r.status_code == 200
        responseJson = r.json()
        assetsReceived = responseJson['assets']['items']
        logging.debug("Received %s assets with chunk %s", len(assetsReceived), page)
        assets = assets + assetsReceived
    return assets


# Fetches assets from the Immich API
# Takes different API versions into account for compatibility
def fetchAlbums():
    apiEndpoint = 'albums'
    if version['major'] == 1 and version['minor'] <= 105:
        apiEndpoint = 'album'

    r = requests.get(root_url+apiEndpoint, **requests_kwargs)
    r.raise_for_status()
    return r.json()

# Creates an album with the provided name and returns the ID of the
# created album
def createAlbum(albumName):
    apiEndpoint = 'albums'
    if version['major'] == 1 and version['minor'] <= 105:
        apiEndpoint = 'album'
    data = {
        'albumName': albumName,
        'description': albumName
    }
    r = requests.post(root_url+apiEndpoint, json=data, **requests_kwargs)
    assert r.status_code in [200, 201]
    return r.json()['id']

# Adds the provided assetIds to the provided albumId
def addAssetsToAlbum(albumId, assets):
    apiEndpoint = 'albums'
    if version['major'] == 1 and version['minor'] <= 105:
        apiEndpoint = 'album'
    # Divide our assets into chunks of number_of_images_per_request,
    # So the API can cope
    assets_chunked = list(divide_chunks(assets, number_of_images_per_request))
    for assets_chunk in assets_chunked:
        data = {'ids':assets_chunk}
        r = requests.put(root_url+apiEndpoint+f'/{albumId}/assets', json=data, **requests_kwargs)
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

# append trailing slash to all root paths
for i in range(len(root_paths)):
    if root_paths[i][-1] != '/':
        root_paths[i] = root_paths[i] + '/'
# append trailing slash to root URL
if root_url[-1] != '/':
    root_url = root_url + '/'

version = fetchServerVersion()

logging.info("Requesting all assets")
assets = fetchAssets()
logging.info("%d photos found", len(assets))



logging.info("Sorting assets to corresponding albums using folder name")
album_to_assets = defaultdict(list)
for asset in assets:
    asset_path = asset['originalPath']
    for root_path in root_paths:
        if root_path not in asset_path:
            continue
        # Check ignore_albums
        ignore = False
        if ignore_albums:
            for ignore_entry in ignore_albums:
                if ignore_entry in asset_path:
                    ignore = True
                    break
            if ignore:
                logging.debug("Ignoring asset %s due to ignore_albums setting!", asset_path)
                continue
            
        # Chunks of the asset's path below root_path
        path_chunks = asset_path.replace(root_path, '').split('/') 
        # A single chunk means it's just the image file in no sub folder, ignore
        if len(path_chunks) == 1:
            continue
        
        # remove last item from path chunks, which is the file name
        del path_chunks[-1]
        album_name = create_album_name(path_chunks)
        if len(album_name) > 0:
            album_to_assets[album_name].append(asset['id'])
        else:
            logging.warning("Got empty album name for asset path %s, check your album_level settings!", asset_path)

album_to_assets = {k:v for k, v in sorted(album_to_assets.items(), key=(lambda item: item[0]))}

logging.info("%d albums identified", len(album_to_assets))
logging.info("Album list: %s", list(album_to_assets.keys()))
if not unattended:
    print("Press Enter to continue, Ctrl+C to abort")
    input()


album_to_id = {}

logging.info("Listing existing albums on immich")

albums = fetchAlbums()
album_to_id = {album['albumName']:album['id'] for album in albums }
logging.info("%d existing albums identified", len(albums))


logging.info("Creating albums if needed")
cpt = 0
for album in album_to_assets:
    if album in album_to_id:
        continue
    album_to_id[album] = createAlbum(album)
    logging.info('Album %s added!', album)
    cpt += 1
logging.info("%d albums created", cpt)


logging.info("Adding assets to albums")
# Note: Immich manages duplicates without problem, 
# so we can each time ad all assets to same album, no photo will be duplicated 
for album, assets in album_to_assets.items():
    id = album_to_id[album]
    addAssetsToAlbum(id, assets)

logging.info("Done!")
