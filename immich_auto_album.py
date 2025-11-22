"""Python script for creating albums in Immich from folder names in an external library."""

# pylint: disable=too-many-lines
from __future__ import annotations
import warnings
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
import traceback

import regex
import yaml

import urllib3
import requests


# Script Constants
# Environment variable to check if the script is running inside Docker
ENV_IS_DOCKER = "IS_DOCKER"

# pylint: disable=R0902,R0904
class ApiClient:
    """Encapsulates Immich API Calls in a client object"""

    # Default value for the maximum number of assets to add to an album in a single API call
    CHUNK_SIZE_DEFAULT = 2000
    # Maximum number of assets that can be fetched in a single API call using the search endpoint
    FETCH_CHUNK_SIZE_MAX = 1000
    # Default value for the maximum number of assets to fetch in a single API call
    FETCH_CHUNK_SIZE_DEFAULT = 1000
    # Default value for API request timeout ins econds
    API_TIMEOUT_DEFAULT = 20
    # Number of times to retry an API call if it times out
    MAX_RETRY_COUNT_ON_TIMEOUT_DEFAULT = 3

    # List of allowed share user roles
    SHARE_ROLES = ["editor", "viewer"]

    def __init__(self, api_url : str, api_key : str, **kwargs: dict):
        """
        :param api_url: The Immich Server's API base URL
        :param api_key: The Immich API key to use for authentication
        :param **kwargs: keyword arguments allowing the following keywords:

                - `chunk_size: int` The number of assets to add to an album with a single API call
                - `fetch_chunk_size: int` The number of assets to fetch with a single API call
                - `api_timeout: int` The timeout to use for API calls in seconds
                - `insecure: bool` Flag indicating whether to skip SSL certificate validation
                - `max_retry_count: int` The maximum number of times to retry an API call if it timed out before failing
        :raises AssertionError: When validation of options failed
        """
        # The Immich API URL to connect to
        self.api_url = api_url
        # The API key to use
        self.api_key = api_key

        self.chunk_size : int = Utils.get_value_or_config_default('chunk_size', kwargs, Configuration.CONFIG_DEFAULTS['chunk_size'])
        self.fetch_chunk_size : int = Utils.get_value_or_config_default('fetch_chunk_size', kwargs, Configuration.CONFIG_DEFAULTS['fetch_chunk_size'])
        self.api_timeout : int = Utils.get_value_or_config_default('api_timeout', kwargs, Configuration.CONFIG_DEFAULTS['api_timeout'])
        self.insecure : bool = Utils.get_value_or_config_default('insecure', kwargs, Configuration.CONFIG_DEFAULTS['insecure'])
        self.max_retry_count : int = Utils.get_value_or_config_default('max_retry_count', kwargs, Configuration.CONFIG_DEFAULTS['max_retry_count'])

        self.__validate_config()

        # Build request arguments to use for API calls
        self.request_args = {
            'headers' : {
                'x-api-key': self.api_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            'verify' : not self.insecure
        }

        if self.insecure:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        else:
            warnings.resetwarnings()

        self.server_version = self.__fetch_server_version_safe()
        if self.server_version is None:
            raise AssertionError("Communication with Immich Server API failed! Make sure the API URL is correct and verify the API Key!")

        # Check version
        if self.server_version ['major'] == 1 and self.server_version  ['minor'] < 106:
            raise AssertionError("This script only works with Immich Server v1.106.0 and newer! Update Immich Server or use script version 0.8.1!")

    def __validate_config(self):
        """
        Validates all set configuration values.

        :raises: ValueError if any config value does not pass validation
        """
        Utils.assert_not_none_or_empty("api_url", self.api_url)
        Utils.assert_not_none_or_empty("api_key", self.api_key)
        Utils.assert_not_none_or_empty("chunk_size", self.chunk_size)
        Utils.assert_not_none_or_empty("fetch_chunk_size", self.fetch_chunk_size)
        Utils.assert_not_none_or_empty("api_timeout", self.api_timeout)
        Utils.assert_not_none_or_empty("insecure", self.insecure)

        if not Utils.is_integer(self.chunk_size) or self.chunk_size < 1:
            raise ValueError("chunk_size must be an integer > 0!")

        if not Utils.is_integer(self.fetch_chunk_size) or self.fetch_chunk_size < 1:
            raise ValueError("fetch_chunk_size must be an integer > 0!")

        if not Utils.is_integer(self.api_timeout) or self.api_timeout < 1:
            raise ValueError("api_timeout must be an integer > 0!")

        try:
            bool(self.insecure)
        except ValueError as e:
            raise ValueError("insecure argument must be a boolean!") from e

    def __request_api(self, http_method: str, endpoint: str, body: any = None, no_retries: bool = False) -> any:
        """
        Performs an HTTP request using `http_method` to `endpoint`, sending headers `self.request_args` and `body` as payload.  
        Uses `self.api_timeout` as a timeout and respects `self.max_retry_count` on timeout if `not_retries` is not `True`. 
        If the HTTP request fails for any other reason than a timeout, no retries are performed.

        :param http_method: The HTTP method to send the request with, must be one of `GET`, `POST`, `PUT`, `DELETE`, `HEAD`, `CONNECT`, `OPTIONS`, `TRACE` or `PATCH`.
        :param endpoint: The URL to request
        :param body: The request body to send. Defaults to an empty dict.
        :param no_retries: Flag indicating whether to fail immediately on request timeout

        :returns: The HTTP response
        :raises: HTTPError if the request failed (timeouts only if occurred too many times)
        """

        http_method_function = getattr(requests, http_method)
        assert http_method_function is not None

        if body is None:
            body = {}
        number_of_retries : int = 0
        ex = None
        while number_of_retries == 0 or ( not no_retries and number_of_retries <= self.max_retry_count ):
            try:
                return http_method_function(endpoint, **self.request_args, json=body , timeout=self.api_timeout)
            except (requests.exceptions.Timeout, urllib3.exceptions.ReadTimeoutError, requests.exceptions.ConnectionError) as e:
                # either not a ConnectionError or a ConectionError caused by ReadTimeoutError
                if not isinstance(e, requests.exceptions.ConnectionError) or (len(e.args) > 0 and isinstance(e.args[0], urllib3.exceptions.ReadTimeoutError)):
                    ex = e
                    number_of_retries += 1
                    if number_of_retries > self.max_retry_count:
                        raise e
                    logging.warning("Request to %s timed out, retry %s...", endpoint, number_of_retries)
                else:
                    raise e
        # this point should not be reached
        raise ex

    @staticmethod
    def __check_api_response(response: requests.Response) -> None:
        """
        Checks the HTTP return code for the provided response and
        logs any errors before raising an HTTPError

        :param response: A list of asset IDs to archive
        :raises: HTTPError if the API call fails
        """
        try:
            response.raise_for_status()
        except HTTPError:
            if response.json():
                logging.error("Error in API call: %s", response.json())
            else:
                logging.error("API response did not contain a payload")
        response.raise_for_status()

    def fetch_server_version(self) -> dict:
        """
        Fetches the API version from the immich server.

        If the API endpoint for getting the server version cannot be reached,
        raises HTTPError

        :returns: Dictionary with keys `major`, `minor`, `patch`
        :rtype: dict
        :raises ConnectionError: If the connection to the API server cannot be establisehd
        :raises JSONDecodeError: If the API response cannot be parsed
        :raises ValueError: If the API response is malformed
        """
        api_endpoint = f'{self.api_url}server/version'
        r = self.__request_api('get', api_endpoint, self.request_args)
        # The API endpoint changed in Immich v1.118.0, if the new endpoint
        # was not found try the legacy one
        if r.status_code == 404:
            api_endpoint = f'{self.api_url}server-info/version'
            r = self.__request_api('get', api_endpoint, self.request_args)

        if r.status_code == 200:
            server_version = r.json()
            try:
                assert server_version['major'] is not None
                assert server_version['minor'] is not None
                assert server_version['patch'] is not None
            except AssertionError as e:
                raise ValueError from e
            logging.info("Detected Immich server version %s.%s.%s", server_version['major'], server_version['minor'], server_version['patch'])
            return server_version
        return None

    # pylint: disable=W0718
    # Catching too general exception Exception (broad-exception-caught
    # That's the whole point of this method
    def __fetch_server_version_safe(self) -> dict:
        """
        Fetches the API version from the Immich server, suppressing any raised errors.
        On error, an error message is getting logged to ERRRO level, and the exception stacktrace
        is logged to DEBUG level.

        :returns: Dictionary with keys `major`, `minor`, `patch` or None in case of an error
        :rtype: dict
        """
        try:
            return self.fetch_server_version()
        except Exception:
            # JSONDecodeError happens if the URL is valid, but does not return valid JSON
            # Anything below this line is deemed an error
            logging.debug("Error requesting server version!")
            logging.debug(traceback.format_exc())
        return None


    def fetch_assets(self, is_not_in_album: bool, visibility_options: list[str]) -> list[dict]:
        """
        Fetches assets from the Immich API.

        Uses the /search/meta-data call. Much more efficient than the legacy method
        since this call allows to filter for assets that are not in an album only.

        :param is_not_in_album: Flag indicating whether to fetch only assets that are not part
                of an album or not. If set to False, will find images in albums and not part of albums
        :param visibility_options: A list of visibility options to find and return assets with
        :returns: An array of asset objects
        :rtype: list[dict]
        """
        if self.server_version['major'] == 1 and self.server_version['minor'] < 133:
            return self.fetch_assets_with_options({'isNotInAlbum': is_not_in_album, 'withArchived': 'archive' in visibility_options})

        asset_list = self.fetch_assets_with_options({'isNotInAlbum': is_not_in_album})
        for visiblity_option in visibility_options:
            # Do not fetch agin for 'timeline', that's the default!
            if visiblity_option != 'timeline':
                asset_list += self.fetch_assets_with_options({'isNotInAlbum': is_not_in_album, 'visibility': visiblity_option})
        return asset_list

    def fetch_assets_with_options(self, search_options: dict[str]) -> list[dict]:
        """
        Fetches assets from the Immich API using specific search options.
        The search options directly correspond to the body used for the search API request.

        :param search_options: Dictionary containing options to pass to the search/metadata API endpoint
        :returns: An array of asset objects
        :rtype: list[dict]
        """
        body = search_options
        assets_found = []
        # prepare request body

        # This API call allows a maximum page size of 1000
        number_of_assets_to_fetch_per_request_search = min(1000, self.fetch_chunk_size)
        body['size'] = number_of_assets_to_fetch_per_request_search
        # Initial API call, let's fetch our first chunk
        page = 1
        body['page'] = str(page)
        r = self.__request_api('post', self.api_url+'search/metadata', body)
        r.raise_for_status()
        response_json = r.json()
        assets_received = response_json['assets']['items']
        logging.debug("Received %s assets with chunk %s", len(assets_received), page)

        assets_found = assets_found + assets_received
        # If we got a full chunk size back, let's perform subsequent calls until we get less than a full chunk size
        while len(assets_received) == number_of_assets_to_fetch_per_request_search:
            page += 1
            body['page'] = page
            r = self.__request_api('post', self.api_url+'search/metadata', body)
            self.__check_api_response(r)
            response_json = r.json()
            assets_received = response_json['assets']['items']
            logging.debug("Received %s assets with chunk %s", len(assets_received), page)
            assets_found = assets_found + assets_received
        return assets_found

    def fetch_albums(self) -> list[dict]:
        """
        Fetches albums from the Immich API
        
        :returns: A list of album objects
        :rtype: list[dict]
        """

        api_endpoint = 'albums'

        r = self.__request_api('get', self.api_url+api_endpoint)
        self.__check_api_response(r)
        return r.json()

    def fetch_album_info(self, album_id_for_info: str) -> dict:
        """
        Fetches information about a specific album

        :param album_id_for_info: The ID of the album to fetch information for
        
        :returns: A dict containing album information
        :rtype: dict
        """

        api_endpoint = f'albums/{album_id_for_info}'

        r = self.__request_api('get', self.api_url+api_endpoint)
        self.__check_api_response(r)
        return r.json()

    def delete_album(self, album_delete: dict) -> bool:
        """
        Deletes an album identified by album_to_delete['id']

        If the album could not be deleted, logs an error.

        :param album_delete: Dictionary with the following keys: `id`, `albumName`

        :returns: True if the album was deleted, otherwise False
        :rtype: bool
        """
        api_endpoint = 'albums'

        logging.debug("Deleting Album: Album ID = %s, Album Name = %s", album_delete['id'], album_delete['albumName'])
        r = self.__request_api('delete', self.api_url+api_endpoint+'/'+album_delete['id'])
        try:
            self.__check_api_response(r)
            return True
        except HTTPError:
            logging.error("Error deleting album %s: %s", album_delete['albumName'], r.reason)
            return False

    def create_album(self, album_name_to_create: str) -> str:
        """
        Creates an album with the provided name and returns the ID of the created album


        :param album_name_to_create: Name of the album to create

        :returns: True if the album was deleted, otherwise False
        :rtype: str
        
        :raises: Exception if the API call failed
        """

        api_endpoint = 'albums'

        data = {
            'albumName': album_name_to_create
        }
        r = self.__request_api('post', self.api_url+api_endpoint, data)
        self.__check_api_response(r)

        return r.json()['id']

    def add_assets_to_album(self, assets_add_album_id: str, asset_list: list[str]) -> list[str]:
        """
        Adds the assets IDs provided in assets to the provided albumId.

        If assets if larger than self.chunk_size, the list is chunked
        and one API call is performed per chunk.
        Only logs errors and successes.

        Returns

        :param assets_add_album_id: The ID of the album to add assets to
        :param asset_list: A list of asset IDs to add to the album

        :returns: The asset UUIDs that were actually added to the album (not respecting assets that were already part of the album)
        :rtype: list[str]
        """
        api_endpoint = 'albums'

        # Divide our assets into chunks of self.chunk_size,
        # So the API can cope
        assets_chunked = list(Utils.divide_chunks(asset_list, self.chunk_size))
        asset_list_added = []

        for assets_chunk in assets_chunked:
            data = {'ids':assets_chunk}
            r = self.__request_api('put', self.api_url+api_endpoint+f'/{assets_add_album_id}/assets', data)
            self.__check_api_response(r)
            response = r.json()

            for res in response:
                if not res['success']:
                    if  res['error'] != 'duplicate':
                        logging.warning("Error adding an asset to an album: %s", res['error'])
                else:
                    asset_list_added.append(res['id'])

        return asset_list_added

    def fetch_users(self) -> list[dict]:
        """
        Queries and returns all users
        
        :returns: A list of user objects
        :rtype: list[dict]
        """

        api_endpoint = 'users'

        r = self.__request_api('get', self.api_url+api_endpoint)
        self.__check_api_response(r)
        return r.json()

    def unshare_album_with_user(self, album_id_to_unshare: str, unshare_user_id: str) -> None:
        """
        Unshares the provided album with the provided user

        :param album_id_to_unshare: The ID of the album to unshare
        :param unshare_user_id: The user ID to remove from the album's share list
        
        :raises: HTTPError if the API call fails
        """
        api_endpoint = f'albums/{album_id_to_unshare}/user/{unshare_user_id}'
        r = self.__request_api('delete', self.api_url+api_endpoint)
        self.__check_api_response(r)

    def update_album_share_user_role(self, album_id_to_share: str, share_user_id: str, share_user_role: str) -> None:
        """
        Updates the user's share role for the provided album ID.

        :param album_id_to_share: The ID of the album to share
        :param share_user_id: The user ID to update the share role for
        :param share_user_role: The share role to update the user to
        
        :raises: AssertionError if user_share_role contains an invalid value
        :raises: HTTPError if the API call fails
        """
        api_endpoint = f'albums/{album_id_to_share}/user/{share_user_id}'

        assert share_user_role in ApiClient.SHARE_ROLES

        data = {
            'role': share_user_role
        }

        r = self.__request_api('put', self.api_url+api_endpoint, data)
        self.__check_api_response(r)

    def share_album_with_user_and_role(self, album_id_to_share: str, user_ids_to_share_with: list[str], user_share_role: str) -> None:
        """
        Shares the album with the provided album_id with all provided share_user_ids
        using share_role as a role.

        :param album_id_to_share: The ID of the album to share
        :param user_ids_to_share_with: IDs of users to share the album with
        :param user_share_role: The share role to use when sharing the album, valid values are `viewer` or `editor`
        :raises: AssertionError if user_share_role contains an invalid value
        :raises: HTTPError if the API call fails
        """
        api_endpoint = f'albums/{album_id_to_share}/users'

        assert user_share_role in ApiClient.SHARE_ROLES

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

        r = self.__request_api('put', self.api_url+api_endpoint, data)
        self.__check_api_response(r)

    def trigger_offline_asset_removal(self) -> None:
        """
        Removes offline assets.

        Takes into account API changes happening between v1.115.0 and v1.116.0.

        Before v1.116.0, offline asset removal was an asynchronous job that could only be
        triggered by an Administrator for a specific library.

        Since v1.116.0, offline assets are no longer displayed in the main timeline but shown in the trash. They automatically
        come back from the trash when they are no longer offline. The only way to delete them is either by emptying the trash
        (along with everything else) or by selectively deleting all offline assets. This is option the script now uses.

        :raises: HTTPException if any API call fails
        """
        if self.server_version['major'] == 1 and self.server_version['minor'] < 116:
            self.__trigger_offline_asset_removal_pre_minor_version_116()
        else:
            self.__trigger_offline_asset_removal_since_minor_version_116()

    def __trigger_offline_asset_removal_since_minor_version_116(self) -> None:
        """
        Synchronously deletes offline assets.

        Uses the searchMetadata endpoint to find all assets marked as offline, then
        issues a delete call for these asset UUIDs.

        :raises: HTTPException if any API call fails
        """
        # Workaround for a bug where isOffline option is not respected:
        # Search all trashed assets and manually filter for offline assets.
        # WARNING! This workaround must NOT be removed to keep compatibility with Immich v1.116.x to at
        # least v1.117.x (reported issue for v1.117.0, might be fixed with v1.118.0)!
        # If removed the assets for users of v1.116.0 - v1.117.x might be deleted completely!!!
        # 2024/03/01: With Immich v1.128.0 isOffline filter is fixed. Remember to also request archived assets.
        trashed_assets = self.fetch_assets_with_options({'isTrashed': True, 'isOffline': True, 'withArchived': True})
        #logging.debug("search results: %s", offline_assets)

        offline_assets = [asset for asset in trashed_assets if asset['isOffline']]

        if len(offline_assets) > 0:
            logging.info("Deleting %s offline assets", len(offline_assets))
            logging.debug("Deleting the following offline assets (count: %d): %s", len(offline_assets), [asset['originalPath'] for asset in offline_assets])
            self.delete_assets(offline_assets, True)
        else:
            logging.info("No offline assets found!")

    def __trigger_offline_asset_removal_pre_minor_version_116(self):
        """
        Triggers Offline Asset Removal Job.
        Only supported in Immich prior v1.116.0.
        Requires the script to run with an Administrator level API key.

        Works by fetching all libraries and triggering the Offline Asset Removal job
        one by one.

        :raises: HTTPError if the API call fails
        """
        libraries = self.fetch_libraries()
        for library in libraries:
            self.__trigger_offline_asset_removal_async(library['id'])

    def delete_assets(self, assets_to_delete: list, force: bool):
        """
        Deletes the provided assets from Immich.

        :param assets_to_delete: A list of asset objects with key `id`
        :param force: Force flag to pass to the API call

        :raises: HTTPException if the API call fails
        """

        api_endpoint = 'assets'
        asset_ids_to_delete = [asset['id'] for asset in assets_to_delete]
        data = {
            'force': force,
            'ids': asset_ids_to_delete
        }

        r = self.__request_api('delete', self.api_url+api_endpoint, data)
        self.__check_api_response(r)

    def __trigger_offline_asset_removal_async(self, library_id: str):
        """
        Triggers removal of offline assets in the library identified by libraryId.

        :param library_id: The ID of the library to trigger offline asset removal for
        :raises: Exception if any API call fails
        """

        api_endpoint = f'libraries/{library_id}/removeOffline'

        r = self.__request_api('post', self.api_url+api_endpoint)
        if r.status_code == 403:
            logging.fatal("--sync-mode 2 requires an Admin User API key!")
        else:
            self.__check_api_response(r)

    def fetch_libraries(self) -> list[dict]:
        """
        Queries and returns all libraries

        :raises: Exception if any API call fails
        """

        api_endpoint = 'libraries'

        r = self.__request_api('get', self.api_url+api_endpoint)
        self.__check_api_response(r)
        return r.json()

    def set_album_thumb(self, thumbnail_album_id: str, thumbnail_asset_id: str):
        """
        Sets asset as thumbnail of album

        :param thumbnail_album_id: The ID of the album for which to set the thumbnail
        :param thumbnail_asset_id: The ID of the asset to be set as thumbnail

        :raises: Exception if the API call fails
        """
        api_endpoint = f'albums/{thumbnail_album_id}'

        data = {"albumThumbnailAssetId": thumbnail_asset_id}

        r = self.__request_api('patch', self.api_url+api_endpoint, data)
        self.__check_api_response(r)

    def update_album_properties(self, album_to_update: AlbumModel):
        """
        Sets album properties in Immich to the properties of the AlbumModel

        :param album_to_update: The album model to use for updating the album

        :raises: Exception if the API call fails
        """
        # Initialize payload
        data = {}

        # Thumbnail Asset
        if album_to_update.thumbnail_asset_uuid:
            data['albumThumbnailAssetId'] = album_to_update.thumbnail_asset_uuid

        # Description
        if album_to_update.description:
            data['description'] = album_to_update.description

        # Sorting Order
        if album_to_update.sort_order:
            data['order'] = album_to_update.sort_order

        # Comments / Likes enabled
        if album_to_update.comments_and_likes_enabled is not None:
            data['isActivityEnabled'] = album_to_update.comments_and_likes_enabled

        # Only update album if there is something to update
        if len(data) > 0:
            api_endpoint = f'albums/{album_to_update.id}'

            response = self.__request_api('patch',self.api_url+api_endpoint, data)
            self.__check_api_response(response)

    def set_assets_visibility(self, asset_ids_for_visibility: list[str], visibility_setting: str):
        """
        Sets the visibility of assets identified by the passed list of UUIDs.

        :param asset_ids_for_visibility: A list of asset IDs to set visibility for
        :param visibility: The visibility to set

        :raises: Exception if the API call fails
        """
        api_endpoint = 'assets'
        data = {"ids": asset_ids_for_visibility}
        # Remove when minimum supported version is >= 133
        if self.server_version['major'] == 1 and self.server_version ['minor'] < 133:
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

        r = self.__request_api('put', self.api_url+api_endpoint, data)
        self.__check_api_response(r)

    def delete_all_albums(self, assets_visibility: str, force_delete: bool):
        """
        Deletes all albums in Immich if force_delete is True. Otherwise lists all albums
        that would be deleted.
        If assets_visibility is set, all assets in deleted albums
        will be set to that visibility.

        :param assets_visibility: Flag indicating whether to unarchive archived assets
        :param force_delete: Flag indicating whether to actually delete albums (True) or only to perform a dry-run (False)

        :raises: HTTPError if the API call fails
        """

        all_albums = self.fetch_albums()
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
            if self.delete_album(album_to_delete):
                # If the archived flag is set it means we need to unarchived all images of deleted albums;
                # In order to do so, we need to fetch all assets of the album we're going to delete
                assets_in_deleted_album = []
                if assets_visibility is not None:
                    album_to_delete_info = self.fetch_album_info(album_to_delete['id'])
                    assets_in_deleted_album = album_to_delete_info['assets']
                logging.info("Deleted album %s", album_to_delete['albumName'])
                deleted_album_count += 1
                if len(assets_in_deleted_album) > 0 and assets_visibility is not None:
                    self.set_assets_visibility([asset['id'] for asset in assets_in_deleted_album], assets_visibility)
                    logging.info("Set visibility for %d assets to %s", len(assets_in_deleted_album), assets_visibility)
        logging.info("Deleted %d/%d albums", deleted_album_count, len(all_albums))

    def cleanup_albums(self, albums_to_delete: list[AlbumModel], asset_visibility: str, force_delete: bool) -> int:
        """
        Instead of creating, deletes albums in Immich if force_delete is True. Otherwise lists all albums
        that would be deleted.
        If unarchived_assets is set to true, all archived assets in deleted albums
        will be unarchived.

        :param  albums_to_delete: A list of AlbumModel records to delete
        :param asset_visibility: The visibility to set for assets for which an album was deleted. Can be used to. e.g. revert archival
        :param force_delete: Flag indicating whether to actually delete albums (True) or only to perform a dry-run (False)

        :returns: Number of successfully deleted albums
        :rtype: int

        :raises: HTTPError if the API call fails
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
            if asset_visibility is not None:
                album_to_delete_info = self.fetch_album_info(album_to_delete.id)
                assets_in_album = album_to_delete_info['assets']
            if self.delete_album({'id': album_to_delete.id, 'albumName': album_to_delete.get_final_name()}):
                logging.info("Deleted album %s", album_to_delete.get_final_name())
                cpt += 1
                # Archive flag is set, so we need to unarchive assets
                if asset_visibility is not None and len(assets_in_album) > 0:
                    self.set_assets_visibility([asset['id'] for asset in assets_in_album], asset_visibility)
                    logging.info("Set visibility for %d assets to %s", len(assets_in_album), asset_visibility)
        return cpt

    # Disable pylint for too many branches
    # pylint: disable=R0912,R0914
    def update_album_shared_state(self, album_to_share: AlbumModel, unshare_users: bool, known_users: list[dict]) -> None:
        """
        Makes sure the album is shared with the users set in the model with the correct roles.
        This involves fetching album info from Immich to check if/who the album is shared with and the share roles,
        then either updating the share role, removing the user, or adding the users

        :param album_to_share: The album to share, with the expected share_with setting
        :param unshare_users: Flag indicating whether to actively unshare albums if shared with a user that is not in the current share settings
        :param known_users: A list of all users Immich knows to find the user IDs to share/unshare with
        
        :raises: HTTPError if the API call fails
        """
        # Parse and prepare expected share roles
        # List all share users by share role
        share_users_to_roles_expected = {}
        for share_user in album_to_share.share_with:
            # Find the user by configured name or email
            share_user_in_immich = FolderAlbumCreator.find_user_by_name_or_email(share_user['user'], known_users)
            if not share_user_in_immich:
                logging.warning("User %s to share album %s with does not exist!", share_user['user'], album_to_share.get_final_name())
                continue
            # Use 'viewer' as default role if not specified
            share_role_local = share_user.get('role', 'viewer')
            share_users_to_roles_expected[share_user_in_immich['id']] = share_role_local

        # No users to share with and unsharing is disabled?
        if len(share_users_to_roles_expected) == 0 and not unshare_users:
            return

        # Now fetch reality
        album_to_share_info = self.fetch_album_info(album_to_share.id)
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
                    self.update_album_share_user_role(album_to_share.id, user_to_share_with, share_role_expected)
                    logging.debug("Sharing: Updated share role for user %s in album %s to %s", user_to_share_with, album_to_share.get_final_name(), share_role_expected)
                except HTTPError as ex:
                    logging.warning("Sharing: Error updating share role for user %s in album %s to %s", user_to_share_with, album_to_share.get_final_name(), share_role_expected)
                    logging.debug("Error: %s", ex)

        # Now check if the album is shared with any users it should not be shared with
        if unshare_users:
            for shared_user in album_share_info:
                if shared_user not in share_users_to_roles_expected:
                    try:
                        self.unshare_album_with_user(album_to_share.id, shared_user)
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
                    self.share_album_with_user_and_role(album_to_share.id, share_users, share_role_group)
                    logging.debug("Album %s shared with users IDs %s in role: %s", album_to_share.get_final_name(), share_users, share_role_group)
                except (AssertionError, HTTPError) as ex:
                    logging.warning("Error sharing album %s for users %s in role %s", album_to_share.get_final_name(), share_users, share_role_group)
                    logging.debug("Album share error: %s", ex)

class AlbumMergeError(Exception):
    """Error thrown when trying to override an existing property"""

class AlbumModelValidationError(Exception):
    """Error thrown when validating album model plausibility fails"""

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

    # List of class attribute names that are relevant for inheritance
    ALBUM_INHERITANCE_VARIABLES = ['inherit', 'inherit_properties']

    def __init__(self, name : str):
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
        self.thumbnail_asset_uuid = None
        # Sorting order for this album, 'asc' or 'desc'
        self.sort_order = None
        # Boolean indicating whether assets in this album should be archived after adding
        # Deprecated, use visibility = archive instead!
        self.archive = None
        # String indicating asset visibility, allowed values: archive, hidden, locked, timeline
        self.visibility = None
        # Boolean indicating whether assets in this albums can be commented on and liked
        self.comments_and_likes_enabled = None
        # Boolean indicating whether properties should be inherited down the directory tree
        self.inherit = None
        # List of property names that should be inherited
        self.inherit_properties = None

    def get_album_properties_dict(self) -> dict:
        """
        Returns this class' attributes relevant for album properties handling
        as a dictionary

        :returns: A dictionary of all album properties
        :rtype: dict
        """
        props = dict(vars(self))
        for prop in list(props.keys()):
            if prop not in AlbumModel.ALBUM_PROPERTIES_VARIABLES:
                del props[prop]
        return props

    def __str__(self) -> str:
        """
        Returns a string representation of this most important album properties

        :returns: A string for printing this album model's properties
        :rtype: str
        """
        return str(self.get_album_properties_dict())

    def get_asset_uuids(self) -> list[str]:
        """
        Gathers UUIDs of all assets and returns them

        :returns: A list of asset UUIDs
        :rtype: list[str]
        """
        return [asset_to_add['id'] for asset_to_add in self.assets]

    def find_incompatible_properties(self, other) -> list[str]:
        """
        Checks whether this Album Model and the other album model are compatible in terms of
        describing the same album for creation in a way that no album properties are in conflict
        with each other.
        All properties must either bei the same or not present in both objects, except for
          - `id`
          - `name`
          - `assets`

        :param other: The other album model to check against

        :returns: A list of string representations for incompatible properties. The list is empty
            if there are no incompatible properties
        :rtype: list[str]
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
          - `id`
          - `name`
          - `assets`

        :param other: The other album model to merge properties from
        :param merge_mode: Defines how the merge should be performed:

            - `AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE`: Only merge properties that are not already set in the merge target
            - `AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE_EX`: Same as above, but also raises an exception if attempting to merge an existing property
            - `AlbumModel.ALBUM_MERGE_MODE_OVERRIDE`: Overrides any existing property in merge target
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
                        raise AlbumMergeError(f"Attempting to override {prop_name} in {self.name} with {other_attribs[prop_name]}")
                    own_attribs[prop_name] = other_attribs[prop_name]

    def merge_inherited_share_with(self, inherited_share_with: list[dict]) -> list[dict]:
        """
        Merges inherited share_with settings with current share_with settings.
        Handles special share_with inheritance logic:
        - Users can be added from parent folders
        - Users can be removed by setting role to 'none' (and once removed, cannot be re-added)
        - User roles follow most restrictive policy: viewer is more restrictive than editor
        - Most restrictive role wins when there are conflicts
        
        :param inherited_share_with: List of inherited share_with settings from parent folders
        :return: Merged share_with list
        """
        if not inherited_share_with:
            return self.share_with if self.share_with else []

        if not self.share_with:
            return inherited_share_with

        # Create a dict to track users by name/email for easier manipulation
        user_roles = {}
        users_set_to_none = set()  # Track users that have been explicitly set to 'none'

        # Add inherited users first
        for inherited_user in inherited_share_with:
            if inherited_user['role'] == 'none':
                users_set_to_none.add(inherited_user['user'])
            else:
                user_roles[inherited_user['user']] = inherited_user['role']

        # Apply current folder's share_with settings
        for current_user in self.share_with:
            if current_user['role'] == 'none':
                # Remove user from sharing and mark as explicitly set to none
                user_roles.pop(current_user['user'], None)
                users_set_to_none.add(current_user['user'])
            elif current_user['user'] not in users_set_to_none:
                # Only add/modify user if they haven't been set to 'none'
                if current_user['user'] in user_roles:
                    # Apply most restrictive role: viewer is more restrictive than editor
                    current_role = user_roles[current_user['user']]
                    new_role = current_user['role']

                    if current_role == 'viewer' or new_role == 'viewer':
                        user_roles[current_user['user']] = 'viewer'
                    else:
                        user_roles[current_user['user']] = new_role
                else:
                    # Add new user with their role
                    user_roles[current_user['user']] = current_user['role']

        # Convert back to list format
        return [{'user': user, 'role': role} for user, role in user_roles.items()]

    def get_final_name(self) -> str:
        """
        Gets the album model's name to use when talking to Immich, i.e.
        returns override_name if set, otherwise name.

        :returns: override_name if set, otherwise name
        :rtype: str
        """
        if self.override_name:
            return self.override_name
        return self.name

    @staticmethod
    def parse_album_properties_file(album_properties_file_path: str):
        """
        Parses the provided album properties file into an AlbumModel

        :param album_properties_file_path: The fully qualified path to a valid album properties file

        :returns: An AlbumModel that represents the album properties
        :rtype: str

        :raises YAMLError: If the provided album properties file could not be found or parsed
        """
        with open(album_properties_file_path, 'r', encoding="utf-8") as stream:
            album_properties = yaml.safe_load(stream)
            if album_properties:
                album_props_template = AlbumModel(None)
                album_props_template_vars = vars(album_props_template)

                # Parse standard album properties
                for album_prop_name in AlbumModel.ALBUM_PROPERTIES_VARIABLES:
                    if album_prop_name in album_properties:
                        album_props_template_vars[album_prop_name] = album_properties[album_prop_name]

                # Parse inheritance properties
                for inheritance_prop_name in AlbumModel.ALBUM_INHERITANCE_VARIABLES:
                    if inheritance_prop_name in album_properties:
                        album_props_template_vars[inheritance_prop_name] = album_properties[inheritance_prop_name]

                # Backward compatibility, remove when archive is removed:
                if album_props_template.archive is not None:
                    logging.warning("Found deprecated property archive in %s! This will be removed in the future, use visibility: archive instead!", album_properties_file_path)
                    if album_props_template.visibility is None:
                        album_props_template.visibility = 'archive'
                #  End backward compatibility
                return album_props_template

        return None


class Configuration():
    """A configuration object for the main class, controlling everything from API key, root path and all the other options the script offers"""
    # Constants holding script run modes
    # Create albums based on folder names and script arguments
    SCRIPT_MODE_CREATE = "CREATE"
    # Create album names based on folder names, but delete these albums
    SCRIPT_MODE_CLEANUP = "CLEANUP"
    # Delete ALL albums
    SCRIPT_MODE_DELETE_ALL = "DELETE_ALL"

        # Constants for album thumbnail setting
    ALBUM_THUMBNAIL_RANDOM_ALL = "random-all"
    ALBUM_THUMBNAIL_RANDOM_FILTERED = "random-filtered"
    ALBUM_THUMBNAIL_SETTINGS = ["first", "last", "random"]
    ALBUM_THUMBNAIL_SETTINGS_GLOBAL = ALBUM_THUMBNAIL_SETTINGS + [ALBUM_THUMBNAIL_RANDOM_ALL, ALBUM_THUMBNAIL_RANDOM_FILTERED]
    ALBUM_THUMBNAIL_STATIC_INDICES = {
        "first": 0,
        "last": -1,
    }

    # Default values for config options that cannot be None
    CONFIG_DEFAULTS = {
        "api_key_type": "literal",
        "unattended": False,
        "album_levels": 1,
        "album_separator": " ",
        "album_order": False,
        "chunk_size": ApiClient.CHUNK_SIZE_DEFAULT,
        "fetch_chunk_size": ApiClient.FETCH_CHUNK_SIZE_DEFAULT,
        "log_level": "INFO",
        "insecure": False,
        "mode": SCRIPT_MODE_CREATE,
        "delete_confirm": False,
        "share_role": "viewer",
        "sync_mode": 0,
        "find_assets_in_albums": False,
        "find_archived_assets": False,
        "read_album_properties": False,
        "api_timeout": ApiClient.API_TIMEOUT_DEFAULT,
        "comments_and_likes_enabled": False,
        "comments_and_likes_disabled": False,
        "update_album_props_mode": 0,
        "max_retry_count": ApiClient.MAX_RETRY_COUNT_ON_TIMEOUT_DEFAULT
    }

    # Static (Global) configuration options
    log_level = CONFIG_DEFAULTS["log_level"]

    # Translation of GLOB-style patterns to Regex
    # Source: https://stackoverflow.com/a/63212852
    # FIXME_EVENTUALLY: Replace with glob.translate() introduced with Python 3.13
    __escaped_glob_tokens_to_re = OrderedDict((
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

    __escaped_glob_replacement = regex.compile('(%s)' % '|'.join(__escaped_glob_tokens_to_re).replace('\\', '\\\\\\'))

    def __init__(self,  args: dict):
        """
        Instantiates the configuration object using the provided arguments.

        :param args: A dictionary containing well-defined key-value pairs
        """
        self.root_paths = args["root_path"]
        self.root_url = args["api_url"]
        self.api_key = args["api_key"]
        self.chunk_size = Utils.get_value_or_config_default("chunk_size", args, Configuration.CONFIG_DEFAULTS["chunk_size"])
        self.fetch_chunk_size = Utils.get_value_or_config_default("fetch_chunk_size", args, Configuration.CONFIG_DEFAULTS["fetch_chunk_size"])
        self.unattended = Utils.get_value_or_config_default("unattended", args, Configuration.CONFIG_DEFAULTS["unattended"])
        self.album_levels = Utils.get_value_or_config_default("album_levels", args, Configuration.CONFIG_DEFAULTS["album_levels"])
        # Album Levels Range handling
        self.album_levels_range_arr = ()
        self.album_level_separator = Utils.get_value_or_config_default("album_separator", args, Configuration.CONFIG_DEFAULTS["album_separator"])
        self.album_name_post_regex = args["album_name_post_regex"]
        self.album_order = Utils.get_value_or_config_default("album_order", args, Configuration.CONFIG_DEFAULTS["album_order"])
        self.insecure = Utils.get_value_or_config_default("insecure", args, Configuration.CONFIG_DEFAULTS["insecure"])
        self.ignore_albums = args["ignore"]
        self.mode = Utils.get_value_or_config_default("mode", args, Configuration.CONFIG_DEFAULTS["mode"])
        self.delete_confirm = Utils.get_value_or_config_default("delete_confirm", args, Configuration.CONFIG_DEFAULTS["delete_confirm"])
        self.share_with = args["share_with"]
        self.share_role = Utils.get_value_or_config_default("share_role", args, Configuration.CONFIG_DEFAULTS["share_role"])
        self.sync_mode = Utils.get_value_or_config_default("sync_mode", args, Configuration.CONFIG_DEFAULTS["sync_mode"])
        self.find_assets_in_albums = Utils.get_value_or_config_default("find_assets_in_albums", args, Configuration.CONFIG_DEFAULTS["find_assets_in_albums"])
        self.path_filter = args["path_filter"]
        self.set_album_thumbnail = args["set_album_thumbnail"]
        self.visibility = args["visibility"]
        self.find_archived_assets = Utils.get_value_or_config_default("find_archived_assets", args, Configuration.CONFIG_DEFAULTS["find_archived_assets"])
        self.read_album_properties = Utils.get_value_or_config_default("read_album_properties", args, Configuration.CONFIG_DEFAULTS["read_album_properties"])
        self.api_timeout = Utils.get_value_or_config_default("api_timeout", args, Configuration.CONFIG_DEFAULTS["api_timeout"])
        self.comments_and_likes_enabled = Utils.get_value_or_config_default("comments_and_likes_enabled", args, Configuration.CONFIG_DEFAULTS["comments_and_likes_enabled"])
        self.comments_and_likes_disabled = Utils.get_value_or_config_default("comments_and_likes_disabled", args, Configuration.CONFIG_DEFAULTS["comments_and_likes_disabled"])

        self.update_album_props_mode = Utils.get_value_or_config_default("update_album_props_mode", args, Configuration.CONFIG_DEFAULTS["update_album_props_mode"])
        self.max_retry_count = Utils.get_value_or_config_default('max_retry_count', args, Configuration.CONFIG_DEFAULTS['max_retry_count'])

        if self.mode != Configuration.SCRIPT_MODE_CREATE:
            # Override unattended if we're running in destructive mode
            self.unattended = False

        # Create ignore regular expressions
        self.ignore_albums_regex = []
        if self.ignore_albums:
            for ignore_albums_entry in self.ignore_albums:
                self.ignore_albums_regex.append(Configuration.__glob_to_re(Configuration.__expand_to_glob(ignore_albums_entry)))

        # Create path filter regular expressions
        self.path_filter_regex = []
        if self.path_filter:
            for path_filter_entry in self.path_filter:
                self.path_filter_regex.append(Configuration.__glob_to_re(Configuration.__expand_to_glob(path_filter_entry)))

        # append trailing slash to all root paths
        # pylint: disable=C0200
        for i in range(len(self.root_paths)):
            if self.root_paths[i][-1] != '/':
                self.root_paths[i] = self.root_paths[i] + '/'

        # append trailing slash to root URL
        if self.root_url[-1] != '/':
            self.root_url = self.root_url + '/'

        self.__validate_config()
        #self.api_client = new ApiClient()

    def __validate_config(self):
        """
        Validates all set configuration values.

        :raises: ValueError if any config value does not pass validation
        """
        Utils.assert_not_none_or_empty("root_path", self.root_paths)
        Utils.assert_not_none_or_empty("root_url", self.root_url)
        Utils.assert_not_none_or_empty("api_key", self.api_key)

        if self.comments_and_likes_disabled and self.comments_and_likes_enabled:
            raise ValueError("Arguments --comments-and-likes-enabled and --comments-and-likes-disabled cannot be used together! Choose one!")

        self.__validate_album_range()

    def __validate_album_range(self):
        """
        Performs logic validation for album level range setting.
        """
        # Verify album levels range
        if not Utils.is_integer(self.album_levels):
            album_levels_range_split = self.album_levels.split(",")
            if any([
                    len(album_levels_range_split) != 2,
                    not Utils.is_integer(album_levels_range_split[0]),
                    not Utils.is_integer(album_levels_range_split[1]),
                    int(album_levels_range_split[0]) == 0,
                    int(album_levels_range_split[1]) == 0,
                    (int(album_levels_range_split[1]) < 0 <= int(album_levels_range_split[0])),
                    (int(album_levels_range_split[0]) < 0 <= int(album_levels_range_split[1])),
                    (int(album_levels_range_split[0]) < 0 and int(album_levels_range_split[1]) < 0 and int(album_levels_range_split[0]) > int(album_levels_range_split[1]))
                ]):
                raise ValueError(("Invalid album_levels range format! If a range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'. "
                            "If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>."))
            self.album_levels_range_arr = album_levels_range_split
            # Convert to int
            self.album_levels_range_arr[0] = int(album_levels_range_split[0])
            self.album_levels_range_arr[1] = int(album_levels_range_split[1])
            # Special case: both levels are negative and end level is -1, which is equivalent to just negative album level of start level
            if(self.album_levels_range_arr[0] < 0 and self.album_levels_range_arr[1] == -1):
                self.album_levels = self.album_levels_range_arr[0]
                self.album_levels_range_arr = ()
                logging.debug("album_levels is a range with negative start level and end level of -1, converted to album_levels = %d", self.album_levels)
            else:
                logging.debug("valid album_levels range argument supplied")
                logging.debug("album_levels_start_level = %d", self.album_levels_range_arr[0])
                logging.debug("album_levels_end_level = %d",self.album_levels_range_arr[1])
                # Deduct 1 from album start levels, since album levels start at 1 for user convenience, but arrays start at index 0
                if self.album_levels_range_arr[0] > 0:
                    self.album_levels_range_arr[0] -= 1
                    self.album_levels_range_arr[1] -= 1

    @staticmethod
    def __glob_to_re(pattern: str) -> str:
        """
        Converts the provided GLOB pattern to
        a regular expression.

        :param pattern: A GLOB-style pattern to convert to a regular expression
        
        :returns: A regular expression matching the same strings as the provided GLOB pattern
        :rtype: str
        """
        return Configuration.__escaped_glob_replacement.sub(lambda match: Configuration.__escaped_glob_tokens_to_re[match.group(0)], regex.escape(pattern))

    @staticmethod
    def __expand_to_glob(expr: str) -> str:
        """
        Expands the passed expression to a glob-style
        expression if it doesn't contain neither a slash nor an asterisk.
        The resulting glob-style expression matches any path that contains the
        original expression anywhere.

        :param expr: Expression to expand to a GLOB-style expression if not already one
        :returns: The original expression if it contained a slash or an asterisk, otherwise `**/*<expr>*/**`
        :rtype: str
        """
        if not '/' in expr and not '*' in expr:
            glob_expr = f'**/*{expr}*/**'
            logging.debug("expanding %s to %s", expr, glob_expr)
            return glob_expr
        return expr

    @staticmethod
    def get_arg_parser() -> argparse.ArgumentParser:
        """
        Creates a the argument parser for parsing command line arguments.

        :returns: The ArgumentParser with all options the script supports
        :rtype: argparse.ArgumentParser
        """

        parser = argparse.ArgumentParser(description="Create Immich Albums from an external library path based on the top level folders",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument("root_path", action='append', help="The external library's root path in Immich")
        parser.add_argument("api_url", help="The root API URL of immich, e.g. https://immich.mydomain.com/api/")
        parser.add_argument("api_key", action='append', help="The Immich API Key to use. Set --api-key-type to 'file' if a file path is provided.")
        parser.add_argument("--api-key", action="append",
                            help="Additional API Keys to run the script for; May be specified multiple times for running the script for multiple users.")
        parser.add_argument("-t", "--api-key-type", default=Configuration.CONFIG_DEFAULTS['api_key_type'], choices=['literal', 'file'], help="The type of the Immich API Key")
        parser.add_argument("-r", "--root-path", action="append",
                            help="Additional external library root path in Immich; May be specified multiple times for multiple import paths or external libraries.")
        parser.add_argument("-u", "--unattended", action="store_true", help="Do not ask for user confirmation after identifying albums. Set this flag to run script as a cronjob.")
        parser.add_argument("-a", "--album-levels", default=Configuration.CONFIG_DEFAULTS['album_levels'], type=str,
                            help="""Number of sub-folders or range of sub-folder levels below the root path used for album name creation.
                                    Positive numbers start from top of the folder structure, negative numbers from the bottom. Cannot be 0.
                                    If a range should be set, the start level and end level must be separated by a comma like '<startLevel>,<endLevel>'.
                                    If negative levels are used in a range, <startLevel> must be less than or equal to <endLevel>.""")
        parser.add_argument("-s", "--album-separator", default=Configuration.CONFIG_DEFAULTS['album_separator'], type=str,
                            help="Separator string to use for compound album names created from nested folders. Only effective if -a is set to a value > 1")
        parser.add_argument("-R", "--album-name-post-regex", nargs='+',
                action='append',
                metavar=('PATTERN', 'REPL'),
                help='Regex pattern and optional replacement (use "" for empty replacement). Can be specified multiple times.')
        parser.add_argument("-c", "--chunk-size", default=Configuration.CONFIG_DEFAULTS['chunk_size'], type=int, help="Maximum number of assets to add to an album with a single API call")
        parser.add_argument("-C", "--fetch-chunk-size", default=Configuration.CONFIG_DEFAULTS['fetch_chunk_size'], type=int, help="Maximum number of assets to fetch with a single API call")
        parser.add_argument("-l", "--log-level", default=Configuration.CONFIG_DEFAULTS['log_level'], choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'],
                            help="Log level to use. ATTENTION: Log level DEBUG logs API key in clear text!")
        parser.add_argument("-k", "--insecure", action="store_true", help="Pass to ignore SSL verification")
        parser.add_argument("-i", "--ignore", action="append",
                            help="""Use either literals or glob-like patterns to ignore assets for album name creation.
                                    This filter is evaluated after any values passed with --path-filter. May be specified multiple times.""")
        parser.add_argument("-m", "--mode", default=Configuration.CONFIG_DEFAULTS['mode'],
                            choices=[Configuration.SCRIPT_MODE_CREATE, Configuration.SCRIPT_MODE_CLEANUP, Configuration.SCRIPT_MODE_DELETE_ALL],
                            help="""Mode for the script to run with.
                                    CREATE = Create albums based on folder names and provided arguments;
                                    CLEANUP = Create album names based on current images and script arguments, but delete albums if they exist;
                                    DELETE_ALL = Delete all albums.
                                    If the mode is anything but CREATE, --unattended does not have any effect.
                                    Only performs deletion if -d/--delete-confirm option is set, otherwise only performs a dry-run.""")
        parser.add_argument("-d", "--delete-confirm", action="store_true",
                            help="""Confirm deletion of albums when running in mode """+Configuration.SCRIPT_MODE_CLEANUP+""" or """+Configuration.SCRIPT_MODE_DELETE_ALL+""".
                                    If this flag is not set, these modes will perform a dry run only. Has no effect in mode """+Configuration.SCRIPT_MODE_CREATE)
        parser.add_argument("-x", "--share-with", action="append",
                            help="""A user name (or email address of an existing user) to share newly created albums with.
                            Sharing only happens if the album was actually created, not if new assets were added to an existing album.
                            If the the share role should be specified by user, the format <userName>=<shareRole> must be used, where <shareRole> must be one of 'viewer' or 'editor'.
                            May be specified multiple times to share albums with more than one user.""")
        parser.add_argument("-o", "--share-role", default=Configuration.CONFIG_DEFAULTS['share_role'], choices=ApiClient.SHARE_ROLES,
                            help="""The default share role for users newly created albums are shared with.
                                    Only effective if --share-with is specified at least once and the share role is not specified within --share-with.""")
        parser.add_argument("-S", "--sync-mode", default=Configuration.CONFIG_DEFAULTS['sync_mode'], type=int, choices=[0, 1, 2],
                            help="""Synchronization mode to use. Synchronization mode helps synchronizing changes in external libraries structures to Immich after albums
                                    have already been created. Possible Modes: 0 = do nothing; 1 = Delete any empty albums; 2 = Delete offline assets AND any empty albums""")
        parser.add_argument("-O", "--album-order", default=Configuration.CONFIG_DEFAULTS['album_order'], type=str, choices=[False, 'asc', 'desc'],
                            help="Set sorting order for newly created albums to newest or oldest file first, Immich defaults to newest file first")
        parser.add_argument("-A", "--find-assets-in-albums", action="store_true",
                            help="""By default, the script only finds assets that are not assigned to any album yet.
                                    Set this option to make the script discover assets that are already part of an album and handle them as usual.
                                    If --find-archived-assets is set as well, both options apply.""")
        parser.add_argument("-f", "--path-filter", action="append",
                            help="""Use either literals or glob-like patterns to filter assets before album name creation.
                                    This filter is evaluated before any values passed with --ignore. May be specified multiple times.""")
        parser.add_argument("--set-album-thumbnail", choices=Configuration.ALBUM_THUMBNAIL_SETTINGS_GLOBAL,
                            help="""Set first/last/random image as thumbnail for newly created albums or albums assets have been added to.
                                    If set to """+Configuration.ALBUM_THUMBNAIL_RANDOM_FILTERED+""", thumbnails are shuffled for all albums whose assets would not be
                                    filtered out or ignored by the ignore or path-filter options, even if no assets were added during the run.
                                    If set to """+Configuration.ALBUM_THUMBNAIL_RANDOM_ALL+""", the thumbnails for ALL albums will be shuffled on every run.""")
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
        parser.add_argument("--api-timeout",  default=Configuration.CONFIG_DEFAULTS['api_timeout'], type=int, help="Timeout when requesting Immich API in seconds")
        parser.add_argument("--comments-and-likes-enabled", action="store_true",
                            help="Pass this argument to enable comment and like functionality in all albums this script adds assets to. Cannot be used together with --comments-and-likes-disabled")
        parser.add_argument("--comments-and-likes-disabled", action="store_true",
                            help="Pass this argument to disable comment and like functionality in all albums this script adds assets to. Cannot be used together with --comments-and-likes-enabled")
        parser.add_argument("--update-album-props-mode", type=int, choices=[0, 1, 2], default=Configuration.CONFIG_DEFAULTS['update_album_props_mode'],
                            help="""Change how album properties are updated whenever new assets are added to an album. Album properties can either come from script arguments or the .albumprops file.
                                    Possible values:
                                    0 = Do not change album properties.
                                    1 = Only override album properties but do not change the share status.
                                    2 = Override album properties and share status, this will remove all users from the album which are not in the SHARE_WITH list.""")
        parser.add_argument("--max-retry-count", type=int, default=Configuration.CONFIG_DEFAULTS['max_retry_count'],
                            help="Number of times to retry an Immich API call if it timed out before failing.")
        return parser

    @staticmethod
    def init_global_config() -> None:
        """
        Initializes global configuration options from global config file ()

        :returns: All configurations the script should run with
        :rtype: None
        """
        parser = Configuration.get_arg_parser()
        args = vars(parser.parse_args())
        Configuration.log_level = Utils.get_value_or_config_default("log_level", args, Configuration.CONFIG_DEFAULTS["log_level"])

    @classmethod
    def get_configurations(cls) -> list[Configuration]:
        """
        Creates and returns a list of configuration objects from the script's arguments.

        :returns: All configurations the script should run with
        :rtype: list[Configuration]
        """
        parser = Configuration.get_arg_parser()
        args = vars(parser.parse_args())
        created_configs: list[Configuration] = []
        api_key_type = Utils.get_value_or_config_default("api_key_type", args, Configuration.CONFIG_DEFAULTS["api_key_type"])
        # Create a configuration for each passed API key
        for api_key_arg in args['api_key']:
            api_keys = Configuration.__determine_api_key(api_key_arg, api_key_type)
            config_args = args
            for api_key in api_keys:
                # replace the API key array with the current api key for that configuration args
                config_args['api_key'] = api_key
                created_configs.append(cls(config_args))
        # Return a list with a single configuration
        return created_configs

    @staticmethod
    def __determine_api_key(api_key_source: str, key_type: str) -> list[str]:
        """
        For key_type `literal`, api_key_source is returned in a list with a single record.
        For key_type `file`, api_key_source is a path to a file containing the API key,
        each line in that file is interpreted as an API key. and a list with each line as a record
        is returned.

        :param api_key_source: An API key or path to a file containing an API key
        :param key_type: Must be either 'literal' or 'file'
        
        :returns: A list of API keys to use
        :rtype: list[str]
        """
        if key_type == 'literal':
            return [api_key_source]
        if key_type == 'file':
            return Utils.read_file(api_key_source).splitlines()
        # At this point key_type is not a valid value
        logging.error("Unknown key type (-t, --key-type). Must be either 'literal' or 'file'.")
        return None

    @staticmethod
    def log_debug_global():
        """
        Logs global configuration options on `DEBUG` log level
        """
        logging.debug("%s = '%s'", "log_level", Configuration.log_level)

    def log_debug(self):
        """
        Logs all its own properties on `DEBUG` log level
        """
        props = dict(vars(self))
        for prop in list(props.keys()):
            logging.debug("%s = '%s'", prop, props[prop])


class FolderAlbumCreator():
    """The Folder Album Creator class creating albums from folder structures based on the passed configuration"""

    # File name to use for album properties files
    ALBUMPROPS_FILE_NAME = '.albumprops'

    def __init__(self, configuration : Configuration):
        self.config = configuration
        # Create API client for configuration
        self.api_client = ApiClient(self.config.root_url,
                                    self.config.api_key,
                                    chunk_size=self.config.chunk_size,
                                    fetch_chunk_size=self.config.fetch_chunk_size,
                                    api_timeout=self.config.api_timeout,
                                    insecure=self.config.insecure,
                                    max_retry_count=self.config.max_retry_count)

    @staticmethod
    def find_albumprops_files(paths: list[str]) -> list[str]:

        """
        Recursively finds all album properties files in all passed paths.

        :param paths: A list of paths to search for album properties files

        :returns: A list of paths with all album properties files
        :rtype: list[str]
        """
        albumprops_files = []
        for path in paths:
            if not os.path.isdir(path):
                logging.warning("Album Properties Discovery: Path %s does not exist!", path)
                continue
            for path_tuple in os.walk(path):
                root = path_tuple[0]
                filenames = path_tuple[2]
                for filename in fnmatch.filter(filenames, FolderAlbumCreator.ALBUMPROPS_FILE_NAME):
                    albumprops_files.append(os.path.join(root, filename))
        return albumprops_files

    @staticmethod
    def __identify_root_path(path: str, root_path_list: list[str]) -> str:
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

    def build_album_properties_templates(self) -> dict:
        """
        Searches all root paths for album properties files,
        applies ignore/filtering mechanisms, parses the files,
        creates AlbumModel objects from them, performs validations and returns
        a dictionary mapping mapping the album name (generated from the path the album properties file was found in)
        to the album model file.
        If a fatal error occurs during processing of album properties files (i.e. two files encountered targeting the same album with incompatible properties), the
        program exits.

        :returns: A dictionary mapping the album name (generated from the path the album properties file was found in) to the album model files
        :rtype: dict
        """
        fatal_error_occurred = False
        album_properties_file_paths = FolderAlbumCreator.find_albumprops_files(self.config.root_paths)
        # Dictionary mapping album name generated from album properties' path to the AlbumModel representing the
        # album properties
        album_props_templates = {}
        album_name_to_album_properties_file_path = {}
        for album_properties_file_path in album_properties_file_paths:
            # First check global path_filter and ignore options
            if self.is_path_ignored(album_properties_file_path):
                continue

            # Identify the root path
            album_props_root_path = FolderAlbumCreator.__identify_root_path(album_properties_file_path, self.config.root_paths)
            if not album_props_root_path:
                continue

            # Chunks of the asset's path below root_path
            path_chunks = album_properties_file_path.replace(album_props_root_path, '').split('/')
            # A single chunk means it's just the image file in no sub folder, ignore
            if len(path_chunks) == 1:
                continue

            # remove last item from path chunks, which is the file name
            del path_chunks[-1]
            album_name = self.create_album_name(path_chunks, self.config.album_level_separator, self.config.album_name_post_regex)
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
            raise AlbumModelValidationError("Encountered at least one fatal error during parsing or validating of album properties files!")

        # Now validate that all album properties templates with the same override_name are compatible with each other
        FolderAlbumCreator.validate_album_props_templates(album_props_templates.values(), album_name_to_album_properties_file_path)

        return album_props_templates

    @staticmethod
    def validate_album_props_templates(album_props_templates: list[AlbumModel], album_name_to_album_properties_file_path: dict):
        """
        Validates the provided list of album properties.
        Specifically, checks that if multiple album properties files specify the same override_name, all other specified properties
        are the same as well.

        If a validation error occurs, the program exits.

        :param album_props_templates: The list of `AlbumModel` objects to validate
        :param album_name_to_album_properties_file_path: A dictionary where the key is an album name and the value is the path to the album properties file the
                album was generated from. This method expects one entry in this dictionary for every `AlbumModel` in album_props_templates.

        :raises AlbumMergeError: If validations do not pass
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
                        if FolderAlbumCreator.check_for_and_log_incompatible_properties(album_props_template, album_props_template_to_check, album_name_to_album_properties_file_path):
                            fatal_error_occurred = True
                checked_override_names.append(album_props_template.override_name)

        if fatal_error_occurred:
            raise AlbumMergeError("Encountered at least one fatal error while validating album properties files, stopping!")

    @staticmethod
    def check_for_and_log_incompatible_properties(model1: AlbumModel, model2: AlbumModel, album_name_to_album_properties_file_path: dict) -> bool:
        """
        Checks if model1 and model2 have incompatible properties (same properties set to different values). If so,
        logs the the incompatible properties and returns True.

        :param model1: The first album model to check for incompatibility with the second model
        :param model2: The second album model to check for incompatibility with the first model
        :param album_name_to_album_properties_file_path: A dictionary where the key is an album name and the value is the path to the album properties file the
                album was generated from. This method expects one entry in this dictionary for every AlbumModel in album_props_templates
        
        :returns: False if model1 and model2 are compatible, otherwise True
        :rtype: bool
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

    @staticmethod
    def build_inheritance_chain_for_album_path(album_path: str, root_path: str, albumprops_cache_param: dict) -> list[AlbumModel]:
        """
        Builds the inheritance chain for a given album path by walking up the directory tree
        and finding all .albumprops files with inherit=True.

        :param album_path: The full path to the album directory
        :param root_path: The root path to stop the inheritance chain at
        :param albumprops_cache: Dictionary mapping .albumprops file paths to AlbumModel objects

        :returns: List of AlbumModel objects in inheritance order (root to current)
        :rtype: list[AlbumModel]
        """
        inheritance_chain = []
        current_path = os.path.normpath(album_path)
        root_path = os.path.normpath(root_path)

        # Walk up the directory tree until we reach the root path
        while len(current_path) >= len(root_path):
            albumprops_path = os.path.join(current_path, FolderAlbumCreator.ALBUMPROPS_FILE_NAME)

            if albumprops_path in albumprops_cache_param:
                album_model_local = albumprops_cache_param[albumprops_path]
                inheritance_chain.insert(0, album_model_local)  # Insert at beginning for correct order

                # If this level doesn't have inherit=True, stop the inheritance chain
                if not album_model_local.inherit:
                    break

            # If we've reached the root path, stop
            if current_path == root_path:
                break

            # Move up one directory level
            parent_path = os.path.dirname(current_path)
            if parent_path == current_path:  # Reached filesystem root
                break
            current_path = parent_path

        return inheritance_chain

    # pylint: disable=R0912
    @staticmethod
    def apply_inheritance_to_album_model(album_model_param: AlbumModel, inheritance_chain: list[AlbumModel]) -> AlbumModel:
        """
        Applies inheritance from the inheritance chain to the given album model.

        :param album_model: The target album model to apply inheritance to (can be None if no local .albumprops)
        :param inheritance_chain: List of AlbumModel objects in inheritance order (root to current, excluding current)

        :returns: The album model with inherited properties applied
        :rtype: AlbumModel
        """
        if not inheritance_chain:
            return album_model_param

        # Create a new model to hold inherited properties
        if album_model_param:
            inherited_model: AlbumModel = AlbumModel(album_model_param.name)
            # Copy all properties from the original model first
            for prop_name in AlbumModel.ALBUM_PROPERTIES_VARIABLES + AlbumModel.ALBUM_INHERITANCE_VARIABLES:
                setattr(inherited_model, prop_name, getattr(album_model_param, prop_name))
            inherited_model.id = album_model_param.id
            inherited_model.assets = album_model_param.assets
        else:
            inherited_model = AlbumModel(None)

        inherited_share_with = []

        # Apply inheritance from root to current (inheritance_chain is already in correct order)
        for parent_model in inheritance_chain:
            if not parent_model.inherit_properties:
                # If no inherit_properties specified, inherit all properties
                inherit_props = AlbumModel.ALBUM_PROPERTIES_VARIABLES
            else:
                inherit_props = parent_model.inherit_properties

            # Apply inherited properties
            parent_attribs = vars(parent_model)
            inherited_attribs = vars(inherited_model)

            for prop_name in inherit_props:
                if prop_name in AlbumModel.ALBUM_PROPERTIES_VARIABLES and parent_attribs[prop_name] is not None:
                    if prop_name == 'share_with':
                        # Special handling for share_with - accumulate users
                        if parent_attribs[prop_name]:
                            inherited_share_with.extend(parent_attribs[prop_name])
                    else:
                        # For other properties, only set if not already set (parent properties have lower precedence)
                        if inherited_attribs[prop_name] is None:
                            inherited_attribs[prop_name] = parent_attribs[prop_name]

        # Apply accumulated inherited share_with if the current model doesn't have share_with
        if inherited_share_with and not inherited_model.share_with:
            inherited_model.share_with = inherited_share_with
        elif inherited_share_with and inherited_model.share_with:
            # Merge inherited and current share_with using the special merge logic
            temp_model = AlbumModel(None)
            temp_model.share_with = inherited_share_with
            inherited_model.share_with = inherited_model.merge_inherited_share_with(inherited_model.share_with)

        return inherited_model

    def build_albumprops_cache(self) -> dict:
        """
        Builds a cache of all .albumprops files found in root paths.

        :returns: Dictionary mapping .albumprops file paths to AlbumModel objects
        :rtype: dict
        """
        albumprops_files = FolderAlbumCreator.find_albumprops_files(self.config.root_paths)
        albumprops_path_to_model_dict = {}

        # Parse all .albumprops files
        for albumprops_path in albumprops_files:
            if self.is_path_ignored(albumprops_path):
                continue

            try:
                album_model_local = AlbumModel.parse_album_properties_file(albumprops_path)
                if album_model_local:
                    albumprops_path_to_model_dict[albumprops_path] = album_model_local
                    logging.debug("Loaded .albumprops from %s", albumprops_path)
            except yaml.YAMLError as ex:
                logging.error("Could not parse album properties file %s: %s", albumprops_path, ex)

        return albumprops_path_to_model_dict

    @staticmethod
    def get_album_properties_with_inheritance(album_name: str, album_path: str, root_path: str, albumprops_cache_param: dict) -> AlbumModel:
        """
        Gets the album properties for an album, applying inheritance from parent folders.

        :param album_name: The name of the album
        :param album_path: The full path to the album directory
        :param root_path: The root path for this album
        :param albumprops_cache: Dictionary mapping .albumprops file paths to AlbumModel objects

        :returns: The album model with inheritance applied, or None if no properties found
        :rtype: AlbumModel
        """
        # Check if the album directory has its own .albumprops file
        albumprops_path = os.path.join(album_path, FolderAlbumCreator.ALBUMPROPS_FILE_NAME)
        local_album_model = None

        logging.debug("Checking for album properties: album_path=%s, albumprops_path=%s", album_path, albumprops_path)

        if albumprops_path in albumprops_cache_param:
            local_album_model = albumprops_cache_param[albumprops_path]
            local_album_model.name = album_name
            logging.debug("Found local .albumprops for album '%s'", album_name)

        # Build inheritance chain (excluding the current level)
        inheritance_chain = FolderAlbumCreator.build_inheritance_chain_for_album_path(album_path, root_path, albumprops_cache_param)

        # Remove the current level from inheritance chain if it exists
        if inheritance_chain and albumprops_path in albumprops_cache_param:
            current_model = albumprops_cache_param[albumprops_path]
            if inheritance_chain and inheritance_chain[-1] is current_model:
                inheritance_chain = inheritance_chain[:-1]

        logging.debug("Inheritance chain for album '%s' has %d levels", album_name, len(inheritance_chain))

        # Apply inheritance
        if inheritance_chain or local_album_model:
            final_model = FolderAlbumCreator.apply_inheritance_to_album_model(local_album_model, inheritance_chain)
            if final_model and final_model.name is None:
                final_model.name = album_name

            # Log final properties for this album
            if final_model and (inheritance_chain or local_album_model):
                logging.info("Final album properties for '%s' (with inheritance): %s", album_name, final_model)

            return final_model

        return None


    @staticmethod
    def __parse_separated_string(separated_string: str, separator: str) -> Tuple[str, str]:
        """
        Parse a key, value pair, separated by the provided separator.

        That's the reverse of ShellArgs.
        On the command line (argparse) a declaration will typically look like:
            foo=hello
        or
            foo="hello world"

        :param separated_string: The string to parse
        :param separator: The separator to parse separated_string at
        :return: A tuple with the first value being the string on the left side of the separator 
            and the second value the string on the right side of the separator
        """
        items = separated_string.split(separator)
        key = items[0].strip() # we remove blanks around keys, as is logical
        value = None
        if len(items) > 1:
            # rejoin the rest:
            value = separator.join(items[1:])
        return (key, value)

    # pylint: disable=R0912
    def create_album_name(self, asset_path_chunks: list[str], album_separator: str, album_name_postprocess_regex: list) -> str:
        """
        Create album names from provided path_chunks string array.

        The method uses global variables album_levels_range_arr or album_levels to
        generate album names either by level range or absolute album levels. If multiple
        album path chunks are used for album names they are separated by album_separator.
        :param asset_path_chunks: A list of strings representing the folder names parsed from an asset's path
        :param album_seprator: The separator used for album names spanning multiple folder levels
        :param album_name_postprocess_regex: List of pairs of regex and replace, optional

        :returns: The created album name or None if the album levels range does not apply to the path chunks.
        :rtype: str
        """

        album_name_chunks = ()
        logging.debug("path chunks = %s", list(asset_path_chunks))
        # Check which path to take: album_levels_range or album_levels
        if len(self.config.album_levels_range_arr) == 2:
            if self.config.album_levels_range_arr[0] < 0:
                album_levels_start_level_capped = min(len(asset_path_chunks), abs(self.config.album_levels_range_arr[0]))
                album_levels_end_level_capped =  self.config.album_levels_range_arr[1]+1
                album_levels_start_level_capped *= -1
            else:
                # If our start range is already out of range of our path chunks, do not create an album from that.
                if len(asset_path_chunks)-1 < self.config.album_levels_range_arr[0]:
                    logging.debug("Skipping asset chunks since out of range: %s", asset_path_chunks)
                    return None
                album_levels_start_level_capped = min(len(asset_path_chunks)-1, self.config.album_levels_range_arr[0])
                # Add 1 to album_levels_end_level_capped to include the end index, which is what the user intended to. It's not a problem
                # if the end index is out of bounds.
                album_levels_end_level_capped =  min(len(asset_path_chunks)-1, self.config.album_levels_range_arr[1]) + 1
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
            album_levels_int = int(self.config.album_levels)
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

    def choose_thumbnail(self, thumbnail_setting: str, thumbnail_asset_list: list[dict]) -> str:
        """
        Tries to find an asset to use as thumbnail depending on thumbnail_setting.

        :param thumbnail_setting: Either a fully qualified asset path or one of `first`, `last`, `random`, `random-filtered`
        :param asset_list: A list of assets to choose a thumbnail from, based on thumbnail_setting

        :returns: An Immich asset dict or None if no thumbnail was found based on thumbnail_setting
        :rtype: str
        """
        # Case: fully qualified path
        if thumbnail_setting not in Configuration.ALBUM_THUMBNAIL_SETTINGS_GLOBAL:
            for asset in thumbnail_asset_list:
                if asset['originalPath'] == thumbnail_setting:
                    return asset
            # at this point we could not find the thumbnail asset by path
            return None

        # Case: Anything but fully qualified path
        # Apply filtering to assets
        thumbnail_assets = thumbnail_asset_list
        if thumbnail_setting == Configuration.ALBUM_THUMBNAIL_RANDOM_FILTERED:
            thumbnail_assets[:] = [asset for asset in thumbnail_assets if not self.is_path_ignored(asset['originalPath'])]

        if len(thumbnail_assets) > 0:
            # Sort assets by creation date
            thumbnail_assets.sort(key=lambda x: x['fileCreatedAt'])
            if thumbnail_setting not in Configuration.ALBUM_THUMBNAIL_STATIC_INDICES:
                idx = random.randint(0, len(thumbnail_assets)-1)
            else:
                idx = Configuration.ALBUM_THUMBNAIL_STATIC_INDICES[thumbnail_setting]
            return thumbnail_assets[idx]

        # Case: Invalid thumbnail_setting
        return None


    def is_path_ignored(self, path_to_check: str) -> bool:
        """
        Determines if the asset should be ignored for the purpose of this script
        based in its originalPath and global ignore and path_filter options.

        :param asset_to_check: The asset to check if it must be ignored or not. Must have the key 'originalPath'.
        
        :returns: True if the asset must be ignored, otherwise False
        :rtype: bool
        """
        is_path_ignored_result = False
        asset_root_path = None
        for root_path_to_check in self.config.root_paths:
            if root_path_to_check in path_to_check:
                asset_root_path = root_path_to_check
                break
        logging.debug("Identified root_path for asset %s = %s", path_to_check, asset_root_path)
        if asset_root_path:
            # First apply filter, if any
            if len(self.config.path_filter_regex) > 0:
                any_match = False
                for path_filter_regex_entry in self.config.path_filter_regex:
                    if regex.fullmatch(path_filter_regex_entry, path_to_check.replace(asset_root_path, '')):
                        any_match = True
                if not any_match:
                    logging.debug("Ignoring path %s due to path_filter setting!", path_to_check)
                    is_path_ignored_result = True
            # If the asset "survived" the path filter, check if it is in the ignore_albums argument
            if not is_path_ignored_result and len(self.config.ignore_albums_regex) > 0:
                for ignore_albums_regex_entry in self.config.ignore_albums_regex:
                    if regex.fullmatch(ignore_albums_regex_entry, path_to_check.replace(asset_root_path, '')):
                        is_path_ignored_result = True
                        logging.debug("Ignoring path %s due to ignore_albums setting!", path_to_check)
                        break

        return is_path_ignored_result

    @staticmethod
    def get_album_id_by_name(albums_list: list[dict], album_name: str, ) -> str:
        """ 
        Finds the album with the provided name in the list of albums and returns its id.
        
        :param albums_list: List of albums to find a particular album in
        :param album_name: Name of album to find the ID for

        :returns: The ID of the requested album or None if not found
        :rtype: str
        """
        for _ in albums_list:
            if _['albumName'] == album_name:
                return _['id']
        return None

    def check_for_and_remove_live_photo_video_components(self, asset_list: list[dict], is_not_in_album: bool, find_archived: bool) -> list[dict]:
        """
        Checks asset_list for any asset with file ending .mov. This is indicative of a possible video component
        of an Apple Live Photo. There is display bug in the Immich iOS app that prevents live photos from being
        show correctly if the static AND video component are added to the album. We only want to add the static component to an album,
        so we need to filter out all video components belonging to a live photo. The static component has a property livePhotoVideoId set
        with the asset ID of the video component.

        :param is_not_in_album: Flag indicating whether to fetch only assets that are not part
                of an album or not. If this and find_archived are True, we can assume asset_list is complete
                and should contain any static components.
        :param find_archived: Flag indicating whether to only fetch assets that are archived. If this and is_not_in_album are
                True, we can assume asset_list is complete and should contain any static components.

        :returns: An asset list without live photo video components
        :rtype: list[dict]
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
            if self.api_client.server_version['major'] == 1 and self.api_client.server_version['minor'] < 133:
                full_asset_list = self.api_client.fetch_assets_with_options({'isNotInAlbum': False, 'withArchived': True})
            else:
                full_asset_list = self.api_client.fetch_assets_with_options({'isNotInAlbum': False})
                full_asset_list += self.api_client.fetch_assets_with_options({'isNotInAlbum': False, 'visibility': 'archive'})
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

    # pylint: disable=R0914
    def set_album_properties_in_model(self, album_model_to_update: AlbumModel) -> None:
        """
        Sets the album_model's properties based on script options set.

        :param album_model: The album model to set the properties for
        """
        # Set share_with
        if self.config.share_with:
            for album_share_user in self.config.share_with:
                # Resolve share user-specific share role syntax <name>=<role>
                share_user_name, share_user_role_local = FolderAlbumCreator.__parse_separated_string(album_share_user, '=')
                # Fallback to default
                if share_user_role_local is None:
                    share_user_role_local = self.config.share_role

                album_share_with = {
                    'user': share_user_name,
                    'role': share_user_role_local
                }
                album_model_to_update.share_with.append(album_share_with)

        # Thumbnail Setting
        if self.config.set_album_thumbnail:
            album_model_to_update.thumbnail_setting = self.config.set_album_thumbnail

        # Archive setting
        if self.config.visibility is not None:
            album_model_to_update.visibility = self.config.visibility

        # Sort Order
        if self.config.album_order:
            album_model_to_update.sort_order = self.config.album_order

        # Comments and Likes
        if self.config.comments_and_likes_enabled:
            album_model_to_update.comments_and_likes_enabled = True
        elif self.config.comments_and_likes_disabled:
            album_model_to_update.comments_and_likes_enabled = False

    # pylint: disable=R0914,R1702,R0915
    def build_album_list(self, asset_list : list[dict], root_path_list : list[str], album_props_templates: dict, albumprops_cache_param: dict = None) -> dict:
        """
        Builds a list of album models, enriched with assets assigned to each album.
        Returns a dict where the key is the album name and the value is the model.
        Attention!

        :param asset_list: List of assets dictionaries fetched from Immich API
        :param root_path_list: List of root paths to use for album creation
        :param album_props_templates: Dictionary mapping an album name to album properties
        :param albumprops_cache: Dictionary mapping .albumprops file paths to AlbumModel objects (for inheritance)

        :returns: A dict with album names as keys and an AlbumModel as value
        :rtype: dict
        """
        album_models = {}
        logged_albums = set()  # Track which albums we've already logged properties for

        for asset_to_add in asset_list:
            asset_path = asset_to_add['originalPath']
            # This method will log the ignore reason, so no need to log anything again.
            if self.is_path_ignored(asset_path):
                continue

            # Identify the root path
            asset_root_path = FolderAlbumCreator.__identify_root_path(asset_path, root_path_list)
            if not asset_root_path:
                continue

            # Chunks of the asset's path below root_path
            path_chunks = asset_path.replace(asset_root_path, '').split('/')
            # A single chunk means it's just the image file in no sub folder, ignore
            if len(path_chunks) == 1:
                continue

            # remove last item from path chunks, which is the file name
            del path_chunks[-1]
            album_name = self.create_album_name(path_chunks, self.config.album_level_separator, self.config.album_name_post_regex)
            # Silently skip album, create_album_name already did debug logging
            if album_name is None:
                continue

            if len(album_name) > 0:
                # Check if we already created this album model
                final_album_name = album_name

                # Check for album properties with inheritance if albumprops_cache is provided
                inherited_album_model = None
                if albumprops_cache_param:
                    # Reconstruct the full album directory path
                    album_dir_path = os.path.join(asset_root_path, *path_chunks)
                    inherited_album_model = FolderAlbumCreator.get_album_properties_with_inheritance(album_name, album_dir_path, asset_root_path, albumprops_cache_param)
                    if inherited_album_model and inherited_album_model.override_name:
                        final_album_name = inherited_album_model.override_name

                # Check if there are traditional album properties for this album (backward compatibility)
                album_props_template = album_props_templates.get(album_name)
                if album_props_template and album_props_template.override_name:
                    final_album_name = album_props_template.override_name

                # Check if we already have this album model
                if final_album_name in album_models:
                    new_album_model = album_models[final_album_name]

                    # Merge properties when adding assets to an existing album with same final name
                    if inherited_album_model:
                        # For share_with, we need to accumulate all users from all directories
                        # using the most restrictive role policy
                        if inherited_album_model.share_with:
                            # Create a temporary model to merge the new share_with settings
                            # with the already accumulated settings in the existing album
                            temp_merge_model = AlbumModel(new_album_model.name)
                            temp_merge_model.share_with = new_album_model.share_with if new_album_model.share_with else []

                            # Use the merge logic to properly handle user conflicts, roles, and 'none' users
                            new_album_model.share_with = temp_merge_model.merge_inherited_share_with(inherited_album_model.share_with)

                        # For other properties, only update if not already set (preserve first album's properties as base)
                        temp_model = AlbumModel(new_album_model.name)
                        # Copy only non-share_with properties to avoid overwriting our accumulated share_with
                        for prop_name in AlbumModel.ALBUM_PROPERTIES_VARIABLES:
                            if prop_name != 'share_with' and getattr(inherited_album_model, prop_name) is not None:
                                setattr(temp_model, prop_name, getattr(inherited_album_model, prop_name))
                        new_album_model.merge_from(temp_model, AlbumModel.ALBUM_MERGE_MODE_EXCLUSIVE)

                else:
                    new_album_model = AlbumModel(album_name)
                    # Apply album properties from set options
                    self.set_album_properties_in_model(new_album_model)

                    # Apply inherited properties if available
                    if inherited_album_model:
                        new_album_model.merge_from(inherited_album_model, AlbumModel.ALBUM_MERGE_MODE_OVERRIDE)

                        # Log final album properties (only once per album)
                        if final_album_name not in logged_albums:
                            logging.info("Final album properties for '%s' (with inheritance): %s", final_album_name, new_album_model)
                            logged_albums.add(final_album_name)

                    # Apply traditional album properties if available (backward compatibility)
                    elif album_props_template:
                        new_album_model.merge_from(album_props_template, AlbumModel.ALBUM_MERGE_MODE_OVERRIDE)

                        # Log final album properties (only once per album)
                        if final_album_name not in logged_albums:
                            logging.info("Final album properties for '%s': %s", final_album_name, new_album_model)
                            logged_albums.add(final_album_name)
                    else:
                        # Log final album properties for albums without .albumprops (only once per album)
                        if final_album_name not in logged_albums:
                            logging.info("Final album properties for '%s': %s", final_album_name, new_album_model)
                            logged_albums.add(final_album_name)

                # Add asset to album model
                new_album_model.assets.append(asset_to_add)
                album_models[new_album_model.get_final_name()] = new_album_model
            else:
                logging.warning("Got empty album name for asset path %s, check your album_level settings!", asset_path)
        return album_models

    # pylint: disable=R1705
    @staticmethod
    def find_user_by_name_or_email(name_or_email: str, user_list: list[dict]) -> dict:
        """
        Finds a user identified by name_or_email in the provided user_list.

        :param name_or_email: The user name or email address to find the user by
        :param user_list: A list of user dictionaries with the following mandatory keys: `id`, `name`, `email`
        
        :returns: A user dict with matching name or email or None if no matching user was found
        :rtype: dict
        """
        for user in user_list:
            # Search by name or mail address
            if name_or_email in (user['name'], user['email']):
                return user
        return None

    def run(self) -> None:
        """
        Performs the actual logic of the script, i.e. creating albums from external library folder structures and everything else.
        """
        # Special case: Run Mode DELETE_ALL albums
        if self.config.mode == Configuration.SCRIPT_MODE_DELETE_ALL:
            self.api_client.delete_all_albums(self.config.visibility, self.config.delete_confirm)
            return

        album_properties_templates = {}
        albumprops_cache = {}
        if self.config.read_album_properties:
            logging.debug("Albumprops: Finding, parsing and loading %s files with inheritance support", FolderAlbumCreator.ALBUMPROPS_FILE_NAME)
            albumprops_cache = self.build_albumprops_cache()
            # Keep the old templates for backward compatibility with existing logic that expects album name keys
            album_properties_templates = self.build_album_properties_templates()
            for album_properties_path, album_properties_template in album_properties_templates.items():
                logging.debug("Albumprops: %s -> %s", album_properties_path, album_properties_template)

        logging.info("Requesting all assets")
        # only request images that are not in any album if we are running in CREATE mode,
        # otherwise we need all images, even if they are part of an album
        if self.config.mode == Configuration.SCRIPT_MODE_CREATE:
            assets = self.api_client.fetch_assets(not self.config.find_assets_in_albums, ['archive'] if self.config.find_archived_assets else [])
        else:
            assets = self.api_client.fetch_assets(False, ['archive'])

        # Remove live photo video components
        assets = self.check_for_and_remove_live_photo_video_components(assets, not self.config.find_assets_in_albums, self.config.find_archived_assets)
        logging.info("%d photos found", len(assets))

        logging.info("Sorting assets to corresponding albums using folder name")
        albums_to_create = self.build_album_list(assets, self.config.root_paths, album_properties_templates, albumprops_cache)
        albums_to_create = dict(sorted(albums_to_create.items(), key=lambda item: item[0]))

        if self.api_client.server_version['major'] == 1 and self.api_client.server_version['minor'] < 133:
            albums_with_visibility = [album_check_to_check for album_check_to_check in albums_to_create.values()
                                    if album_check_to_check.visibility is not None and album_check_to_check.visibility != 'archive']
            if len(albums_with_visibility) > 0:
                logging.warning("Option 'visibility' is only supported in Immich Server v1.133.x and newer! Option will be ignored!")

        logging.info("%d albums identified", len(albums_to_create))
        logging.info("Album list: %s", list(albums_to_create.keys()))

        if not self.config.unattended and self.config.mode == Configuration.SCRIPT_MODE_CREATE:
            if is_docker:
                print("Check that this is the list of albums you want to create. Run the container with environment variable UNATTENDED set to 1 to actually create these albums.")
                return
            else:
                print("Press enter to create these albums, Ctrl+C to abort")
                input()

        logging.info("Listing existing albums on immich")

        albums = self.api_client.fetch_albums()
        logging.info("%d existing albums identified", len(albums))

        album: AlbumModel
        for album in albums_to_create.values():
            # fetch the id if same album name exist
            album.id = FolderAlbumCreator.get_album_id_by_name(albums, album.get_final_name())

        # mode CLEANUP
        if self.config.mode == Configuration.SCRIPT_MODE_CLEANUP:
            # Filter list of albums to create for existing albums only
            albums_to_cleanup = {}
            for album in albums_to_create.values():
                # Only cleanup existing albums (has id set) and no duplicates (due to override_name)
                if album.id and album.id not in albums_to_cleanup:
                    albums_to_cleanup[album.id] = album
            # pylint: disable=C0103
            number_of_deleted_albums = self.api_client.cleanup_albums(albums_to_cleanup.values(), self.config.visibility, self.config.delete_confirm)
            logging.info("Deleted %d/%d albums", number_of_deleted_albums, len(albums_to_cleanup))
            return

        # Get all users in preparation for album sharing
        users = self.api_client.fetch_users()
        logging.debug("Found users: %s", users)

        # mode CREATE
        logging.info("Create / Append to Albums")
        created_albums = []
        # List for gathering all asset UUIDs for later archiving
        asset_uuids_added = []
        for album in albums_to_create.values():
            # Special case: Add assets to Locked folder
            # Locked assets cannot be part of an album, so don't create albums in the first place
            if album.visibility == 'locked':
                self.api_client.set_assets_visibility(album.get_asset_uuids(), album.visibility)
                logging.info("Added %d assets to locked folder", len(album.get_asset_uuids()))
                continue

            # Create album if inexistent:
            if not album.id:
                album.id = self.api_client.create_album(album.get_final_name())
                created_albums.append(album)
                logging.info('Album %s added!', album.get_final_name())

            logging.info("Adding assets to album %s", album.get_final_name())
            assets_added = self.api_client.add_assets_to_album(album.id, album.get_asset_uuids())
            if len(assets_added) > 0:
                asset_uuids_added += assets_added
                logging.info("%d new assets added to %s", len(assets_added), album.get_final_name())

            # Set assets visibility
            if album.visibility is not None:
                self.api_client.set_assets_visibility(assets_added, album.visibility)
                logging.info("Set visibility for %d assets to %s", len(assets_added), album.visibility)

            # Update album properties depending on mode or if newly created
            if self.config.update_album_props_mode > 0 or (album in created_albums):
                # Handle thumbnail
                # Thumbnail setting 'random-all' is handled separately
                if album.thumbnail_setting and album.thumbnail_setting != Configuration.ALBUM_THUMBNAIL_RANDOM_ALL:
                    # Fetch assets to be sure to have up-to-date asset list
                    album_to_update_info = self.api_client.fetch_album_info(album.id)
                    album_assets = album_to_update_info['assets']
                    thumbnail_asset = self.choose_thumbnail(album.thumbnail_setting, album_assets)
                    if thumbnail_asset:
                        logging.info("Using asset %s as thumbnail for album %s", thumbnail_asset['originalPath'], album.get_final_name())
                        album.thumbnail_asset_uuid = thumbnail_asset['id']
                    else:
                        logging.warning("Unable to determine thumbnail for setting '%s' in album %s", album.thumbnail_setting, album.get_final_name())
                # Update album properties
                try:
                    self.api_client.update_album_properties(album)
                except HTTPError as e:
                    logging.error('Error updating properties for album %s: %s', album.get_final_name(), e)

            # Update album sharing if needed or newly created
            if self.config.update_album_props_mode == 2 or (album in created_albums):
                # Handle album sharing
                self.api_client.update_album_shared_state(album, True, users)

        logging.info("%d albums created", len(created_albums))

        # Perform album cover randomization
        if self.config.set_album_thumbnail == Configuration.ALBUM_THUMBNAIL_RANDOM_ALL:
            logging.info("Picking a new random thumbnail for all albums")
            albums = self.api_client.fetch_albums()
            for album in albums:
                album_info = self.api_client.fetch_album_info(album['id'])
                # Create album model for thumbnail randomization
                album_model = AlbumModel(album['albumName'])
                album_model.id = album['id']
                album_model.assets = album_info['assets']
                # Set thumbnail setting to 'random' in model
                album_model.thumbnail_setting = 'random'
                thumbnail_asset = self.choose_thumbnail(album_model.thumbnail_setting, album_model.assets)
                if thumbnail_asset:
                    logging.info("Using asset %s as thumbnail for album %s", thumbnail_asset['originalPath'], album.get_final_name())
                    album_model.thumbnail_asset_uuid = thumbnail_asset['id']
                else:
                    logging.warning("Unable to determine thumbnail for setting '%s' in album %s", album.thumbnail_setting, album.get_final_name())
                # Update album properties (which will only pick a random thumbnail and set it, no other properties are changed)
                self.api_client.update_album_properties(album_model)

        # Perform sync mode action: Trigger offline asset removal
        if self.config.sync_mode == 2:
            logging.info("Trigger offline asset removal")
            self.api_client.trigger_offline_asset_removal()

        # Perform sync mode action: Delete empty albums
        #
        # For Immich versions prior to v1.116.0:
        # Attention: Since Offline Asset Removal is an asynchronous job,
        # albums affected by it are most likely not empty yet! So this
        # might only be effective in the next script run.
        if self.config.sync_mode >= 1:
            logging.info("Deleting all empty albums")
            albums = self.api_client.fetch_albums()
            # pylint: disable=C0103
            empty_album_count = 0
            # pylint: disable=C0103
            cleaned_album_count = 0
            for album in albums:
                if album['assetCount'] == 0:
                    empty_album_count += 1
                    logging.info("Deleting empty album %s", album['albumName'])
                    if self.api_client.delete_album(album):
                        cleaned_album_count += 1
            if empty_album_count > 0:
                logging.info("Successfully deleted %d/%d empty albums!", cleaned_album_count, empty_album_count)
            else:
                logging.info("No empty albums found!")

        logging.info("Done!")

class Utils:
    """A collection of helper methods"""
    @staticmethod
    def divide_chunks(full_list: list, chunk_size: int):
        """
        Yield successive chunk_size-sized chunks from full_list.
        
        :param full_list: The full list to create chunks from
        :param chunk_size: The number of records per chunk
        """
        # looping till length l
        for j in range(0, len(full_list), chunk_size):
            yield full_list[j:j + chunk_size]

    @staticmethod
    def assert_not_none_or_empty(key: str, value : any):
        """
        Asserts that the passed value is not None and not empty
        
        :param value: The value to assert
        :raises: ValueError if the passed value is None or empty
        """
        if value is None or len(str(value)) == 0:
            raise ValueError("Value for "+key+" is None or empty")

    @staticmethod
    def get_value_or_config_default(key : str, args_dict : dict, default: any) -> any:
        """
        Returns the value stored in args_dict under the provided key if it is not None or empty, 
        otherwise returns the value from Configuration.CONFIG_DEAULTS using the same key.
        
        :param default: The default value to return if value did not pass the check
        :param key: The dictionary key to look up the value for
        
        :returns: The passed value or the configuration default if the value did not pass the checks
        :rtype: any
        """
        try:
            Utils.assert_not_none_or_empty(key, args_dict[key] if key in args_dict else None)
            return args_dict[key]
        except ValueError:
            return default

    @staticmethod
    def is_integer(string_to_test: str) -> bool:
        """
        Trying to deal with python's isnumeric() function
        not recognizing negative numbers, tests whether the provided
        string is an integer or not.

        :param string_to_test: The string to test for integer
        
        :returns: True if string_to_test is an integer, otherwise False
        :rtype: bool
        """
        try:
            int(string_to_test)
            return True
        except ValueError:
            return False

    @staticmethod
    def read_file(file_path: str, encoding: str  = "utf-8") -> str:
        """
        Reads and returns the contents of the provided file.
        Assumes

        :param file_path: Path to the file to read
        :param encoding: The encoding to read the file with, defaults to `utf-8`
                
        :returns: The file's contents
        :rtype: str

        :raises: FileNotFoundError if the file does not exist
        :raises: Exception on any other error reading the file
        """
        with open(file_path, 'r', encoding=encoding) as secret_file:
            return secret_file.read().strip()

class AlbumCreatorLogFormatter(logging.Formatter):
    """Log formatter logging as logfmt with seconds-precision timestamps and lower-case log levels to match supercronic's logging"""
    def format(self, record):
        record.levelname = record.levelname.lower()
        logging.Formatter.formatTime = (lambda self, record, datefmt=None: datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).astimezone().replace(microsecond=0).isoformat(sep="T",timespec="seconds").replace('+00:00', 'Z'))
        return logging.Formatter.format(self, record)

# Set up logging
handler = logging.StreamHandler()
formatter = AlbumCreatorLogFormatter('time="%(asctime)s" level=%(levelname)s msg="%(message)s"')
handler.setFormatter(formatter)
# Initialize logging with default log level, we might have to log something when initializing the global configuration (which includes the log level we should use)
logging.basicConfig(level=Configuration.CONFIG_DEFAULTS["log_level"], handlers=[handler])
# Initialize global config
Configuration.init_global_config()
# Update log level with the level this configuration dictates
logging.getLogger().setLevel(Configuration.log_level)


is_docker = os.environ.get(ENV_IS_DOCKER, False)

try:
    configs = Configuration.get_configurations()
    logging.info("Created %d configurations", len(configs))
except(HTTPError, ValueError, AssertionError) as e:
    logging.fatal(e.msg)
    sys.exit(1)

Configuration.log_debug_global()

for config in configs:
    try:
        folder_album_creator = FolderAlbumCreator(config)

        processing_api_key = folder_album_creator.api_client.api_key[:5] + '*' * (len(folder_album_creator.api_client.api_key)-5)
        # Log the full API key when DEBUG logging is enabled
        if 'DEBUG' == config.log_level:
            processing_api_key = folder_album_creator.api_client.api_key

        logging.info("Processing API Key %s", processing_api_key)
        # Log config to DEBUG level
        config.log_debug()
        folder_album_creator.run()
    except (AlbumMergeError, AlbumModelValidationError, HTTPError, ValueError, AssertionError) as e:
        logging.fatal("Fatal error while processing configuration!")
        logging.fatal(e)
