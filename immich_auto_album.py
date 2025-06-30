"""Python script for creating albums in Immich from folder names in an external library."""

from typing import Tuple
import argparse
import logging
import sys
import fnmatch
import os
import datetime
from collections import OrderedDict
import random
from urllib.error import HTTPError

import regex
import yaml

import urllib3
import requests

# Script Constants

# Constants holding script run modes
# Create albums based on folder names and script arguments
SCRIPT_MODE_CREATE = "CREATE"
# Create album names based on folder names, but delete these albums
SCRIPT_MODE_CLEANUP = "CLEANUP"
# Delete ALL albums
SCRIPT_MODE_DELETE_ALL = "DELETE_ALL"

# Environment variable to check if the script is running inside Docker
ENV_IS_DOCKER = "IS_DOCKER"

# List of allowed share user roles
SHARE_ROLES = ["editor", "viewer"]

# Immich API request timeout
REQUEST_TIMEOUT_DEFAULT = 20

# Constants for album thumbnail setting
ALBUM_THUMBNAIL_RANDOM_ALL = "random-all"
ALBUM_THUMBNAIL_RANDOM_FILTERED = "random-filtered"
ALBUM_THUMBNAIL_SETTINGS = ["first", "last", "random"]
ALBUM_THUMBNAIL_SETTINGS_GLOBAL = ALBUM_THUMBNAIL_SETTINGS + [ALBUM_THUMBNAIL_RANDOM_ALL, ALBUM_THUMBNAIL_RANDOM_FILTERED]
ALBUM_THUMBNAIL_STATIC_INDICES = {
    "first": 0,
    "last": -1,
}

# File name to use for album properties files
ALBUMPROPS_FILE_NAME = '.albumprops'

class AlbumMergeException(Exception):
    """Error thrown when trying to override an existing property"""

# Disable pylint rule for too many instance attributes
# pylint: disable=R0902
class AlbumModel:
    """Model of an album with all properties necessary for handling albums in the scope of this script"""
    # Album Merge Mode indicating only properties should be merged that are
    # not already set in the merge target
    ALBUM_MERGE_MODE_EXCLUSIVE = 1
    # Same as ALBUM_MERGE_MODE_EXCLUSIVE, but also raises an error
    # if attempting to overwrite an existing property when merging
    ALBUM_MERGE_MODE_EXCLUSIVE_EX = 2
    # Override any property in the merge target if already exists
    ALBUM_MERGE_MODE_OVERRIDE = 3
    # List of class attribute names that are relevant for album properties handling
    # This list is used for album model merging and validation
    ALBUM_PROPERTIES_VARIABLES = ['override_name', 'description', 'share_with', 'thumbnail_setting', 'sort_order', 'archive', 'visibility', 'comments_and_likes_enabled']

    def __init__(self, name: str):
        # The album ID, set after it was created
        self.id = None
        # The album name
        self.name = name
        # The override album name, takes precedence over name for album creation
        self.override_name = None
        # The description to set for the album
        self.description = None
        # A list of dicts with Immich assets
        self.assets = []
        # a list of dicts with keys user and role, listing all users and their role to share the album with
        self.share_with = []
        # Either a fully qualified asset path or one of 'first', 'last', 'random'
        self.thumbnail_setting = None
        # Sorting order for this album, 'asc' or 'desc'
        self.sort_order = None
        # Boolean indicating whether assets in this album should be archived after adding
        # Deprecated, use visibility = archive instead!
        self.archive = None
        # String indicating asset visibility, allowed values: archive, hidden, locked, timeline
        self.visibility = None
        # Boolean indicating whether assets in this albums can be commented on and liked
        self.comments_and_likes_enabled = None
        # A set of unique paths in this album
        self.album_paths = set()

    def add_asset(self, asset: dict):
        """
        Adds an asset to the album and updates the album_paths with the asset's directory.

        Parameters
        ----------
        asset : dict
            The asset to add, must contain the key 'originalPath'.
        """
        self.assets.append(asset)
        asset_path = os.path.dirname(asset['originalPath'])
        self.album_paths.add(asset_path)

    def get_album_properties_dict(self) -> dict:
        """
        Returns this class' attributes relevant for album properties handling
        as a dictionary

        Returns
        ---------
            A dictionary of all album properties
        """
        props = dict(vars(self))
        for prop in list(props.keys()):
            if prop not in AlbumModel.ALBUM_PROPERTIES_VARIABLES:
                del props[prop]
        return props

    def __str__(self) -> str:
        """
        Returns a string representation of this most important album properties

        Returns
        ---------
            A string for printing this album model's properties
        """
        return str(self.get_album_properties_dict())

    def get_asset_uuids(self) -> list:
        """
        Gathers UUIDs of all assets and returns them

        Returns
        ---------
            A list of asset UUIDs
        """
        return [asset_to_add['id'] for asset_to_add in self.assets]

    def find_incompatible_properties(self, other) -> list[str]:
        """
        Checks whether this Album Model and the other album model are compatible in terms of
        describing the same album for creation in a way that no album properties are in conflict
        with each other.
        All properties must either bei the same or not present in both objects, except for
          - id
          - name
          - assets

        Parameters
        ----------
        other : AlbumModel
            The other album model to check against

        Returns
        ---------
            A list of string representations for incompatible properties. The list is empty
            if there are no incompatible properties
        """
        if not isinstance(other, AlbumModel):
            return False
        incompatible_props = []
        props = self.get_album_properties_dict()
        other_props = other.get_album_properties_dict()
        for prop in props:
            if props[prop] != other_props[prop]:
                incompatible_props.append(f'{prop}: {props[prop]} vs {other_props[prop]}')

        return incompatible_props

    def merge_from(self, other, merge_mode: int):
        """
        Merges properties of other in self. The only properties not
        considered for merging are
          - id
          - name
          - assets

        Parameters
        ----------
        other : AlbumModel
            The other album model to merge properties from
        merge_mode: int
            Defines how the merge should be performed:
            - AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE: Only merge properties that are not already set in the merge target
            - AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE_EX: Same as above, but also raises an exception if attempting to merge an existing property
            - AlbumModel.ALBUM_MERGE_MODE_OVERRIDE: Overrides any existing property in merge target
        """
        # Do not try to merge unrelated types
        if not isinstance(other, AlbumModel):
            logging.warning("Trying to merge AlbumModel with incompatible type!")
            return
        own_attribs = vars(self)
        other_attribs = vars(other)

        # Override merge mode
        if merge_mode == AlbumModel.ALBUM_MERGE_MODE_OVERRIDE:
            for prop_name in AlbumModel.ALBUM_PROPERTIES_VARIABLES:
                if other_attribs[prop_name]:
                    own_attribs[prop_name] = other_attribs[prop_name]

        # Exclusive merge modes
        elif merge_mode in [AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE, AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE_EX]:
            for prop_name in AlbumModel.ALBUM_PROPERTIES_VARIABLES:
                if other_attribs[prop_name]:
                    if own_attribs[prop_name] and merge_mode == AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE_EX:
                        raise AlbumMergeException(f"Attempting to override {prop_name} in {self.name} with {other_attribs[prop_name]}")
                    own_attribs[prop_name] = other_attribs[prop_name]


    def get_final_name(self) -> str:
        """
        Gets the album model's name to use when talking to Immich, i.e.
        returns override_name if set, otherwise name.

        Returns
        ---------
            override_name if set, otherwise name
        """
        if self.override_name:
            return self.override_name
        return self.name

    @staticmethod
    def parse_album_properties_file(album_properties_file_path: str):
        """
        Parses the provided album properties file into an AlbumModel

        Parameters
        ----------
            album_properties_file_path : str
                The fully qualified path to a valid album properties file

        Returns
        ---------
            An AlbumModel that represents the album properties

        Raises
        ---------
            YAMLError
                If the provided album properties file could not be found or parsed
        """
        with open(album_properties_file_path, 'r', encoding="utf-8") as stream:
            album_properties = yaml.safe_load(stream)
            if album_properties:
                album_props_template = AlbumModel(None)
                album_props_template_vars = vars(album_props_template)
                for album_prop_name in AlbumModel.ALBUM_PROPERTIES_VARIABLES:
                    if album_prop_name in album_properties:
                        album_props_template_vars[album_prop_name] = album_properties[album_prop_name]

                # Backward compatibility, remove when archive is removed:
                if album_props_template.archive is not None:
                    logging.warning("Found deprecated property archive in %s! This will be removed in the future, use visibility: archive instead!", album_properties_file_path)
                    if album_props_template.visibility is None:
                        album_props_template.visibility = 'archive'
                #  End backward compatibility
                return album_props_template

        return None

def find_albumprops_files(paths: list[str]) -> list[str]:
    """
    Recursively finds all album properties files in all passed paths.

    Parameters
    ----------
        paths : list[str]
            A list of paths to search for album properties files

    Returns
    ---------
        A list of paths with all album properties files
    """
    albumprops_files = []
    for path in paths:
        if not os.path.isdir(path):
            logging.warning("Album Properties Discovery: Path %s does not exist!", path)
            continue
        for path_tuple in os.walk(path):
            root = path_tuple[0]
            filenames = path_tuple[2]
            for filename in fnmatch.filter(filenames, ALBUMPROPS_FILE_NAME):
                albumprops_files.append(os.path.join(root, filename))
    return albumprops_files

def identify_root_path(path: str, root_path_list: list[str]) -> str:
    """
    Identifies which root path is the parent of the provided path.

    :param path: The path to find the root path for
    :type path: str
    :param root_path_list: The list of root paths to get the one path is a child of from
    :type root_path_list: list[str]
    :return: The root path from root_path_list that is the parent of path
    :rtype: str
    """
    for root_path in root_path_list:
        if root_path in path:
            return root_path
    return None

def build_album_properties_templates() -> dict:
    """
    Searches all root paths for album properties files,
    applies ignore/filtering mechanisms, parses the files,
    creates AlbumModel objects from them, performs validations and returns
    a dictionary mapping mapping the album name (generated from the path the album properties file was found in)
    to the album model file.
    If a fatal error occurs during processing of album properties files (i.e. two files encountered targeting the same album with incompatible properties), the
    program exits.

    Returns
    ---------
        A dictionary mapping mapping the album name (generated from the path the album properties file was found in)
        to the album model files
    """
    fatal_error_occurred = False
    album_properties_file_paths = find_albumprops_files(root_paths)
    # Dictionary mapping album name generated from album properties' path to the AlbumModel representing the
    # album properties
    album_props_templates = {}
    album_name_to_album_properties_file_path = {}
    for album_properties_file_path in album_properties_file_paths:
        # First check global path_filter and ignore options
        if is_path_ignored(album_properties_file_path):
            continue

        # Identify the root path
        album_props_root_path = identify_root_path(album_properties_file_path, root_paths)
        if not album_props_root_path:
            continue

        # Chunks of the asset's path below root_path
        path_chunks = album_properties_file_path.replace(album_props_root_path, '').split('/')
        # A single chunk means it's just the image file in no sub folder, ignore
        if len(path_chunks) == 1:
            continue

        # remove last item from path chunks, which is the file name
        del path_chunks[-1]
        album_name = create_album_name(path_chunks, album_level_separator, album_name_post_regex)
        if album_name is None:
            continue
        try:
            # Parse the album properties into an album model
            album_props_template = AlbumModel.parse_album_properties_file(album_properties_file_path)
            if not album_props_template:
                logging.warning("Unable to parse album properties file %s", album_properties_file_path)
                continue

            album_props_template.name = album_name
            if not album_name in album_props_templates:
                album_props_templates[album_name] = album_props_template
                album_name_to_album_properties_file_path[album_name] = album_properties_file_path
            # There is already an album properties template with the same album name (maybe from a different root_path)
            else:
                incompatible_props = album_props_template.find_incompatible_properties(album_props_templates[album_name])
                if len(incompatible_props) > 0:
                    logging.fatal("Album Properties files %s and %s create an album with identical name but have conflicting properties:",
                                album_name_to_album_properties_file_path[album_name], album_properties_file_path)
                    for incompatible_prop in incompatible_props:
                        logging.fatal(incompatible_prop)
                    fatal_error_occurred = True

        except yaml.YAMLError as ex:
            logging.error("Could not parse album properties file %s: %s", album_properties_file_path, ex)

    if fatal_error_occurred:
        logging.fatal("Encountered at least one fatal error during parsing or validating of album properties files, exiting!")
        sys.exit(1)

    # Now validate that all album properties templates with the same override_name are compatible with each other
    validate_album_props_templates(album_props_templates.values(), album_name_to_album_properties_file_path)

    return album_props_templates

def validate_album_props_templates(album_props_templates: list[AlbumModel], album_name_to_album_properties_file_path: dict):
    """
    Validates the provided list of album properties.
    Specifically, checks that if multiple album properties files specify the same override_name, all other specified properties
    are the same as well.

    If a validation error occurs, the program exits.

    Parameters
    ----------
        album_props_templates : list[AlbumModel]
            The list AlbumModel objects to validate
        album_name_to_album_properties_file_path : dict
            A dictionary where the key is an album name and the value is the path to the album properties file the
            album was generated from.
            This method expects one entry in this dictionary for every AlbumModel in album_props_templates
    """
    fatal_error_occurred = False
    # This is a cache to remember checked names - keep time complexity down
    checked_override_names = []
    # Loop over all album properties templates
    for album_props_template in album_props_templates:
        # Check if override_name is set and not already checked
        if album_props_template.override_name and album_props_template.override_name not in checked_override_names:
            # Inner loop through album properties template
            for album_props_template_to_check in album_props_templates:
                # Do not check against ourselves and only check if the other template has the same override name (we already checked above that override_name is not None)
                if (album_props_template is not album_props_template_to_check
                    and album_props_template.override_name == album_props_template_to_check.override_name):
                    if check_for_and_log_incompatible_properties(album_props_template, album_props_template_to_check, album_name_to_album_properties_file_path):
                        fatal_error_occurred = True
            checked_override_names.append(album_props_template.override_name)

    if fatal_error_occurred:
        logging.fatal("Encountered at least one fatal error while validating album properties files, exiting!")
        sys.exit(1)

def check_for_and_log_incompatible_properties(model1: AlbumModel, model2: AlbumModel, album_name_to_album_properties_file_path: dict) -> bool:
    """
    Checks if model1 and model2 have incompatible properties (same properties set to different values). If so,
    logs the the incompatible properties and returns True.

    Parameters
    ----------
      - model1 : AlbumModel
            The first album model to check for incompatibility with the second model
      - model2 : AlbumModel
            The second album model to check for incompatibility with the first model
      - album_name_to_album_properties_file_path : dict
            A dictionary where the key is an album name and the value is the path to the album properties file the
            album was generated from.
            This method expects one entry in this dictionary for every AlbumModel in album_props_templates
    Returns
    ---------
        False if model1 and model2 are compatible, otherwise True
    """
    incompatible_props = model1.find_incompatible_properties(model2)
    if len(incompatible_props) > 0:
        logging.fatal("Album properties files %s and %s define the same override_name but have incompatible properties:",
                        album_name_to_album_properties_file_path[model1.name],
                        album_name_to_album_properties_file_path[model2.name])
        for incompatible_prop in incompatible_props:
            logging.fatal(incompatible_prop)
        return True
    return False

def is_integer(string_to_test: str) -> bool:
    """
    Trying to deal with python's isnumeric() function
    not recognizing negative numbers, tests whether the provided
    string is an integer or not.

    Parameters
    ----------
        string_to_test : str
            The string to test for integer
    Returns
    ---------
        True if string_to_test is an integer, otherwise False
    """
    try:
        int(string_to_test)
        return True
    except ValueError:
        return False

# Translation of GLOB-style patterns to Regex
# Source: https://stackoverflow.com/a/63212852
# FIXME_EVENTUALLY: Replace with glob.translate() introduced with Python 3.13
escaped_glob_tokens_to_re = OrderedDict((
    # Order of ``**/`` and ``/**`` in RE tokenization pattern doesn't matter because ``**/`` will be caught first no matter what, making ``/**`` the only option later on.
    # W/o leading or trailing ``/`` two consecutive asterisks will be treated as literals.
    ('/\\*\\*', '(?:/.+?)*'), # Edge-case #1. Catches recursive globs in the middle of path. Requires edge case #2 handled after this case.
    ('\\*\\*/', '(?:^.+?/)*'), # Edge-case #2. Catches recursive globs at the start of path. Requires edge case #1 handled before this case. ``^`` is used to ensure proper location for ``**/``.
    ('\\*', '[^/]*'), # ``[^/]*`` is used to ensure that ``*`` won't match subdirs, as with naive ``.*?`` solution.
    ('\\?', '.'),
    ('\\[\\*\\]', '\\*'), # Escaped special glob character.
    ('\\[\\?\\]', '\\?'), # Escaped special glob character.
    ('\\[!', '[^'), # Requires ordered dict, so that ``\\[!`` preceded ``\\[`` in RE pattern.
                    # Needed mostly to differentiate between ``!`` used within character class ``[]`` and outside of it, to avoid faulty conversion.
    ('\\[', '['),
    ('\\]', ']'),
))

escaped_glob_replacement = regex.compile('(%s)' % '|'.join(escaped_glob_tokens_to_re).replace('\\', '\\\\\\'))

def glob_to_re(pattern: str) -> str:
    """
    Converts the provided GLOB pattern to
    a regular expression.

    Parameters
    ----------
        pattern : str
            A GLOB-style pattern to convert to a regular expression
    Returns
    ---------
        A regular expression matching the same strings as the provided GLOB pattern
    """
    return escaped_glob_replacement.sub(lambda match: escaped_glob_tokens_to_re[match.group(0)], regex.escape(pattern))

def read_file(file_path: str) -> str:
    """
    Reads and returns the contents of the provided file.

    Parameters
    ----------
        file_path : str
            Path to the file to read
    Raises
    ----------
        FileNotFoundError if the file does not exist
        Exception on any other error reading the file
    Returns
    ---------
        The file's contents
    """
    with open(file_path, 'r', encoding="utf-8") as secret_file:
        return secret_file.read().strip()

def read_api_key_from_file(file_path: str) -> str:
    """
    Reads the API key from the provided file

    Parameters
    ----------
        file_path : str
            Path to the file to read
    Returns
    ---------
        The API key or None on error
    """
    try:
        return read_file(file_path)
    except FileNotFoundError:
        logging.error("API Key file not found at %s", args["api_key"])
    except OSError as ex:
        logging.error("Error reading API Key file: %s", ex)
    return None

def determine_api_key(api_key_source: str, key_type: str) -> str:
    """
    Determines the API key base on key_type.
    For key_type 'literal', api_key_source is returned as is.
    For key'type 'file', api_key_source is a path to a file containing the API key,
    and the file's contents are returned.

    Parameters
    ----------
        api_key_source : str
            An API key or path to a file containing an API key
        key_type : str
            Must be either 'literal' or 'file'
    Returns
    ---------
        The API key or None on error
    """
    if key_type == 'literal':
        return api_key_source
    if key_type == 'file':
        return read_file(api_key_source)
    # At this point key_type is not a valid value
    logging.error("Unknown key type (-t, --key-type). Must be either 'literal' or 'file'.")
    return None

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
    return expr

def divide_chunks(full_list: list, chunk_size: int):
    """Yield successive n-sized chunks from l. """
    # looping till length l
    for j in range(0, len(full_list), chunk_size):
        yield full_list[j:j + chunk_size]

def parse_separated_string(separated_string: str, separator: str) -> Tuple[str, str]:
    """
    Parse a key, value pair, separated by the provided separator.

    That's the reverse of ShellArgs.
    On the command line (argparse) a declaration will typically look like:
        foo=hello
    or
        foo="hello world"
    """
    items = separated_string.split(separator)
    key = items[0].strip() # we remove blanks around keys, as is logical
    value = None
    if len(items) > 1:
        # rejoin the rest:
        value = separator.join(items[1:])
    return (key, value)


def parse_separated_strings(items: list[str]) -> dict:
    """
    Parse a series of key-value pairs and return a dictionary
    """
    parsed_strings_dict = {}
    if items:
        for item in items:
            key, value = parse_separated_string(item, '=')
            parsed_strings_dict[key] = value
    return parsed_strings_dict

# pylint: disable=R0912
def create_album_name(asset_path_chunks: list[str], album_separator: str, album_name_postprocess_regex: list) -> str:
    """
    Create album names from provided path_chunks string array.

    The method uses global variables album_levels_range_arr or album_levels to
    generate album names either by level range or absolute album levels. If multiple
    album path chunks are used for album names they are separated by album_separator.

    album_name_postprocess_regex is list of pairs of regex and replace, this is optional

    Returns
    -------
        The created album name or None if the album levels range does not apply to the path chunks.
    """

    album_name_chunks = ()
    logging.debug("path chunks = %s", list(asset_path_chunks))
    # Check which path to take: album_levels_range or album_levels
    if len(album_levels_range_arr) == 2:
        if album_levels_range_arr[0] < 0:
            album_levels_start_level_capped = min(len(asset_path_chunks), abs(album_levels_range_arr[0]))
            album_levels_end_level_capped =  album_levels_range_arr[1]+1
            album_levels_start_level_capped *= -1
        else:
            # If our start range is already out of range of our path chunks, do not create an album from that.
            if len(asset_path_chunks)-1 < album_levels_range_arr[0]:
                logging.debug("Skipping asset chunks since out of range: %s", asset_path_chunks)
                return None
            album_levels_start_level_capped = min(len(asset_path_chunks)-1, album_levels_range_arr[0])
            # Add 1 to album_levels_end_level_capped to include the end index, which is what the user intended to. It's not a problem
            # if the end index is out of bounds.
            album_levels_end_level_capped =  min(len(asset_path_chunks)-1, album_levels_range_arr[1]) + 1
        logging.debug("album_levels_start_level_capped = %d", album_levels_start_level_capped)
        logging.debug("album_levels_end_level_capped = %d", album_levels_end_level_capped)
        # album start level is not equal to album end level, so we want a range of levels
        if album_levels_start_level_capped is not album_levels_end_level_capped:

            # if the end index is out of bounds.
            if album_levels_end_level_capped < 0 and abs(album_levels_end_level_capped) >= len(asset_path_chunks):
                album_name_chunks = asset_path_chunks[album_levels_start_level_capped:]
            else:
                album_name_chunks = asset_path_chunks[album_levels_start_level_capped:album_levels_end_level_capped]
        # album start and end levels are equal, we want exactly that level
        else:
            # create on-the-fly array with a single element taken from
            album_name_chunks = [asset_path_chunks[album_levels_start_level_capped]]
    else:
        album_levels_int = int(album_levels)
        # either use as many path chunks as we have,
        # or the specified album levels
        album_name_chunk_size = min(len(asset_path_chunks), abs(album_levels_int))
        if album_levels_int < 0:
            album_name_chunk_size *= -1

        # Copy album name chunks from the path to use as album name
        album_name_chunks = asset_path_chunks[:album_name_chunk_size]
        if album_name_chunk_size < 0:
            album_name_chunks = asset_path_chunks[album_name_chunk_size:]
    logging.debug("album_name_chunks = %s", album_name_chunks)

    # final album name before regex
    album_name = album_separator.join(album_name_chunks)
    logging.debug("Album Name %s", album_name)

    # apply regex if any
    if album_name_postprocess_regex:
        for pattern, *repl in album_name_postprocess_regex:
            # If no replacement string provided, default to empty string
            replace = repl[0] if repl else ''
            album_name = regex.sub(pattern, replace, album_name)
            logging.debug("Album Post Regex s/%s/%s/g --> %s", pattern, replace, album_name)

    return album_name.strip()

def fetch_server_version() -> dict:
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
    r = requests.get(api_endpoint, **requests_kwargs, timeout=api_timeout)
    # The API endpoint changed in Immich v1.118.0, if the new endpoint
    # was not found try the legacy one
    if r.status_code == 404:
        api_endpoint = f'{root_url}server-info/version'
        r = requests.get(api_endpoint, **requests_kwargs, timeout=api_timeout)

    if r.status_code == 200:
        server_version = r.json()
        logging.info("Detected Immich server version %s.%s.%s", server_version['major'], server_version['minor'], server_version['patch'])
    # Any other errors mean communication error with API
    else:
        logging.error("Communication with Immich API failed! Make sure the passed API URL is correct!")
        check_api_response(r)
    return server_version


def fetch_assets(is_not_in_album: bool, visibility_options: list[str]) -> list:
    """
    Fetches assets from the Immich API.

    Uses the /search/meta-data call. Much more efficient than the legacy method
    since this call allows to filter for assets that are not in an album only.

    Parameters
    ----------
        is_not_in_album : bool
            Flag indicating whether to fetch only assets that are not part
            of an album or not. If set to False, will find images in albums and
            not part of albums
        visibility_options : list[str]
            A list of visibility options to find and return assets with
    Returns
    ---------
        An array of asset objects
    """
    if version['major'] == 1 and version ['minor'] < 133:
        return fetch_assets_with_options({'isNotInAlbum': is_not_in_album, 'withArchived': 'archive' in visibility_options})

    asset_list = fetch_assets_with_options({'isNotInAlbum': is_not_in_album})
    for visiblity_option in visibility_options:
        # Do not fetch agin for 'timeline', that's the default!
        if visiblity_option != 'timeline':
            asset_list += fetch_assets_with_options({'isNotInAlbum': is_not_in_album, 'visibility': visiblity_option})
    return asset_list

def check_for_and_remove_live_photo_video_components(asset_list: list[dict], is_not_in_album: bool, find_archived: bool) -> list[dict]:
    """
    Checks asset_list for any asset with file ending .mov. This is indicative of a possible video component
    of an Apple Live Photo. There is display bug in the Immich iOS app that prevents live photos from being
    show correctly if the static AND video component are added to the album. We only want to add the static component to an album,
    so we need to filter out all video components belonging to a live photo. The static component has a property livePhotoVideoId set
    with the asset ID of the video component.

    Parameters
    ----------
        is_not_in_album : bool
            Flag indicating whether to fetch only assets that are not part
            of an album or not. If this and find_archived are True, we can assume asset_list is complete
            and should contain any static components.
        find_archived : bool
            Flag indicating whether to only fetch assets that are archived. If this and is_not_in_album are
            True, we can assume asset_list is complete and should contain any static components.

    Returns
    ---------
       An asset list without live photo video components
    """
    logging.info("Checking for live photo video components")
    # Filter for all quicktime assets
    asset_list_mov = [asset for asset in asset_list if 'video' in asset['originalMimeType']]

    if len(asset_list_mov) == 0:
        logging.debug("No live photo video components found")
        return asset_list

    # If either is not True, we need to fetch all assets
    if is_not_in_album or not find_archived:
        logging.debug("Fetching all assets for live photo video component check")
        if version['major'] == 1 and version ['minor'] < 133:
            full_asset_list = fetch_assets_with_options({'isNotInAlbum': False, 'withArchived': True})
        else:
            full_asset_list = fetch_assets_with_options({'isNotInAlbum': False})
            full_asset_list += fetch_assets_with_options({'isNotInAlbum': False, 'visibility': 'archive'})
    else:
        full_asset_list = asset_list

    # Find all assets with a live ID set
    asset_list_with_live_id = [asset for asset in full_asset_list if asset['livePhotoVideoId'] is not None]

    # Find all video components
    asset_list_video_components_ids = []
    for asset_static_component in asset_list_with_live_id:
        for asset_mov in asset_list_mov:
            if asset_mov['id'] == asset_static_component['livePhotoVideoId']:
                asset_list_video_components_ids.append(asset_mov['id'])
                logging.debug("File %s is a video component of a live photo, removing from list", asset_mov['originalPath'])

    logging.info("Removing %s live photo video components from asset list", len(asset_list_video_components_ids))
    # Remove all video components from the asset list
    asset_list_without_video_components = [asset for asset in asset_list if asset['id'] not in asset_list_video_components_ids]
    return asset_list_without_video_components


def fetch_assets_with_options(search_options: dict) -> list:
    """
    Fetches assets from the Immich API using specific search options.
    The search options directly correspond to the body used for the search API request.

    Parameters
    ----------
        search_options: dict
            Dictionary containing options to pass to the search/metadata API endpoint
    Returns
    ---------
        An array of asset objects
    """
    body = search_options
    assets_found = []
    # prepare request body

    # This API call allows a maximum page size of 1000
    number_of_assets_to_fetch_per_request_search = min(1000, number_of_assets_to_fetch_per_request)
    body['size'] = number_of_assets_to_fetch_per_request_search
    # Initial API call, let's fetch our first chunk
    page = 1
    body['page'] = str(page)
    r = requests.post(root_url+'search/metadata', json=body, **requests_kwargs, timeout=api_timeout)
    r.raise_for_status()
    response_json = r.json()
    assets_received = response_json['assets']['items']
    logging.debug("Received %s assets with chunk %s", len(assets_received), page)

    assets_found = assets_found + assets_received
    # If we got a full chunk size back, let's perform subsequent calls until we get less than a full chunk size
    while len(assets_received) == number_of_assets_to_fetch_per_request_search:
        page += 1
        body['page'] = page
        r = requests.post(root_url+'search/metadata', json=body, **requests_kwargs, timeout=api_timeout)
        check_api_response(r)
        response_json = r.json()
        assets_received = response_json['assets']['items']
        logging.debug("Received %s assets with chunk %s", len(assets_received), page)
        assets_found = assets_found + assets_received
    return assets_found


def fetch_albums() -> dict:
    """Fetches albums from the Immich API, we enrich the album data with the paths"""

    api_endpoint = 'albums'

    if fetched_albums := read_yaml('.albums_cache.yaml'):
        logging.info("Loaded albums %s from cache", len(fetched_albums))
        return fetched_albums

    r = requests.get(root_url+api_endpoint, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)
    fetched_albums = r.json()

    # in case don't want to merge folders, we need to track the original paths of the assets
    if not merge_folder:
        for a in fetched_albums:
            album_detail = fetch_album_info(a['id'])

            a['album_paths'] = list({os.path.dirname(asset['originalPath']) for asset in album_detail['assets']})

            # just log if multiple paths...
            if len(a['album_paths']) > 1:
                logging.info("Album '%s' is made out of %d Folders", a['albumName'], len(a['album_paths']))
                logging.debug("Paths: %s", ','.join(a['album_paths']))

    write_yaml(fetched_albums, '.albums_cache.yaml')
    return fetched_albums


def fetch_album_info(album_id_for_info: str):
    """
    Fetches information about a specific album

    Parameters
    ----------
        album_id_for_info : str
            The ID of the album to fetch information for

    """

    api_endpoint = f'albums/{album_id_for_info}'

    r = requests.get(root_url+api_endpoint, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)
    return r.json()

def delete_album(album_delete: dict):
    """
    Deletes an album identified by album_to_delete['id']

    If the album could not be deleted, logs an error.

    Parameters
    ----------
        album_delete : dict
            Dictionary with the following keys:
                - id
                - albumName

    Returns
    ---------
        True if the album was deleted, otherwise False
    """
    api_endpoint = 'albums'

    logging.debug("Deleting Album: Album ID = %s, Album Name = %s", album_delete['id'], album_delete['albumName'])
    r = requests.delete(root_url+api_endpoint+'/'+album_delete['id'], **requests_kwargs, timeout=api_timeout)
    try:
        check_api_response(r)
        return True
    except HTTPError:
        logging.error("Error deleting album %s: %s", album_delete['albumName'], r.reason)
        return False

def create_album(album_name_to_create: str) -> str:
    """
    Creates an album with the provided name and returns the ID of the created album


    Parameters
    ----------
        album_name_to_create : str
            Name of the album to create

    Returns
    ---------
        True if the album was deleted, otherwise False

    Raises
    ----------
        Exception if the API call failed
    """

    api_endpoint = 'albums'

    data = {
        'albumName': album_name_to_create
    }
    r = requests.post(root_url+api_endpoint, json=data, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)

    return r.json()['id']


def is_path_ignored(path_to_check: str) -> bool:
    """
    Determines if the asset should be ignored for the purpose of this script
    based in its originalPath and global ignore and path_filter options.

    Parameters
    ----------
        asset_to_check : dict
            The asset to check if it must be ignored or not. Must have the key 'originalPath'.
    Returns
    ----------
        True if the asset must be ignored, otherwise False
    """
    is_path_ignored_result = False
    asset_root_path = None
    for root_path_to_check in root_paths:
        if root_path_to_check in path_to_check:
            asset_root_path = root_path_to_check
            break
    logging.debug("Identified root_path for asset %s = %s", path_to_check, asset_root_path)
    if asset_root_path:
        # First apply filter, if any
        if len(path_filter_regex) > 0:
            any_match = False
            for path_filter_regex_entry in path_filter_regex:
                if regex.fullmatch(path_filter_regex_entry, path_to_check.replace(asset_root_path, '')):
                    any_match = True
            if not any_match:
                logging.debug("Ignoring path %s due to path_filter setting!", path_to_check)
                is_path_ignored_result = True
        # If the asset "survived" the path filter, check if it is in the ignore_albums argument
        if not is_path_ignored_result and len(ignore_albums_regex) > 0:
            for ignore_albums_regex_entry in ignore_albums_regex:
                if regex.fullmatch(ignore_albums_regex_entry, path_to_check.replace(asset_root_path, '')):
                    is_path_ignored_result = True
                    logging.debug("Ignoring path %s due to ignore_albums setting!", path_to_check)
                    break

    return is_path_ignored_result


def add_assets_to_album(assets_add_album_id: str, asset_list: list[str]) -> list[str]:
    """
    Adds the assets IDs provided in assets to the provided albumId.

    If assets if larger than number_of_images_per_request, the list is chunked
    and one API call is performed per chunk.
    Only logs errors and successes.

    Returns

    Parameters
    ----------
        assets_add_album_id : str
            The ID of the album to add assets to
        asset_list: list[str]
            A list of asset IDs to add to the album

    Returns
    ---------
        The asset UUIDs that were actually added to the album (not respecting assets that were already part of the album)
    """
    api_endpoint = 'albums'

    # Divide our assets into chunks of number_of_images_per_request,
    # So the API can cope
    assets_to_add = []
    for _ in assets:
        for _asset in asset_list:
            if _['id'] == _asset:
                assets_to_add.append(_)
                break
    logging.debug("Added assets to album: %s", assets_to_add)
    assets_chunked = list(divide_chunks(asset_list, number_of_images_per_request))
    asset_list_added = []

    for assets_chunk in assets_chunked:
        data = {'ids':assets_chunk}
        r = requests.put(root_url+api_endpoint+f'/{assets_add_album_id}/assets', json=data, **requests_kwargs, timeout=api_timeout)
        check_api_response(r)
        response = r.json()

        for res in response:
            if not res['success']:
                if  res['error'] != 'duplicate':
                    logging.warning("Error adding an asset to an album: %s", res['error'])
            else:
                asset_list_added.append(res['id'])

    return asset_list_added

def fetch_users():
    """Queries and returns all users"""

    api_endpoint = 'users'

    r = requests.get(root_url+api_endpoint, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)
    return r.json()

# Disable pylint for too many branches
# pylint: disable=R0912
def update_album_shared_state(album_to_share: AlbumModel, unshare_users: bool) -> None:
    """
    Makes sure the album is shared with the users set in the model with the correct roles.
    This involves fetching album info from Immich to check if/who the album is shared with and the share roles,
    then either updating the share role, removing the user, or adding the users

    Parameters
    ----------
        album_to_share : AlbumModel
            The album to share, with the expected share_with setting
        unshare_users: bool
            Flag indicating whether to actively unshare albums if shared with a user that is not in the current
            share settings
    Raises
    ----------
        HTTPError if the API call fails
    """
    # Parse and prepare expected share roles
    # List all share users by share role
    share_users_to_roles_expected = {}
    for share_user in album.share_with:
        # Find the user by configured name or email
        share_user_in_immich = find_user_by_name_or_email(share_user['user'], users)
        if not share_user_in_immich:
            logging.warning("User %s to share album %s with does not exist!", share_user['user'], album.get_final_name())
            continue
        share_users_to_roles_expected[share_user_in_immich['id']] = share_user['role']

    # No users to share with and unsharing is disabled?
    if len(share_users_to_roles_expected) == 0 and not unshare_users:
        return

    # Now fetch reality
    album_to_share_info = fetch_album_info(album_to_share.id)
    # Dict mapping a user ID to share role
    album_share_info = {}
    for share_user_actual in album_to_share_info['albumUsers']:
        album_share_info[share_user_actual['user']['id']] = share_user_actual['role']

    # Group share users by share role
    share_roles_to_users_expected = {}
    # Now compare expectation with reality and update
    for user_to_share_with, share_role_expected in share_users_to_roles_expected.items():
        # Case: Album is not share with user
        if user_to_share_with not in album_share_info:
            # Gather all users to share the album with for this role
            if not share_role_expected in share_roles_to_users_expected:
                share_roles_to_users_expected[share_role_expected] = []
            share_roles_to_users_expected[share_role_expected].append(user_to_share_with)

        # Case: Album is shared, but with wrong role
        elif album_share_info[user_to_share_with] != share_role_expected:
            try:
                update_album_share_user_role(album_to_share.id, user_to_share_with, share_role_expected)
                logging.debug("Sharing: Updated share role for user %s in album %s to %s", user_to_share_with, album_to_share.get_final_name(), share_role_expected)
            except HTTPError as ex:
                logging.warning("Sharing: Error updating share role for user %s in album %s to %s", user_to_share_with, album_to_share.get_final_name(), share_role_expected)
                logging.debug("Error: %s", ex)

    # Now check if the album is shared with any users it should not be shared with
    if unshare_users:
        for shared_user in album_share_info:
            if shared_user not in share_users_to_roles_expected:
                try:
                    unshare_album_with_user(album_to_share.id, shared_user)
                    logging.debug("Sharing: User %s removed from album %s", shared_user, album_to_share.get_final_name())
                except HTTPError as ex:
                    logging.warning("Sharing: Error removing user %s from album %s", shared_user, album_to_share.get_final_name())
                    logging.debug("Error: %s", ex)

    # Now share album with all users it is not already shared with
    if len(share_roles_to_users_expected) > 0:
        # Share album for users by role
        for share_role_group, share_users in share_roles_to_users_expected.items():
            # Convert list of user dicts to list of user IDs
            try:
                share_album_with_user_and_role(album_to_share.id, share_users, share_role_group)
                logging.debug("Album %s shared with users IDs %s in role: %s", album_to_share.get_final_name(), share_users, share_role_group)
            except (AssertionError, HTTPError) as ex:
                logging.warning("Error sharing album %s for users %s in role %s", album_to_share.get_final_name(), share_users, share_role_group)
                logging.debug("Album share error: %s", ex)

def unshare_album_with_user(album_id_to_unshare: str, unshare_user_id: str) -> None:
    """
    Unshares the provided album with the provided user

    Parameters
    ----------
        album_id_to_unshare : str
            The ID of the album to unshare
        unshare_user_id: str
            The user ID to remove from the album's share list
    Raises
    ----------
        HTTPError if the API call fails
    """
    api_endpoint = f'albums/{album_id_to_unshare}/user/{unshare_user_id}'
    r = requests.delete(root_url+api_endpoint, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)

def update_album_share_user_role(album_id_to_share: str, share_user_id: str, share_user_role: str) -> None:
    """
    Updates the user's share role for the provided album ID.

    Parameters
    ----------
        album_id_to_share : str
            The ID of the album to share
        share_user_id: str
            The user ID to update the share role for
        share_user_role: str
            The share role to update the user to
    Raises
    ----------
        AssertionError if user_share_role contains an invalid value
        HTTPError if the API call fails
    """
    api_endpoint = f'albums/{album_id_to_share}/user/{share_user_id}'

    assert share_role in SHARE_ROLES

    data = {
        'role': share_user_role
    }

    r = requests.put(root_url+api_endpoint, json=data, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)

def share_album_with_user_and_role(album_id_to_share: str, user_ids_to_share_with: list[str], user_share_role: str) -> None:
    """
    Shares the album with the provided album_id with all provided share_user_ids
    using share_role as a role.

    Parameters
    ----------
        album_id_to_share : str
            The ID of the album to share
        user_ids_to_share_with: list[str]
            IDs of users to share the album with
        user_share_role: str
            The share role to use when sharing the album, valid values are
            "viewer" or "editor"
    Raises
    ----------
        AssertionError if user_share_role contains an invalid value
        HTTPError if the API call fails
    """
    api_endpoint = f'albums/{album_id_to_share}/users'

    assert share_role in SHARE_ROLES

    # build payload
    album_users = []
    for user_id_to_share_with in user_ids_to_share_with:
        share_info = {}
        share_info['role'] = user_share_role
        share_info['userId'] = user_id_to_share_with
        album_users.append(share_info)

    data = {
        'albumUsers': album_users
    }

    r = requests.put(root_url+api_endpoint, json=data, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)

def trigger_offline_asset_removal() -> None:
    """
    Removes offline assets.

    Takes into account API changes happening between v1.115.0 and v1.116.0.

    Before v1.116.0, offline asset removal was an asynchronous job that could only be
    triggered by an Administrator for a specific library.

    Since v1.116.0, offline assets are no longer displayed in the main timeline but shown in the trash. They automatically
    come back from the trash when they are no longer offline. The only way to delete them is either by emptying the trash
    (along with everything else) or by selectively deleting all offline assets. This is option the script now uses.

    Raises
    ----------
        HTTPException if any API call fails
    """
    if version['major'] == 1 and version ['minor'] < 116:
        trigger_offline_asset_removal_pre_minor_version_116()
    else:
        trigger_offline_asset_removal_since_minor_version_116()

def trigger_offline_asset_removal_since_minor_version_116() -> None:
    """
    Synchronously deletes offline assets.

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
    # 2024/03/01: With Immich v1.128.0 isOffline filter is fixed. Remember to also request archived assets.
    trashed_assets = fetch_assets_with_options({'isTrashed': True, 'isOffline': True, 'withArchived': True})
    #logging.debug("search results: %s", offline_assets)

    offline_assets = [asset for asset in trashed_assets if asset['isOffline']]

    if len(offline_assets) > 0:
        logging.info("Deleting %s offline assets", len(offline_assets))
        logging.debug("Deleting the following offline assets (count: %d): %s", len(offline_assets), [asset['originalPath'] for asset in offline_assets])
        delete_assets(offline_assets, True)
    else:
        logging.info("No offline assets found!")


def delete_assets(assets_to_delete: list, force: bool):
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

    api_endpoint = 'assets'
    asset_ids_to_delete = [asset['id'] for asset in assets_to_delete]
    data = {
        'force': force,
        'ids': asset_ids_to_delete
    }

    r = requests.delete(root_url+api_endpoint, json=data, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)



def trigger_offline_asset_removal_pre_minor_version_116():
    """
    Triggers Offline Asset Removal Job.
    Only supported in Immich prior v1.116.0.
    Requires the script to run with an Administrator level API key.

    Works by fetching all libraries and triggering the Offline Asset Removal job
    one by one.

    Raises
    ----------
        HTTPError if the API call fails
    """
    libraries = fetch_libraries()
    for library in libraries:
        trigger_offline_asset_removal_async(library['id'])

def fetch_libraries() -> list[dict]:
    """
    Queries and returns all libraries

    Raises
    ----------
        Exception if any API call fails
    """

    api_endpoint = 'libraries'

    r = requests.get(root_url+api_endpoint, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)
    return r.json()

def trigger_offline_asset_removal_async(library_id: str):
    """
    Triggers removal of offline assets in the library identified by libraryId.

    Parameters
    ----------
        library_id : str
            The ID of the library to trigger offline asset removal for
    Raises
    ----------
        Exception if any API call fails
    """

    api_endpoint = f'libraries/{library_id}/removeOffline'

    r = requests.post(root_url+api_endpoint, **requests_kwargs, timeout=api_timeout)
    if r.status_code == 403:
        logging.fatal("--sync-mode 2 requires an Admin User API key!")
    else:
        check_api_response(r)

def set_album_thumb(thumbnail_album_id: str, thumbnail_asset_id: str):
    """
    Sets asset as thumbnail of album

    Parameters
    ----------
        thumbnail_album_id : str
            The ID of the album for which to set the thumbnail
        thumbnail_asset_id : str
            The ID of the asset to be set as thumbnail

    Raises
    ----------
        Exception if the API call fails
    """
    api_endpoint = f'albums/{thumbnail_album_id}'

    data = {"albumThumbnailAssetId": thumbnail_asset_id}

    r = requests.patch(root_url+api_endpoint, json=data, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)

def choose_thumbnail(thumbnail_setting: str, thumbnail_asset_list: list[dict]) -> str:
    """
    Tries to find an asset to use as thumbnail depending on thumbnail_setting.

    Parameters
    ----------
        thumbnail_setting : str
            Either a fully qualified asset path or one of 'first', 'last', 'random', 'random-filtered'
        asset_list: list[dict]
            A list of assets to choose a thumbnail from, based on thumbnail_setting

    Returns
    ----------
        An Immich asset dict or None if no thumbnail was found based on thumbnail_setting
    """
    # Case: fully qualified path
    if thumbnail_setting not in ALBUM_THUMBNAIL_SETTINGS_GLOBAL:
        for asset in thumbnail_asset_list:
            if asset['originalPath'] == thumbnail_setting:
                return asset
        # at this point we could not find the thumbnail asset by path
        return None

    # Case: Anything but fully qualified path
    # Apply filtering to assets
    thumbnail_assets = thumbnail_asset_list
    if thumbnail_setting == ALBUM_THUMBNAIL_RANDOM_FILTERED:
        thumbnail_assets[:] = [asset for asset in thumbnail_assets if not is_path_ignored(asset['originalPath'])]

    if len(thumbnail_assets) > 0:
        # Sort assets by creation date
        thumbnail_assets.sort(key=lambda x: x['fileCreatedAt'])
        if thumbnail_setting not in ALBUM_THUMBNAIL_STATIC_INDICES:
            idx = random.randint(0, len(thumbnail_assets)-1)
        else:
            idx = ALBUM_THUMBNAIL_STATIC_INDICES[thumbnail_setting]
        return thumbnail_assets[idx]

    # Case: Invalid thumbnail_setting
    return None


def update_album_properties(album_to_update: AlbumModel):
    """
    Sets album properties in Immich to the properties of the AlbumModel

    Parameters
    ----------
        album_to_update : AlbumModel
            The album model to use for updating the album

    Raises
    ----------
        Exception if the API call fails
    """
    # Initialize payload
    data = {}

    # Handle thumbnail
    # Thumbnail setting 'random-all' is handled separately
    if album_to_update.thumbnail_setting and album_to_update.thumbnail_setting != ALBUM_THUMBNAIL_RANDOM_ALL:
        # Fetch assets to be sure to have up-to-date asset list
        album_to_update_info = fetch_album_info(album_to_update.id)
        album_assets = album_to_update_info['assets']
        thumbnail_asset = choose_thumbnail(album_to_update.thumbnail_setting, album_assets)
        if thumbnail_asset:
            logging.info("Using asset %s as thumbnail for album %s", thumbnail_asset['originalPath'], album_to_update.get_final_name())
            data['albumThumbnailAssetId'] = thumbnail_asset['id']
        else:
            logging.warning("Unable to determine thumbnail for setting '%s' in album %s", album.thumbnail_setting, album.get_final_name())

    # Description
    if album_to_update.description:
        data['description'] = album.description

    # Sorting Order
    if album_to_update.sort_order:
        data['order'] = album.sort_order

    # Comments / Likes enabled
    if album_to_update.comments_and_likes_enabled is not None:
        data['isActivityEnabled'] = album_to_update.comments_and_likes_enabled

    # Only update album if there is something to update
    if len(data) > 0:
        api_endpoint = f'albums/{album_to_update.id}'

        response = requests.patch(root_url+api_endpoint, json=data, **requests_kwargs, timeout=api_timeout)
        check_api_response(response)

def set_assets_visibility(asset_ids_for_visibility: list[str], visibility_setting: str):
    """
    Sets the visibility of assets identified by the passed list of UUIDs.

    Parameters
    ----------
        asset_ids_for_visibility : list
            A list of asset IDs to set visibility for
        visibility : str
            The visibility to set
   
    Raises
    ----------
        Exception if the API call fails
    """
    api_endpoint = 'assets'
    data = {"ids": asset_ids_for_visibility}
    # Remove when minimum supported version is >= 133
    if version['major'] == 1 and version ['minor'] < 133:
        if visibility_setting is not None and visibility_setting not in ['archive', 'timeline']:
            # Warnings have been logged earlier, silently abort
            return
        is_archived = True
        if visibility_setting == 'timeline':
            is_archived = False
        data["isArchived"] = is_archived
    # Up-to-date Immich Server versions
    else:
        data["visibility"] = visibility_setting

    r = requests.put(root_url+api_endpoint, json=data, **requests_kwargs, timeout=api_timeout)
    check_api_response(r)

def check_api_response(response: requests.Response):
    """
    Checks the HTTP return code for the provided response and
    logs any errors before raising an HTTPError

    Parameters
    ----------
        response : requests.Response
            A list of asset IDs to archive
        isArchived : bool
            Flag indicating whether to archive or unarchive the passed assets

    Raises
    ----------
        HTTPError if the API call fails
    """
    try:
        response.raise_for_status()
    except HTTPError:
        if response.json():
            logging.error("Error in API call: %s", response.json())
        else:
            logging.error("API response did not contain a payload")
    response.raise_for_status()

def delete_all_albums(assets_visibility: str, force_delete: bool):
    """
    Deletes all albums in Immich if force_delete is True. Otherwise lists all albums
    that would be deleted.
    If assets_visibility is set, all assets in deleted albums
    will be set to that visibility.

    Parameters
    ----------
        assets_visibility : str
            Flag indicating whether to unarchive archived assets
        force_delete : bool
            Flag indicating whether to actually delete albums (True) or only to
            perform a dry-run (False)

    Raises
    ----------
        HTTPError if the API call fails
    """

    all_albums = fetch_albums()
    logging.info("%d existing albums identified", len(all_albums))
    # Delete Confirm check
    if not force_delete:
        album_names = []
        for album_to_delete in all_albums:
            album_names.append(album_to_delete['albumName'])
        print("Would delete the following albums (ALL albums!):")
        print(album_names)
        if is_docker:
            print("Run the container with environment variable DELETE_CONFIRM set to 1 to actually delete these albums!")
        else:
            print("Call with --delete-confirm to actually delete albums!")
        sys.exit(0)

    deleted_album_count = 0
    for album_to_delete in all_albums:
        if delete_album(album_to_delete):
             # If the archived flag is set it means we need to unarchived all images of deleted albums;
            # In order to do so, we need to fetch all assets of the album we're going to delete
            assets_in_deleted_album = []
            if assets_visibility is not None:
                album_to_delete_info = fetch_album_info(album_to_delete['id'])
                assets_in_deleted_album = album_to_delete_info['assets']
            logging.info("Deleted album %s", album_to_delete['albumName'])
            deleted_album_count += 1
            if len(assets_in_deleted_album) > 0 and assets_visibility is not None:
                set_assets_visibility([asset['id'] for asset in assets_in_deleted_album], assets_visibility)
                logging.info("Set visibility for %d assets to %s", len(assets_in_deleted_album), assets_visibility)
    logging.info("Deleted %d/%d albums", deleted_album_count, len(all_albums))

def cleanup_albums(albums_to_delete: list[AlbumModel], force_delete: bool):
    """
    Instead of creating, deletes albums in Immich if force_delete is True. Otherwise lists all albums
    that would be deleted.
    If unarchived_assets is set to true, all archived assets in deleted albums
    will be unarchived.

    Parameters
    ----------
        albums_to_delete: list[AlbumModel]
            A list of AlbumModel records to delete
        force_delete : bool
            Flag indicating whether to actually delete albums (True) or only to
            perform a dry-run (False)

    Returns
    ----------
        Number of successfully deleted albums

    Raises
    ----------
        HTTPError if the API call fails
    """
    # Delete Confirm check
    if not force_delete:
        print("Would delete the following albums:")
        print([a.get_final_name() for a in albums_to_delete])
        if is_docker:
            print("Run the container with environment variable DELETE_CONFIRM set to 1 to actually delete these albums!")
        else:
            print(" Call with --delete-confirm to actually delete albums!")
        return 0

    # At this point force_delete is true!
    cpt = 0
    for album_to_delete in albums_to_delete:
        # If the archived flag is set it means we need to unarchived all images of deleted albums;
        # In order to do so, we need to fetch all assets of the album we're going to delete
        assets_in_album = []
        # For cleanup, we only respect the global visibility flag to be able to either do not change
        # visibility at all, or to override whatever might be set in .ablumprops and revert to something else
        if visibility is not None:
            album_to_delete_info = fetch_album_info(album_to_delete.id)
            assets_in_album = album_to_delete_info['assets']
        if delete_album({'id': album_to_delete.id, 'albumName': album_to_delete.get_final_name()}):
            logging.info("Deleted album %s", album_to_delete.get_final_name())
            cpt += 1
            # Archive flag is set, so we need to unarchive assets
            if visibility is not None and len(assets_in_album) > 0:
                set_assets_visibility([asset['id'] for asset in assets_in_album], visibility)
                logging.info("Set visibility for %d assets to %s", len(assets_in_album), visibility)
    return cpt


def set_album_properties_in_model(album_model_to_update: AlbumModel):
    """
    Sets the album_model's properties based on script options set.

    Parameters
    ----------
        album_model : AlbumModel
            The album model to set the properties for
    """
    # Set share_with
    if share_with:
        for album_share_user in share_with:
            # Resolve share user-specific share role syntax <name>=<role>
            share_user_name, share_user_role = parse_separated_string(album_share_user, '=')
            # Fallback to default
            if share_user_role is None:
                share_user_role = share_role

            album_share_with = {
                'user': share_user_name,
                'role': share_user_role
            }
            album_model_to_update.share_with.append(album_share_with)

    # Thumbnail Setting
    if set_album_thumbnail:
        album_model_to_update.thumbnail_setting = set_album_thumbnail

    # Archive setting
    if visibility is not None:
        album_model_to_update.visibility = visibility

    # Sort Order
    if album_order:
        album_model_to_update.sort_order = album_order

    # Comments and Likes
    if comments_and_likes_enabled:
        album_model_to_update.comments_and_likes_enabled = True
    elif comments_and_likes_disabled:
        album_model_to_update.comments_and_likes_enabled = False

def album_core_path(asset_path : str, album_level ,root_path_list : list[str] ):
    """ returns the core path of an album """
    for root_path in root_path_list:
        if asset_path.startswith(root_path):
            if isinstance(album_level,int):
                path_chunks = asset_path[len(root_path):].split('/')
                if album_level < 0:
                    return '/'.join(path_chunks[album_level:])
                else:
                    return '/'.join(path_chunks[:album_level-1])
            if isinstance(album_level,list):
                #range not implemented yet
                pass
            else:
                return asset_path[len(root_path):]
    return asset_path


def build_album_list(asset_list : list[dict], root_path_list : list[str], album_props_templates: dict) -> dict:
    """
        Builds a list of album models, enriched with assets assigned to each album.
        Returns a list of AlbumModel objects.
        Attention!

        Parameters
        ----------
            asset_list : list[dict]
                List of assets dictionaries fetched from Immich API
            root_path_list : list[str]
                List of root paths to use for album creation
            album_props_templates: dict
                Dictionary mapping an album name to album properties

        Returns
        ---------
            A list of AlbumModel objects
    """
    album_models = []
    for asset_to_add in asset_list:
        asset_path = asset_to_add['originalPath']
        # This method will log the ignore reason, so no need to log anything again.
        if is_path_ignored(asset_path):
            continue

        # Identify the root path
        asset_root_path = identify_root_path(asset_path, root_path_list)
        if not asset_root_path:
            continue

        # Chunks of the asset's path below root_path
        path_chunks = asset_path.replace(asset_root_path, '').split('/')
        # A single chunk means it's just the image file in no sub folder, ignore
        if len(path_chunks) == 1:
            continue

        # remove last item from path chunks, which is the file name
        del path_chunks[-1]
        album_name = create_album_name(path_chunks, album_level_separator, album_name_post_regex)
        # Silently skip album, create_album_name already did debug logging
        if album_name is None:
            continue

        if len(album_name) > 0:
            logging.debug("Asset '%s' -> Album '%s'", asset_to_add['originalPath'], album_name)

            # Check if album properties exist for this album
            album_props_template = album_props_templates.get(album_name)
            # check if we have an existing album in this run. In case we we don't want to have merged albums, we compare the Asset Path to the album_paths Attribute
            existing_album_model = next(
                (a for a in album_models if a.name == album_name and (merge_folder or album_core_path(asset_to_add['originalPath'], album_levels, root_path_list) in a.album_paths)),
                None
            )

            if existing_album_model is None:
                # Create a new AlbumModel if no existing one is found
                logging.debug("New Album '%s'?", album_name)
                new_album_model = AlbumModel(album_name)
                set_album_properties_in_model(new_album_model)
                if album_props_template:
                    new_album_model.merge_from(album_props_template, AlbumModel.ALBUM_MERGE_MODE_OVERRIDE)
                album_models.append(new_album_model)
            else:
                # Merge properties into the existing AlbumModel
                logging.debug("Reuse Album '%s' with %i assets (in this run)", existing_album_model.name, len(existing_album_model.assets))
                new_album_model = existing_album_model
                if album_props_template:
                    new_album_model.merge_from(album_props_template, AlbumModel.ALBUM_MERGE_MODE_OVERRIDE)

            # Add asset to album model
            new_album_model.add_asset(asset_to_add)
        else:
            logging.warning("Got empty album name for asset path %s, check your album_level settings!", asset_path)
    return album_models


def find_user_by_name_or_email(name_or_email: str, user_list: list[dict]) -> dict:
    """
    Finds a user identified by name_or_email in the provided user_list.

    Parameters
    ----------
        name_or_email: str
            The user name or email address to find the user by
        user_list: list[dict]
            A list of user dictionaries with the following mandatory keys:
              - id
              - name
              - email
    Returns
    ---------
        A user dict with matching name or email or None if no matching user was found
    """
    for user in user_list:
        # Search by name or mail address
        if name_or_email in (user['name'], user['email']):
            return user
    return None

def write_yaml(data, file: str):
    """ write yaml into a file """
    with open(file, 'w', encoding="utf-8") as f:
        yaml.dump(data, f)

def read_yaml(file: str,max_age_min=60):
    """ read yaml data """
    if os.path.exists(file):
        file_age = datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(file))
        if file_age.total_seconds() > max_age_min*60:
            return None
        with open(file, 'r', encoding='utf-8') as cache_file:
            return yaml.safe_load(cache_file)
    return None

parser = argparse.ArgumentParser(description="Create Immich Albums from an external library path based on the top level folders",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("root_path", action='append', help="The external library's root path in Immich")
parser.add_argument("api_url", help="The root API URL of immich, e.g. https://immich.mydomain.com/api/")
parser.add_argument("api_key", help="The Immich API Key to use. Set --api-key-type to 'file' if a file path is provided.")
parser.add_argument("-t", "--api-key-type", default="literal", choices=['literal', 'file'], help="The type of the Immich API Key")
parser.add_argument("-r", "--root-path", action="append",
                    help="Additional external library root path in Immich; May be specified multiple times for multiple import paths or external libraries.")
parser.add_argument("-u", "--unattended", action="store_true", help="Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob.")
parser.add_argument("-a", "--album-levels", default="1", type=str,
                    help="""Number of sub-folders or range of sub-folder levels below the root path used for album name creation.
                            Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be 0.
                            If a range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'.
                            If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>.""")
parser.add_argument("-s", "--album-separator", default=" ", type=str,
                    help="Separator string to use for compound album names created from nested folders. Only effective if -a is set to a value > 1")
parser.add_argument("-R", "--album-name-post-regex", nargs='+',
        action='append',
        metavar=('PATTERN', 'REPL'),
        help='Regex pattern and optional replacement (use "" for empty replacement). Can be specified multiple times.')
parser.add_argument("-c", "--chunk-size", default=2000, type=int, help="Maximum number of assets to add to an album with a single API call")
parser.add_argument("-C", "--fetch-chunk-size", default=5000, type=int, help="Maximum number of assets to fetch with a single API call")
parser.add_argument("-l", "--log-level", default="INFO", choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'], help="Log level to use")
parser.add_argument("-k", "--insecure", action="store_true", help="Pass to ignore SSL verification")
parser.add_argument("-i", "--ignore", action="append",
                    help="""Use either literals or glob-like patterns to ignore assets for album name creation.
                            This filter is evaluated after any values passed with --path-filter. May be specified multiple times.""")
parser.add_argument("-m", "--mode", default=SCRIPT_MODE_CREATE, choices=[SCRIPT_MODE_CREATE, SCRIPT_MODE_CLEANUP, SCRIPT_MODE_DELETE_ALL],
                    help="""Mode for the script to run with.
                            CREATE = Create albums based on folder names and provided arguments;
                            CLEANUP = Create album names based on current images and script arguments, but delete albums if they exist;
                            DELETE_ALL = Delete all albums.
                            If the mode is anything but CREATE, --unattended does not have any effect.
                            Only performs deletion if -d/--delete-confirm option is set, otherwise only performs a dry-run.""")
parser.add_argument("-d", "--delete-confirm", action="store_true",
                    help="""Confirm deletion of albums when running in mode """+SCRIPT_MODE_CLEANUP+""" or """+SCRIPT_MODE_DELETE_ALL+""".
                            If this flag is not set, these modes will perform a dry run only. Has no effect in mode """+SCRIPT_MODE_CREATE)
parser.add_argument("-x", "--share-with", action="append",
                    help="""A user name (or email address of an existing user) to share newly created albums with.
                    Sharing only happens if the album was actually created, not if new assets were added to an existing album.
                    If the the share role should be specified by user, the format <userName>=<shareRole> must be used, where <shareRole> must be one of 'viewer' or 'editor'.
                    May be specified multiple times to share albums with more than one user.""")
parser.add_argument("-o", "--share-role", default="viewer", choices=['viewer', 'editor'],
                    help="""The default share role for users newly created albums are shared with.
                            Only effective if --share-with is specified at least once and the share role is not specified within --share-with.""")
parser.add_argument("-S", "--sync-mode", default=0, type=int, choices=[0, 1, 2],
                    help="""Synchronization mode to use. Synchronization mode helps synchronizing changes in external libraries structures to Immich after albums
                            have already been created. Possible Modes: 0 = do nothing; 1 = Delete any empty albums; 2 = Delete offline assets AND any empty albums""")
parser.add_argument("-O", "--album-order", default=False, type=str, choices=[False, 'asc', 'desc'],
                    help="Set sorting order for newly created albums to newest or oldest file first, Immich defaults to newest file first")
parser.add_argument("-A", "--find-assets-in-albums", action="store_true",
                    help="""By default, the script only finds assets that are not assigned to any album yet.
                            Set this option to make the script discover assets that are already part of an album and handle them as usual.
                            If --find-archived-assets is set as well, both options apply.""")
parser.add_argument("-f", "--path-filter", action="append",
                    help="""Use either literals or glob-like patterns to filter assets before album name creation.
                            This filter is evaluated before any values passed with --ignore. May be specified multiple times.""")
parser.add_argument("--set-album-thumbnail", choices=ALBUM_THUMBNAIL_SETTINGS_GLOBAL,
                    help="""Set first/last/random image as thumbnail for newly created albums or albums assets have been added to.
                            If set to """+ALBUM_THUMBNAIL_RANDOM_FILTERED+""", thumbnails are shuffled for all albums whose assets would not be
                            filtered out or ignored by the ignore or path-filter options, even if no assets were added during the run.
                            If set to """+ALBUM_THUMBNAIL_RANDOM_ALL+""", the thumbnails for ALL albums will be shuffled on every run.""")
# Backward compatibility, remove when archive is removed
parser.add_argument("-v", "--archive", action="store_true",
                    help="""DEPRECATED. Use --visibility=archive instead! This option will be removed in the future!
                            Set this option to automatically archive all assets that were newly added to albums.
                            If this option is set in combination with --mode = CLEANUP or DELETE_ALL, archived images of deleted albums will be unarchived.
                            Archiving hides the assets from Immich's timeline.""")
# End Backward compaibility
parser.add_argument("--visibility", choices=['archive', 'hidden', 'locked', 'timeline'],
                    help="""Set this option to automatically set the visibility of all assets that are discovered by the script and assigned to albums.
                            Exception for value 'locked': Assets will not be added to any albums, but to the 'locked' folder only.
                            Also applies if -m/--mode is set to CLEAN_UP or DELETE_ALL; then it affects all assets in the deleted albums.
                            Always overrides -v/--archive.""")
parser.add_argument("--find-archived-assets", action="store_true",
                    help="""By default, the script only finds assets with visibility set to 'timeline' (which is the default).
                            Set this option to make the script discover assets with visibility 'archive' as well.
                            If -A/--find-assets-in-albums is set as well, both options apply.""")
parser.add_argument("--read-album-properties", action="store_true",
                    help="""If set, the script tries to access all passed root paths and recursively search for .albumprops files in all contained folders.
                            These properties will be used to set custom options on an per-album level. Check the readme for a complete documentation.""")
parser.add_argument("--api-timeout",  default=REQUEST_TIMEOUT_DEFAULT, type=int, help="Timeout when requesting Immich API in seconds")
parser.add_argument("--comments-and-likes-enabled", action="store_true",
                    help="Pass this argument to enable comment and like functionality in all albums this script adds assets to. Cannot be used together with --comments-and-likes-disabled")
parser.add_argument("--comments-and-likes-disabled", action="store_true",
                    help="Pass this argument to disable comment and like functionality in all albums this script adds assets to. Cannot be used together with --comments-and-likes-enabled")
parser.add_argument("--update-album-props-mode", type=int, choices=[0, 1, 2], default=0,
                    help="""Change how album properties are updated whenever new assets are added to an album. Album properties can either come from script arguments or the .albumprops file.
                            Possible values:
                            0 = Do not change album properties.
                            1 = Only override album properties but do not change the share status.
                            2 = Override album properties and share status, this will remove all users from the album which are not in the SHARE_WITH list.""")
parser.add_argument("--dont-merge-folder", action="store_true",
                    help="If set, multiple albums with the same name will be created for different folders.")


args = vars(parser.parse_args())
# set up logger to log in logfmt format
logging.basicConfig(level=args["log_level"], stream=sys.stdout, format='time=%(asctime)s level=%(levelname)s msg=%(message)s')
logging.Formatter.formatTime = (lambda self, record, datefmt=None: datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).astimezone().isoformat(sep="T",timespec="milliseconds"))

root_paths = args["root_path"]
root_url = args["api_url"]
api_key = determine_api_key(args["api_key"], args["api_key_type"])
if api_key is None:
    logging.fatal("Unable to determine API key with API Key type %s", args["api_key_type"])
    sys.exit(1)
number_of_images_per_request = args["chunk_size"]
number_of_assets_to_fetch_per_request = args["fetch_chunk_size"]
unattended = args["unattended"]
album_levels = args["album_levels"]
# Album Levels Range handling
album_levels_range_arr = ()
album_level_separator = args["album_separator"]
album_name_post_regex = args["album_name_post_regex"]
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
visibility = args["visibility"]
find_archived_assets = args["find_archived_assets"]
read_album_properties = args["read_album_properties"]
api_timeout = args["api_timeout"]
comments_and_likes_enabled = args["comments_and_likes_enabled"]
comments_and_likes_disabled = args["comments_and_likes_disabled"]
if comments_and_likes_disabled and comments_and_likes_enabled:
    logging.fatal("Arguments --comments-and-likes-enabled and --comments-and-likes-disabled cannot be used together! Choose one!")
    sys.exit(1)
update_album_props_mode = args["update_album_props_mode"]
merge_folder = not args["dont_merge_folder"] #invert non breaking default is to merge folders

if mode != SCRIPT_MODE_CREATE:
    # Override unattended if we're running in destructive mode
    # pylint: disable=C0103
    unattended = False

# Backward compatibility, remove when archive is removed
if visibility is None and archive:
    # pylint: disable=C0103
    visibility = 'archive'
    logging.warning('-v/--archive is DEPRECATED! Use --visibility=archive instead! This option will be removed in the future!')
# End Backward compaibility

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
logging.debug("album_name_post_regex= %s", album_name_post_regex)
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
# Backward compatibility, remove when archive is removed
logging.debug("archive = %s", archive)
# End Backward compaibility
logging.debug("visibility = %s", visibility)
logging.debug("find_archived_assets = %s", find_archived_assets)
logging.debug("read_album_properties = %s", read_album_properties)
logging.debug("api_timeout = %s", api_timeout)
logging.debug("comments_and_likes_enabled = %s", comments_and_likes_enabled)
logging.debug("comments_and_likes_disabled = %s", comments_and_likes_disabled)
logging.debug("update_album_props_mode = %d", update_album_props_mode)
logging.debug("merge_folder = %d", merge_folder)

# Verify album levels
if is_integer(album_levels) and album_levels == 0:
    parser.print_help()
    sys.exit(1)

# Request arguments for API calls
requests_kwargs = {
    'headers' : {
        'x-api-key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    },
    'verify' : not insecure
}

if insecure:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Verify album levels range
if not is_integer(album_levels):
    album_levels_range_split = album_levels.split(",")
    if any([
            len(album_levels_range_split) != 2,
            not is_integer(album_levels_range_split[0]),
            not is_integer(album_levels_range_split[1]),
            int(album_levels_range_split[0]) == 0,
            int(album_levels_range_split[1]) == 0,
            (int(album_levels_range_split[1]) < 0 <= int(album_levels_range_split[0])),
            (int(album_levels_range_split[0]) < 0 <= int(album_levels_range_split[1])),
            (int(album_levels_range_split[0]) < 0 and int(album_levels_range_split[1]) < 0 and int(album_levels_range_split[0]) > int(album_levels_range_split[1]))
        ]):
        logging.error(("Invalid album_levels range format! If a range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'. "
                      "If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>."))
        sys.exit(1)
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
# pylint: disable=C0200
for i in range(len(root_paths)):
    if root_paths[i][-1] != '/':
        root_paths[i] = root_paths[i] + '/'
# append trailing slash to root URL
if root_url[-1] != '/':
    root_url = root_url + '/'

version = fetch_server_version()
# Check version
if version['major'] == 1 and version ['minor'] < 106:
    logging.fatal("This script only works with Immich Server v1.106.0 and newer! Update Immich Server or use script version 0.8.1!")
    sys.exit(1)

# Special case: Run Mode DELETE_ALL albums
if mode == SCRIPT_MODE_DELETE_ALL:
    delete_all_albums(visibility, delete_confirm)
    sys.exit(0)

album_properties_templates = {}
if read_album_properties:
    logging.debug("Albumprops: Finding, parsing and merging %s files", ALBUMPROPS_FILE_NAME)
    album_properties_templates = build_album_properties_templates()
    for album_properties_path, album_properties_template in album_properties_templates.items():
        logging.debug("Albumprops: %s -> %s", album_properties_path, album_properties_template)

logging.info("Requesting all assets")
# only request images that are not in any album if we are running in CREATE mode,
# otherwise we need all images, even if they are part of an album
if mode == SCRIPT_MODE_CREATE:
    assets = fetch_assets(not find_assets_in_albums, ['archive'] if find_archived_assets else [])
else:
    assets = fetch_assets(False, ['archive'])
if assets := read_yaml('.assets_cache.yaml'):
    logging.info("Loaded Assets %s from cache", len(assets))
else:
    logging.info("Requesting all assets")
    # only request images that are not in any album if we are running in CREATE mode,
    # otherwise we need all images, even if they are part of an album
    if mode == SCRIPT_MODE_CREATE:
        assets = fetch_assets(not find_assets_in_albums, ['archive'] if find_archived_assets else [])
    else:
        assets = fetch_assets(False, ['archive'])

    # Remove live photo video components
    assets = check_for_and_remove_live_photo_video_components(assets, not find_assets_in_albums, find_archived_assets)
    write_yaml(assets, '.assets_cache.yaml')
logging.info("%d photos found", len(assets))



logging.info("Sorting assets to corresponding albums using folder name")
albums_to_create = build_album_list(assets, root_paths, album_properties_templates)

if version['major'] == 1 and version ['minor'] < 133:
    albums_with_visibility = [album_check_to_check for album_check_to_check in albums_to_create
                              if album_check_to_check.visibility is not None and album_check_to_check.visibility != 'archive']
    if len(albums_with_visibility) > 0:
        logging.warning("Option 'visibility' is only supported in Immich Server v1.133.x and newer! Option will be ignored!")

logging.info("%d albums identified", len(albums_to_create))
for album in albums_to_create:
    logging.info(" - Album %s, Assets %i, Paths %s", album.name, len(album.assets),list(album.album_paths))


if not unattended and mode == SCRIPT_MODE_CREATE:
    if is_docker:
        print("Check that this is the list of albums you want to create. Run the container with environment variable UNATTENDED set to 1 to actually create these albums.")
        sys.exit(0)
    else:
        print("Press enter to create these albums, Ctrl+C to abort")
        input()

logging.info("Listing existing albums on immich")

albums = fetch_albums()
logging.info("%d existing albums identified", len(albums))

for album in albums_to_create:
    # fetch the id if same album name exist, if won't merge, compare if atleast (?) one album_paths is the same
    album.id = next(
        (
            a['id'] for a in albums if album.name == a['albumName'] and (merge_folder or any(path in a['album_paths'] for path in album.album_paths))),
        None)

# mode CLEANUP
if mode == SCRIPT_MODE_CLEANUP:
    # Filter list of albums to create for existing albums only
    albums_to_cleanup = {}
    for album in albums_to_create:
        # Only cleanup existing albums (has id set) and no duplicates (due to override_name)
        if album.id and album.id not in albums_to_cleanup:
            albums_to_cleanup[album.id] = album
    # pylint: disable=C0103
    number_of_deleted_albums = cleanup_albums(albums_to_cleanup, delete_confirm)
    logging.info("Deleted %d/%d albums", number_of_deleted_albums, len(albums_to_cleanup))
    sys.exit(0)

# Get all users in preparation for album sharing
users = fetch_users()
logging.debug("Found users: %s", users)

# mode CREATE
logging.info("Create / Append to Albums")
created_albums = []
# List for gathering all asset UUIDs for later archiving
asset_uuids_added = []
for album in albums_to_create:
    # Special case: Add assets to Locked folder
    # Locked assets cannot be part of an album, so don't create albums in the first place
    if album.visibility == 'locked':
        set_assets_visibility(album.get_asset_uuids(), album.visibility)
        logging.info("Added %d assets to locked folder", len(album.get_asset_uuids()))
        continue

    # Create album if inexistent:
    if not album.id:
        album.id = create_album(album.get_final_name())
        created_albums.append(album)
        logging.info('Album %s added %s', album.get_final_name(),album.id)

    logging.info("Adding assets to album %s %s", album.get_final_name(), album.id)
    assets_added = add_assets_to_album(album.id, album.get_asset_uuids())
    if len(assets_added) > 0:
        asset_uuids_added += assets_added
        logging.info("%d new assets added to %s %s", len(assets_added), album.get_final_name(), album.id)

    # Set assets visibility
    if album.visibility is not None:
        set_assets_visibility(assets_added, album.visibility)
        logging.info("Set visibility for %d assets to %s", len(assets_added), album.visibility)

    # Set assets visibility
    if album.visibility is not None:
        set_assets_visibility(assets_added, album.visibility)
        logging.info("Set visibility for %d assets to %s", len(assets_added), album.visibility)

    # Update album properties depending on mode or if newly created
    if update_album_props_mode > 0 or (album in created_albums):
        # Update album properties
        try:
            update_album_properties(album)
        except HTTPError as e:
            logging.error('Error updating properties for album %s: %s', album.get_final_name(), e)

    # Update album sharing if needed or newly created
    if update_album_props_mode == 2 or (album in created_albums):
        # Handle album sharing
        update_album_shared_state(album, True)

logging.info("%d albums created", len(created_albums))

if created_albums:
    #flush cash
    write_yaml(None, '.albums_cache.yaml')

# Perform album cover randomization
if set_album_thumbnail == ALBUM_THUMBNAIL_RANDOM_ALL:
    logging.info("Picking a new random thumbnail for all albums")
    albums = fetch_albums()
    for album in albums:
        album_info = fetch_album_info(album['id'])
        # Create album model for thumbnail randomization
        album_model = AlbumModel(album['albumName'])
        album_model.id = album['id']
        album_model.assets = album_info['assets']
        # Set thumbnail setting to 'random' in model
        album_model.thumbnail_setting = 'random'
        # Update album properties (which will only pick a random thumbnail and set it, no other properties are changed)
        update_album_properties(album_model)


# Perform sync mode action: Trigger offline asset removal
if sync_mode == 2:
    logging.info("Trigger offline asset removal")
    trigger_offline_asset_removal()

# Perform sync mode action: Delete empty albums
#
# For Immich versions prior to v1.116.0:
# Attention: Since Offline Asset Removal is an asynchronous job,
# albums affected by it are most likely not empty yet! So this
# might only be effective in the next script run.
if sync_mode >= 1:
    logging.info("Deleting all empty albums")
    albums = fetch_albums()
    # pylint: disable=C0103
    empty_album_count = 0
    # pylint: disable=C0103
    cleaned_album_count = 0
    for album in albums:
        if album['assetCount'] == 0:
            empty_album_count += 1
            logging.info("Deleting empty album %s", album['albumName'])
            if delete_album(album):
                cleaned_album_count += 1
    if empty_album_count > 0:
        logging.info("Successfully deleted %d/%d empty albums!", cleaned_album_count, empty_album_count)
    else:
        logging.info("No empty albums found!")

logging.info("Done!")
