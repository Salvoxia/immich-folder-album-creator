
from typing import Tuple
import requests
import argparse
import logging
import sys
import os
import datetime
from collections import defaultdict, OrderedDict
import re
import urllib3
import random

# Trying to deal with python's isnumeric() function
# not recognizing negative numbers
def is_integer(str):
    try:
        int(str)
        return True
    except ValueError:
        return False

# Translation of GLOB-style patterns to Regex
# Source: https://stackoverflow.com/a/63212852
# FIXME: Replace with glob.translate() introduced with Python 3.13
escaped_glob_tokens_to_re = OrderedDict((
    # Order of ``**/`` and ``/**`` in RE tokenization pattern doesn't matter because ``**/`` will be caught first no matter what, making ``/**`` the only option later on.
    # W/o leading or trailing ``/`` two consecutive asterisks will be treated as literals.
    ('/\\*\\*', '(?:/.+?)*'), # Edge-case #1. Catches recursive globs in the middle of path. Requires edge case #2 handled after this case.
    ('\\*\\*/', '(?:^.+?/)*'), # Edge-case #2. Catches recursive globs at the start of path. Requires edge case #1 handled before this case. ``^`` is used to ensure proper location for ``**/``.
    ('\\*', '[^/]*'), # ``[^/]*`` is used to ensure that ``*`` won't match subdirs, as with naive ``.*?`` solution.
    ('\\?', '.'),
    ('\\[\\*\\]', '\\*'), # Escaped special glob character.
    ('\\[\\?\\]', '\\?'), # Escaped special glob character.
    ('\\[!', '[^'), # Requires ordered dict, so that ``\\[!`` preceded ``\\[`` in RE pattern. Needed mostly to differentiate between ``!`` used within character class ``[]`` and outside of it, to avoid faulty conversion.
    ('\\[', '['),
    ('\\]', ']'),
))

escaped_glob_replacement = re.compile('(%s)' % '|'.join(escaped_glob_tokens_to_re).replace('\\', '\\\\\\'))

def glob_to_re(pattern):
    return escaped_glob_replacement.sub(lambda match: escaped_glob_tokens_to_re[match.group(0)], re.escape(pattern))



# Constants holding script run modes
# Creat albums based on folder names and script arguments
SCRIPT_MODE_CREATE = "CREATE"
# Create album names based on folder names, but delete these albums
SCRIPT_MODE_CLEANUP = "CLEANUP"
# Delete ALL albums
SCRIPT_MODE_DELETE_ALL = "DELETE_ALL"

# Environment variable to check if the script is running inside Docker
ENV_IS_DOCKER = "IS_DOCKER"

# List of allowed share user roles
SHARE_ROLES = ["editor", "viewer"]

# Constants for album thumbnail setting
ALBUM_THUMBNAIL_RANDOM_ALL = "random-all"
ALBUM_THUMBNAIL_RANDOM_FILTERED = "random-filtered"
ALBUM_THUMBNAIL_SETTINGS = ["first", "last", "random", ALBUM_THUMBNAIL_RANDOM_ALL, ALBUM_THUMBNAIL_RANDOM_FILTERED]
ALBUM_THUMBNAIL_STATIC_INDICES = {
    "first": 0,
    "last": -1,
}

parser = argparse.ArgumentParser(description="Create Immich Albums from an external library path based on the top level folders", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("root_path", action='append', help="The external libarary's root path in Immich")
parser.add_argument("api_url", help="The root API URL of immich, e.g. https://immich.mydomain.com/api/")
api_key_group = parser.add_argument_group('API Key')
api_key_group.add_argument("-K", "--api-key", help="The Immich API Key to use. Either --api-key or --api-key-file must be specified. The --api-key parameter takes precedence for ease of manual execution, but it is recommended to use --api-key-file. ")
api_key_group.add_argument("-F", "--api-key-file", help="A path to a file containing the Immich API Key to use. The file must contain only the value.")
parser.add_argument("-r", "--root-path", action="append", help="Additional external libarary root path in Immich; May be specified multiple times for multiple import paths or external libraries.")
parser.add_argument("-u", "--unattended", action="store_true", help="Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob.")
parser.add_argument("-a", "--album-levels", default="1", type=str, help="Number of sub-folders or range of sub-folder levels below the root path used for album name creation. Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be 0. If a range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'. If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>.")
parser.add_argument("-s", "--album-separator", default=" ", type=str, help="Separator string to use for compound album names created from nested folders. Only effective if -a is set to a value > 1")
parser.add_argument("-c", "--chunk-size", default=2000, type=int, help="Maximum number of assets to add to an album with a single API call")
parser.add_argument("-C", "--fetch-chunk-size", default=5000, type=int, help="Maximum number of assets to fetch with a single API call")
parser.add_argument("-l", "--log-level", default="INFO", choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'], help="Log level to use")
parser.add_argument("-k", "--insecure", action="store_true", help="Set to true to ignore SSL verification")
parser.add_argument("-i", "--ignore", action="append", help="Use either literals or glob-like patterns to ignore assets for album name creation. This filter is evaluated after any values passed with --path-filter. May be specified multiple times.")
parser.add_argument("-m", "--mode", default=SCRIPT_MODE_CREATE, choices=[SCRIPT_MODE_CREATE, SCRIPT_MODE_CLEANUP, SCRIPT_MODE_DELETE_ALL], help="Mode for the script to run with. CREATE = Create albums based on folder names and provided arguments; CLEANUP = Create album nmaes based on current images and script arguments, but delete albums if they exist; DELETE_ALL = Delete all albums. If the mode is anything but CREATE, --unattended does not have any effect. Only performs deletion if -d/--delete-confirm option is set, otherwise only performs a dry-run.")
parser.add_argument("-d", "--delete-confirm", action="store_true", help="Confirm deletion of albums when running in mode "+SCRIPT_MODE_CLEANUP+" or "+SCRIPT_MODE_DELETE_ALL+". If this flag is not set, these modes will perform a dry run only. Has no effect in mode "+SCRIPT_MODE_CREATE)
parser.add_argument("-x", "--share-with", action="append", help="A user name (or email address of an existing user) to share newly created albums with. Sharing only happens if the album was actually created, not if new assets were added to an existing album. If the the share role should be specified by user, the format <userName>=<shareRole> must be used, where <shareRole> must be one of 'viewer' or 'editor'. May be specified multiple times to share albums with more than one user.")
parser.add_argument("-o", "--share-role", default="viewer", choices=['viewer', 'editor'], help="The default share role for users newly created albums are shared with. Only effective if --share-with is specified at least once and the share role is not specified within --share-with.")
parser.add_argument("-S", "--sync-mode", default=0, type=int, choices=[0, 1, 2], help="Synchronization mode to use. Synchronization mode helps synchronizing changes in external libraries structures to Immich after albums have already been created. Possible Modes: 0 = do nothing; 1 = Delete any empty albums; 2 = Delete offline assets AND any empty albums")
parser.add_argument("-O", "--album-order", default=False, type=str, choices=[False, 'asc', 'desc'], help="Set sorting order for newly created albums to newest or oldest file first, Immich defaults to newest file first")
parser.add_argument("-A", "--find-assets-in-albums", action="store_true", help="By default, the script only finds assets that are not assigned to any album yet. Set this option to make the script discover assets that are already part of an album and handle them as usual. If --find-archived-assets is set as well, both options apply.")
parser.add_argument("-f", "--path-filter", action="append", help="Use either literals or glob-like patterns to filter assets before album name creation. This filter is evaluated before any values passed with --ignore. May be specified multiple times.")
parser.add_argument("--set-album-thumbnail", choices=ALBUM_THUMBNAIL_SETTINGS, help="Set first/last/random image as thumbnail for newly created albums or albums assets have been added to. If set to "+ALBUM_THUMBNAIL_RANDOM_FILTERED+", thumbnails are shuffled for all albums whose assets would not be filtered out or ignored by the ignore or path-filter options, even if no assets were added during the run. If set to "+ALBUM_THUMBNAIL_RANDOM_ALL+", the thumbnails for ALL albums will be shuffled on every run.")
parser.add_argument("-v", "--archive", action="store_true", help="Set this option to automatically archive all assets that were newly added to albums. If this option is set in combination with --mode = CLEANUP or DELETE_ALL, archived images of deleted albums will be unarchived. Archiving hides the assets from Immich's timeline.")
parser.add_argument("--find-archived-assets", action="store_true", help="By default, the script only finds assets that are not archived in Immich. Set this option to make the script discover assets that are already archived. If -A/--find-assets-in-albums is set as well, both options apply.")


args = vars(parser.parse_args())
# set up logger to log in logfmt format
logging.basicConfig(level=args["log_level"], stream=sys.stdout, format='time=%(asctime)s level=%(levelname)s msg=%(message)s')
logging.Formatter.formatTime = (lambda self, record, datefmt=None: datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).astimezone().isoformat(sep="T",timespec="milliseconds"))

if not (args["api_key"] or args["api_key_file"]):
    parser.error("At least one of --api-key (-K) or --api-key-file (-F) must be provided.")

def readApiKeyFromFile(file_path: str) -> str:
    try:
        with open(file_path, 'r') as secret_file:
            return secret_file.read().strip()
    except FileNotFoundError:
        logging.error("API Key file not found at %s", file_path)
        exit(1)
    except Exception as e:
        logging.error("Error reading API Key file: %s", e)
        exit(1)    


root_paths = args["root_path"]
root_url = args["api_url"]
api_key = args["api_key"] if args["api_key"] else readApiKeyFromFile(args["api_key_file"])
number_of_images_per_request = args["chunk_size"]
number_of_assets_to_fetch_per_request = args["fetch_chunk_size"]
unattended = args["unattended"]
album_levels = args["album_levels"]
# Album Levels Range handling
album_levels_range_arr = ()
album_level_separator = args["album_separator"]
album_order = args["album_order"]
insecure = args["insecure"]
ignore_albums = args["ignore"]
mode = args["mode"]
delete_confirm = args["delete_confirm"]
share_with = args["share_with"]
share_role = args["share_role"]
sync_mode = args["sync_mode"]
find_assets_in_albums = args["find_assets_in_albums"]
path_filter = args["path_filter"]
set_album_thumbnail = args["set_album_thumbnail"]
archive = args["archive"]
find_archived_assets = args["find_archived_assets"]

# Override unattended if we're running in destructive mode
if mode != SCRIPT_MODE_CREATE:
    unattended = False

is_docker = os.environ.get(ENV_IS_DOCKER, False)

logging.debug("root_path = %s", root_paths)
logging.debug("root_url = %s", root_url)
logging.debug("api_key = %s", api_key)
logging.debug("number_of_images_per_request = %d", number_of_images_per_request)
logging.debug("number_of_assets_to_fetch_per_request = %d", number_of_assets_to_fetch_per_request)
logging.debug("unattended = %s", unattended)
logging.debug("album_levels = %s", album_levels)
#logging.debug("album_levels_range = %s", album_levels_range)
logging.debug("album_level_separator = %s", album_level_separator)
logging.debug("album_order = %s", album_order)
logging.debug("insecure = %s", insecure)
logging.debug("ignore = %s", ignore_albums)
logging.debug("mode = %s", mode)
logging.debug("delete_confirm = %s", delete_confirm)
logging.debug("is_docker = %s", is_docker)
logging.debug("share_with = %s", share_with)
logging.debug("share_role = %s", share_role)
logging.debug("sync_mode = %d", sync_mode)
logging.debug("find_assets_in_albums = %s", find_assets_in_albums)
logging.debug("path_filter = %s", path_filter)
logging.debug("set_album_thumbnail = %s", set_album_thumbnail)
logging.debug("archive = %s", archive)
logging.debug("find_archived_assets = %s", find_archived_assets)

# Verify album levels
if is_integer(album_levels) and album_levels == 0:
    parser.print_help()
    exit(1)

# Request arguments for API calls
requests_kwargs = {
    'headers' : {
        'x-api-key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    },
    'verify' : not insecure
}

def expand_to_glob(expr: str) -> str:
    """ 
    Expands the passed expression to a glob-style
    expression if it doesn't contain neither a slash nor an asterisk.
    The resulting glob-style expression matches any path that contains the 
    original expression anywhere.

    Parameters
    ----------
        expr : str
            Expression to expand to a GLOB-style expression if not already
            one
    Returns
    ---------
        The original expression if it contained a slash or an asterisk,
        otherwise \\*\\*/\\*\\<expr\\>\\*/\\*\\*
    """
    if not '/' in expr and not '*' in expr:
        glob_expr = f'**/*{expr}*/**'
        logging.debug("expanding %s to %s", expr, glob_expr)
        return glob_expr
    else:
        return expr

def divide_chunks(l: list, n: int): 
    """Yield successive n-sized chunks from l. """
    # looping till length l 
    for i in range(0, len(l), n):  
        yield l[i:i + n]

def parseSeparatedString(s: str, seprator: str) -> Tuple[str, str]:
    """
    Parse a key, value pair, separated by the provided separator.
    
    That's the reverse of ShellArgs.
    On the command line (argparse) a declaration will typically look like:
        foo=hello
    or
        foo="hello world"
    """
    items = s.split(seprator)
    key = items[0].strip() # we remove blanks around keys, as is logical
    value = None
    if len(items) > 1:
        # rejoin the rest:
        value = seprator.join(items[1:])
    return (key, value)


def parseSeparatedStrings(items: list[str]) -> dict:
    """
    Parse a series of key-value pairs and return a dictionary
    """
    d = {}
    if items:
        for item in items:
            key, value = parseSeparatedString(item, '=')
            d[key] = value
    return d
  
def create_album_name(path_chunks: list[str], album_separator: str) -> str:
    """
    Create album names from provided path_chunks string array.

    The method uses global variables album_levels_range_arr or album_levels to
    generate ablum names either by level range or absolute album levels. If multiple
    album path chunks are used for album names they are separated by album_separator.
    """

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
    return album_separator.join(album_name_chunks)

def fetchServerVersion() -> dict:
    """
    Fetches the API version from the immich server.

    If the API endpoint for getting the server version cannot be reached,
    raises HTTPError
    
    Returns
    -------
        Dictionary with keys 
            - major
            - minor
            - patch
    """
    api_endpoint = f'{root_url}server/version'
    r = requests.get(api_endpoint, **requests_kwargs)
    # The API endpoint changed in Immich v1.118.0, if the new endpoint
    # was not found try the legacy one
    if r.status_code == 404:
        api_endpoint = f'{root_url}server-info/version'
        r = requests.get(api_endpoint, **requests_kwargs)
    
    if r.status_code == 200:
        version = r.json()
        logging.info("Detected Immich server version %s.%s.%s", version['major'], version['minor'], version['patch'])
    # Any other errors mean communication error with API
    else:
        logging.error("Communication with Immich API failed! Make sure the passed API URL is correct!")
        checkApiResponse(r)
    return version


def fetchAssets(isNotInAlbum: bool, findArchived: bool) -> list:
    """
    Fetches assets from the Immich API.

    Uses the /search/meta-data call. Much more efficient than the legacy method
    since this call allows to filter for assets that are not in an album only.
    
    Parameters
    ----------
        isNotInAlbum : bool
            Flag indicating whether to fetch only assets that are not part
            of an album or not. If set to False, will find images in albums and 
            not part of albums
        findArchived : bool
            Flag indicating whether to only fetch assets that are archived. If set to False,
            will find archived and unarchived images
    Returns
    ---------
        An array of asset objects
    """

    assets = fetchAssetsWithOptions({'isNotInAlbum': isNotInAlbum, 'withArchived': findArchived})
    return assets

def fetchAssetsWithOptions(searchOptions: dict) -> list:
    """
    Fetches assets from the Immich API using specific search options.
    The search options directly correspond to the body used for the search API request.
    
    Parameters
    ----------
        searchOptions: dict
            Dictionary containing options to pass to the search/metadata API endpoint
    Returns
    ---------
        An array of asset objects
    """
    body = searchOptions
    assets = []
    # prepare request body

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
        checkApiResponse(r)
        responseJson = r.json()
        assetsReceived = responseJson['assets']['items']
        logging.debug("Received %s assets with chunk %s", len(assetsReceived), page)
        assets = assets + assetsReceived
    return assets


def fetchAlbums():
    """Fetches albums from the Immich API"""

    apiEndpoint = 'albums'

    r = requests.get(root_url+apiEndpoint, **requests_kwargs)
    checkApiResponse(r)
    return r.json()

def fetchAlbumAssets(albumId: str):
    """
    Fetches assets of a specifc album

    Parameters
    ----------
        albumId : str
            The ID of the album for which to fetch the assets

    """

    apiEndpoint = f'albums/{albumId}'

    r = requests.get(root_url+apiEndpoint, **requests_kwargs)
    checkApiResponse(r)
    return r.json()["assets"]

def deleteAlbum(album: dict):
    """
    Deletes an album identified by album['id']
    
    If the album could not be deleted, logs an error.

    Parameters
    ----------
        album : dict
            Dictionary with the following keys:
                - id
                - albumName

    Returns
    ---------
        True if the album was deleted, otherwise False
    """
    apiEndpoint = 'albums'

    logging.debug("Album ID = %s, Album Name = %s", album['id'], album['albumName'])
    r = requests.delete(root_url+apiEndpoint+'/'+album['id'], **requests_kwargs)
    try:
        checkApiResponse(r)
        return True
    except:
        logging.error("Error deleting album %s: %s", album['albumName'], r.reason)
        return False    

def createAlbum(albumName: str, albumOrder: str) -> str:
    """
    Creates an album with the provided name and returns the ID of the created album
    

    Parameters
    ----------
        albumName : str
            Name of the album to create
        albumOrder : str
            False or order [asc|desc]

    Returns
    ---------
        True if the album was deleted, otherwise False
    
    Raises
    ----------
        Exception if the API call failed
    """

    apiEndpoint = 'albums'

    data = {
        'albumName': albumName,
        'description': albumName
    }
    r = requests.post(root_url+apiEndpoint, json=data, **requests_kwargs)
    checkApiResponse(r)

    albumId = r.json()['id']

    if albumOrder:
        data = {
            'order': albumOrder
        }
        r = requests.patch(root_url+apiEndpoint+f'/{albumId}', json=data, **requests_kwargs)
        checkApiResponse(r)
    return albumId


def is_asset_ignored(asset: dict) -> bool:
    """
    Determines if the asset should be ignored for the purpose of this script
    based in its originalPath and global ignore and path_filter options.

    Parameters
    ----------
        asset : dict
            The asset to check if it must be ignored or not. Must have the key 'originalPath'.
    Returns 
    ----------
        True if the asset must be ignored, otherwise False
    """
    is_asset_ignored = False
    asset_root_path = None
    asset_path = asset['originalPath']
    for root_path in root_paths:
        if root_path in asset_path:
            asset_root_path = root_path
            break
    logging.debug("Identified root_path for asset %s = %s", asset_path, asset_root_path)
    if asset_root_path:
        # First apply filter, if any
        if len(path_filter_regex) > 0:
            any_match = False
            for path_filter_regex_entry in path_filter_regex:
                if re.fullmatch(path_filter_regex_entry, asset_path.replace(asset_root_path, '')):
                    any_match = True
            if not any_match:
                logging.debug("Ignoring asset %s due to path_filter setting!", asset_path)
                is_asset_ignored = True
        # If the asset "survived" the path filter, check if it is in the ignore_albums argument
        if not is_asset_ignored and len(ignore_albums_regex) > 0:
            for ignore_albums_regex_entry in ignore_albums_regex:
                if re.fullmatch(ignore_albums_regex_entry, asset_path.replace(asset_root_path, '')):
                    is_asset_ignored = True
                    logging.debug("Ignoring asset %s due to ignore_albums setting!", asset_path)
                    break

    return is_asset_ignored


def addAssetsToAlbum(albumId: str, assets: list[str]) -> list[str]:
    """
    Adds the assets IDs provided in assets to the provided albumId.

    If assets if larger than number_of_images_per_request, the list is chunked
    and one API call is performed per chunk.
    Only logs errors and successes.

    Returns 

    Parameters
    ----------
        albumId : str
            The ID of the album to add assets to
        assets: list[str]
            A list of asset IDs to add to the album

    Returns
    ---------
        The asset UUIDs that were actually added to the album (not respecting assets that were already part of the album)
    """
    apiEndpoint = 'albums'

    # Divide our assets into chunks of number_of_images_per_request,
    # So the API can cope
    assets_chunked = list(divide_chunks(assets, number_of_images_per_request))
    assets_added = list()
    for assets_chunk in assets_chunked:
        data = {'ids':assets_chunk}
        r = requests.put(root_url+apiEndpoint+f'/{albumId}/assets', json=data, **requests_kwargs)
        checkApiResponse(r)
        response = r.json()

        cpt = 0
        for res in response:
            if not res['success']:
                if  res['error'] != 'duplicate':
                    logging.warning("Error adding an asset to an album: %s", res['error'])
            else:
                cpt += 1
                assets_added.append(res['id'])
        if cpt > 0:
            logging.info("%d new assets added to %s", cpt, album)

    return assets_added

def fetchUsers():
    """Queries and returns all users"""

    apiEndpoint = 'users'

    r = requests.get(root_url+apiEndpoint, **requests_kwargs)
    checkApiResponse(r)
    return r.json()

def shareAlbumWithUserAndRole(album_id: str, share_user_ids: list[str], share_role: str):
    """
    Shares the album with the provided album_id with all provided share_user_ids
    using share_role as a role.

    Parameters
    ----------
        album_id : str
            The ID of the album to share
        share_user_ids: list[str]
            IDs of users to share the album with
        share_role: str
            The share role to use when sharing the album, valid values are
            "viewer" or "editor"
    Raises
    ----------
        Exception if share_role contains an invalid value  
        Exception if the API call fails
    """ 

    apiEndpoint = 'albums/'+album_id+'/users'

    assert share_role in SHARE_ROLES

    # build payload
    album_users = []
    for share_user_id in share_user_ids:
        share_info = dict()
        share_info['role'] = share_role
        share_info['userId'] = share_user_id
        album_users.append(share_info)
    
    data = {
        'albumUsers': album_users
    }
    r = requests.put(root_url+apiEndpoint, json=data, **requests_kwargs)
    checkApiResponse(r)

def triggerOfflineAssetRemoval():
    """
    Removes offline assets.

    Takes into account API changes happening between v1.115.0 and v1.116.0.

    Before v1.116.0, offline asset removal was an asynchronuous job that could only be
    triggered by an Administrator for a specific library.

    Since v1.116.0, offline assets are no longer displayed in the main timeline but shown in the trash. They automatically
    come back from the trash when they are no longer offline. The only way to delete them is either by emptying the trash
    (along with everything else) or by selectively deleting all offline assets. This is option the script now uses.

    Raises
    ----------
        HTTPException if any API call fails
    """
    if version['major'] == 1 and version ['minor'] < 116:
        triggerOfflineAssetRemovalPreMinorVersion116()
    else:
        triggerOfflineAssetRemovalSinceMinorVersion116()

def triggerOfflineAssetRemovalSinceMinorVersion116():
    """
    Synchronuously deletes offline assets.

    Uses the searchMetadata endpoint to find all assets marked as offline, then
    issues a delete call for these asset UUIDs.

    Raises
    ----------
        HTTPException if any API call fails
    """
    # Workaround for a bug where isOffline option is not respected:
    # Search all trashed assets and manually filter for offline assets.
    # WARNING! This workaround must NOT be removed to keep compatibility with Immich v1.116.x to at
    # least v1.117.x (reported issue for v1.117.0, might be fixed with v1.118.0)!
    # If removed the assets for users of v1.116.0 - v1.117.x might be deleted completely!!!
    trashed_assets = fetchAssetsWithOptions({'trashedAfter': '1970-01-01T00:00:00.000Z'})
    #logging.debug("search results: %s", offline_assets)
    
    offline_assets = [asset for asset in trashed_assets if asset['isOffline']]

    
    if len(offline_assets) > 0:
        logging.debug("Deleting the following offline assets (count: %d): %s", len(offline_assets), [asset['originalPath'] for asset in offline_assets])
        deleteAssets(offline_assets, True)
    else:
        logging.info("No offline assets found!")


def deleteAssets(assets_to_delete: list, force: bool):
    """
    Deletes the provided assets from Immich.

    Parameters
    ----------
        assets_to_delete : list
            A list of asset objects with key 'id'.
        force: bool
            Force flag to pass to the API call

    Raises
    ----------
        HTTPException if the API call fails
    """

    apiEndpoint = 'assets'
    assetIdsToDelete = [asset['id'] for asset in assets_to_delete]
    data = {
        'force': force,
        'ids': assetIdsToDelete
    }

    r = requests.delete(root_url+apiEndpoint, json=data, **requests_kwargs)
    checkApiResponse(r)



def triggerOfflineAssetRemovalPreMinorVersion116():
    """
    Triggers Offline Asset Removal Job.
    Only supported in Immich prior v1.116.0.
    Requires the script to run with an Administrator level API key.
    
    Works by fetching all libraries and triggering the Offline Asset Removal job
    one by one.
    
    Raises
    ----------
        HTTPException if the API call fails
    """
    libraries = fetchLibraries()
    for library in libraries:
        triggerOfflineAssetRemovalAsync(library['id'])

def fetchLibraries() -> list[dict]:
    """
    Queries and returns all libraries
    
    Raises
    ----------
        Exception if any API call fails
    """

    apiEndpoint = 'libraries'

    r = requests.get(root_url+apiEndpoint, **requests_kwargs)
    checkApiResponse(r)
    return r.json()

def triggerOfflineAssetRemovalAsync(libraryId: str):
    """
    Triggers removal of offline assets in the library identified by libraryId.

    Parameters
    ----------
        libraryId : str
            The ID of the library to trigger offline asset removal for
    Raises
    ----------
        Exception if any API call fails
    """

    apiEndpoint = f'libraries/{libraryId}/removeOffline'

    r = requests.post(root_url+apiEndpoint, **requests_kwargs)
    if r.status_code == 403:
        logging.fatal("--sync-mode 2 requires an Admin User API key!")
    else:
        checkApiResponse(r)

def setAlbumThumbnail(albumId: str, assetId: str):
    """
    Sets asset as thumbnail of album

    Parameters
    ----------
        albumId : str
            The ID of the album for which to set the thumbnail
        assetId : str
            The ID of the asset to be set as thumbnail
            
    Raises
    ----------
        Exception if the API call fails
    """
    apiEndpoint = f'albums/{albumId}'

    data = {"albumThumbnailAssetId": assetId}

    r = requests.patch(root_url+apiEndpoint, json=data, **requests_kwargs)
    checkApiResponse(r)

def setAssetsArchived(assetIds: list[str], isArchived: bool):
    """
    (Un-)Archives the assets identified by the passed list of UUIDs.

    Parameters
    ----------
        assetIds : list
            A list of asset IDs to archive
        isArchived : bool
            Flag indicating whether to archive or unarchive the passed assets
   
    Raises
    ----------
        Exception if the API call fails
    """
    apiEndpoint = f'assets'

    data = {
        "ids": assetIds,
        "isArchived": isArchived
    }

    r = requests.put(root_url+apiEndpoint, json=data, **requests_kwargs)
    checkApiResponse(r)

def checkApiResponse(response: requests.Response):
    """
    Checks the HTTP return code for the privided response and
    logs any errors before raising an HTTPException

    Parameters
    ----------
        respsone : requests.Response
            A list of asset IDs to archive
        isArchived : bool
            Flag indicating whether to archive or unarchive the passed assets
   
    Raises
    ----------
        HTTPException if the API call fails
    """
    try:
        response.raise_for_status()
    except:
        if response.json():
            logging.error("Error in API call: %s", response.json())
        else:
            logging.error("API respsonse did not contain a payload")
    response.raise_for_status()


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

# Create ignore regular expressions
ignore_albums_regex = []
if ignore_albums:
    for ignore_albums_entry in ignore_albums:
        ignore_albums_regex.append(glob_to_re(expand_to_glob(ignore_albums_entry)))

# Create path filter regular expressions
path_filter_regex = []
if path_filter:
    for path_filter_entry in path_filter:
        path_filter_regex.append(glob_to_re(expand_to_glob(path_filter_entry)))

# append trailing slash to all root paths
for i in range(len(root_paths)):
    if root_paths[i][-1] != '/':
        root_paths[i] = root_paths[i] + '/'
# append trailing slash to root URL
if root_url[-1] != '/':
    root_url = root_url + '/'

version = fetchServerVersion()
# Check version
if version['major'] == 1 and version ['minor'] < 106:
    logging.fatal("This script only works with Immich Server v1.106.0 and newer! Update Immich Server or use script version 0.8.1!")
    exit(1)


# Special case: Run Mode DELETE_ALL albums
if mode == SCRIPT_MODE_DELETE_ALL:
    albums = fetchAlbums()
    logging.info("%d existing albums identified", len(albums))
    # Delete Confirm check
    if not delete_confirm:
        album_names = []
        for album in albums:
            album_names.append(album['albumName'])
        print("Would delete the following albums (ALL albums!):")
        print(album_names)
        if is_docker:
            print("Run the container with environment variable DELETE_CONFIRM set to 1 to actually delete these albums!")
        else:
            print("Call with --delete-confirm to actually delete albums!")
        exit(0)
    cpt = 0
    for album in albums:
        if deleteAlbum(album):
             # If the archived flag is set it means we need to unarchived all images of deleted albums;
            # In order to do so, we need to fetch all assets of the album we're going to delete
            assets_in_album = []
            if archive:
                assets_in_album = fetchAlbumAssets(album['id'])
            logging.info("Deleted album %s", album['albumName'])
            cpt += 1
            if len(assets_in_album) > 0 and archive:
                setAssetsArchived([asset['id'] for asset in assets_in_album], False)
                logging.info("Unarchived %d assets", len(assets_in_album))
    logging.info("Deleted %d/%d albums", cpt, len(albums))
    exit(0)

logging.info("Requesting all assets")
# only request images that are not in any album if we are running in CREATE mode,
# otherwise we need all images, even if they are part of an album
if mode == SCRIPT_MODE_CREATE:
    assets = fetchAssets(not find_assets_in_albums, find_archived_assets)
else:
    assets = fetchAssets(False, True)
logging.info("%d photos found", len(assets))



logging.info("Sorting assets to corresponding albums using folder name")
album_to_assets = defaultdict(list)
for asset in assets:
    asset_path = asset['originalPath']
    # This method will log the ignore reason, so no need to log anyhting again.
    if is_asset_ignored(asset):
        continue
   
    for root_path in root_paths:
        if root_path not in asset_path:
            continue

        # Chunks of the asset's path below root_path
        path_chunks = asset_path.replace(root_path, '').split('/') 
        # A single chunk means it's just the image file in no sub folder, ignore
        if len(path_chunks) == 1:
            continue
        
        # remove last item from path chunks, which is the file name
        del path_chunks[-1]
        album_name = create_album_name(path_chunks, album_level_separator)
        if len(album_name) > 0:
            album_to_assets[album_name].append(asset['id'])
        else:
            logging.warning("Got empty album name for asset path %s, check your album_level settings!", asset_path)

album_to_assets = {k:v for k, v in sorted(album_to_assets.items(), key=(lambda item: item[0]))}

logging.info("%d albums identified", len(album_to_assets))
logging.info("Album list: %s", list(album_to_assets.keys()))

if not unattended and mode == SCRIPT_MODE_CREATE:
    if is_docker:
        print("Check that this is the list of albums you want to create. Run the container with environment variable UNATTENDED set to 1 to actually create these albums.")
        exit(0)
    else:
        print("Press enter to create these albums, Ctrl+C to abort")
        input()

album_to_id = {}

logging.info("Listing existing albums on immich")

albums = fetchAlbums()
album_to_id = {album['albumName']:album['id'] for album in albums }
logging.info("%d existing albums identified", len(albums))

# mode CLEANUP
if mode == SCRIPT_MODE_CLEANUP:  
    albums_to_delete = list()
    for album in album_to_assets:
        if album in album_to_id:
            album_to_delete = dict()
            album_to_delete['id'] = album_to_id[album]
            album_to_delete['albumName'] = album
            albums_to_delete.append(album_to_delete)
    
    # Delete Confirm check
    if not delete_confirm:
        print("Would delete the following albums:")
        print([a['albumName'] for a in albums_to_delete])
        if is_docker:
            print("Run the container with environment variable DELETE_CONFIRM set to 1 to actually delete these albums!")
        else:
            print(" Call with --delete-confirm to actually delete albums!")
        exit(0)
    else:
        cpt = 0
        for album_to_delete in albums_to_delete:
            # If the archived flag is set it means we need to unarchived all images of deleted albums;
            # In order to do so, we need to fetch all assets of the album we're going to delete
            assets_in_album = []
            if archive:
                assets_in_album = fetchAlbumAssets(album_to_delete['id'])
            if deleteAlbum(album_to_delete):
                logging.info("Deleted album %s", album_to_delete['albumName'])
                cpt += 1
                if len(assets_in_album) > 0 and archive:
                    setAssetsArchived([asset['id'] for asset in assets_in_album], False)
                    logging.info("Unarchived %d assets", len(assets_in_album))
        logging.info("Deleted %d/%d albums", cpt, len(album_to_assets))
        exit(0)


# mode CREATE
logging.info("Creating albums if needed")
created_albums = dict()
for album in album_to_assets:
    if album in album_to_id:
        continue
    album_id = createAlbum(album, album_order)
    album_to_id[album] = album_id
    created_albums[album] = album_id
    logging.info('Album %s added!', album)
logging.info("%d albums created", len(created_albums))

# Share newly created albums with users
if share_with is not None and len(created_albums) > 0:
    logging.info("Sharing created albums with users")
    share_user_roles = parseSeparatedStrings(share_with)
    logging.debug("Share User Roles: %s", share_user_roles)
    # Get all users
    users = fetchUsers()
    logging.debug("Found users: %s", users)
    
    # Initialize dicitionary of share roles to user IDs to share with
    roles_for_share_user_ids = dict()
    for allowed_role in SHARE_ROLES:
        roles_for_share_user_ids[allowed_role] = list()
    
    # Search user IDs of users to share with
    for share_user in share_user_roles.keys():
        role = share_user_roles[share_user]
        # search user ID by name or email
        found_user = False
        if role == None:
            role = share_role
            logging.debug("No explicit share role passed for share user %s, using default role %s", share_user, share_role)
        elif role not in SHARE_ROLES:
            role = share_role
            logging.warning("Passed share role %s for user %s is not allowed, defaulting to %s", role, share_user, share_role)
        else:
            logging.debug("Explicit share role %s passed for share user %s", role, share_user)
        
        for user in users:
            # Search by name or mail address
            if user['name'] == share_user or user['email'] == share_user:
                share_user_id = user['id']
                logging.debug("User %s has ID %s", share_user, share_user_id)
                roles_for_share_user_ids[role].append(share_user_id)
                found_user = True
                break
        if not found_user:
            logging.warning("User %s to share albums with does not exist!", share_user)
            
    
    shared_album_cnt = 0
    # Only try sharing if we found at least one user ID to share with
    for share_album in created_albums.keys():
        album_shared_successfully = False
        for role in roles_for_share_user_ids.keys():
            share_user_ids = roles_for_share_user_ids[role]
            if len(share_user_ids) > 0:   
                try:
                    shareAlbumWithUserAndRole(created_albums[share_album], share_user_ids, role)
                    logging.debug("Album %s shared with users IDs %s in role: %s)", share_album, share_user_ids, role)
                    album_shared_successfully = True
                except:
                    logging.warning("Error sharing album %s for users %s in role %s", share_album, share_user_ids, role)
                    album_shared_successfully = False
        if album_shared_successfully:
            shared_album_cnt += 1
    logging.info("Successfully shared %d/%d albums", shared_album_cnt, len(created_albums))


logging.info("Adding assets to albums")
# Note: Immich manages duplicates without problem, 
# so we can each time ad all assets to same album, no photo will be duplicated 
albums_with_assets_added = list()
asset_uuids_added = list()
for album, assets in album_to_assets.items():
    id = album_to_id[album]
    assets_added = addAssetsToAlbum(id, assets)
    if len(assets_added) > 0:
        album_with_asset_added = dict()
        album_with_asset_added['id'] = id
        album_with_asset_added['albumName'] = album
        albums_with_assets_added.append(album_with_asset_added)
        asset_uuids_added += assets_added

# Archive assets
if archive and len(asset_uuids_added) > 0:
    setAssetsArchived(asset_uuids_added, True)
    logging.info("Archived %d assets", len(asset_uuids_added))


if set_album_thumbnail:
    logging.info("Updating album thumbnails")
    if set_album_thumbnail in [ALBUM_THUMBNAIL_RANDOM_ALL, ALBUM_THUMBNAIL_RANDOM_FILTERED]:
        # fetch albums again to get newest state
        albums = fetchAlbums()
    else:
        albums = albums_with_assets_added

    for album in albums:
        # get assets for album and sort them by file creation date
        assets = fetchAlbumAssets(album['id'])
        # apply filtering to assets
        if set_album_thumbnail == ALBUM_THUMBNAIL_RANDOM_FILTERED:
            assets[:] = [asset for asset in assets if not is_asset_ignored(asset)]        

        if(len(assets) > 0):
            assets.sort(key=lambda x: x['fileCreatedAt'])

            if set_album_thumbnail not in ALBUM_THUMBNAIL_STATIC_INDICES.keys():
                index = random.randint(0, len(assets)-1)
            else:
                index = ALBUM_THUMBNAIL_STATIC_INDICES[set_album_thumbnail]

            logging.info("Using asset with index %d as thumbnail for album %s", index, album['albumName'])
            setAlbumThumbnail(album['id'], assets[index]['id'])
        
# Perform sync mode action: Trigger offline asset removal
if sync_mode == 2:
    logging.info("Trigger offline asset removal")
    triggerOfflineAssetRemoval()

# Perform sync mode action: Delete empty albums
#
# For Immich versions prior to v1.116.0:
# Attention: Since Offline Asset Removal is an asynchronous job,
# albums affected by it are most likely not empty yet! So this 
# might only be effective in the next script run.
if sync_mode >= 1:
    logging.info("Deleting all empty albums")
    albums = fetchAlbums()
    emptyAlbumCount = 0
    deletedAlbumCount = 0
    for album in albums:
        if album['assetCount'] == 0:
            emptyAlbumCount += 1
            logging.info("Deleting empty album %s", album['albumName'])
            if deleteAlbum(album):
                deletedAlbumCount += 1
    if emptyAlbumCount > 0:
        logging.info("Successfully deleted %d/%d empty albums!", deletedAlbumCount, emptyAlbumCount)
    else:
        logging.info("No empty albums found!")

logging.info("Done!")
