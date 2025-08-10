# cache_utils.py
import time
import pathlib
import datetime
import requests
from typing import Union, List, Any

from google import genai
from google.genai import types

# Global client variable, to be initialized by the main app
client = None


def initialize_client(api_key: str):
    """
    Initializes the global client with the provided API key.
    This MUST be called before any other function in this module.
    """
    global client
    if not api_key:
        raise ValueError("API key cannot be empty.")
    client = genai.Client(api_key=api_key)
    print("Gemini Client Initialized in cache_utils.")


# === FILE UTILITIES ===
def download_file(url: str, dest_path: Union[str, pathlib.Path]) -> pathlib.Path:
    """Downloads a file from `url` to `dest_path` if it does not already exist."""
    path = pathlib.Path(dest_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as wf:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                wf.write(chunk)
    return path


def upload_file(path: Union[str, pathlib.Path]) -> Any:
    """
    Upload a file to Gemini Files API and wait until processing is complete.
    This is a blocking operation.
    """
    if not client:
        raise RuntimeError("Client not initialized.")
    file_obj = client.files.upload(file=pathlib.Path(path))
    while file_obj.state.name == 'PROCESSING':
        print('Waiting for file to be processed...')
        time.sleep(2)
        file_obj = client.files.get(name=file_obj.name)
    return file_obj


# === CACHE UTILITIES ===
def create_explicit_cache(model: str, contents: List[Any], system_instruction: str, ttl_seconds: int,
                          display_name: str) -> Any:
    """Creates an explicit cache."""
    if not client:
        raise RuntimeError("Client not initialized.")

    ttl_string = f"{ttl_seconds}s"

    cache = client.caches.create(
        model=model,
        config=types.CreateCachedContentConfig(
            display_name=display_name,
            system_instruction=system_instruction,
            contents=contents,
            ttl=ttl_string
        )
    )
    return cache


def generate_from_cache(model: str, cache_name: str, prompt: str) -> Any:
    """Generates content from an existing cache."""
    if not client:
        raise RuntimeError("Client not initialized.")
    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(cached_content=cache_name)
    )
    return response


def list_caches() -> List[Any]:
    """Lists metadata for all caches."""
    if not client:
        raise RuntimeError("Client not initialized.")
    return list(client.caches.list())


def get_cache_metadata(name: str) -> Any:
    """Retrieves metadata for a single cache by name."""
    if not client:
        raise RuntimeError("Client not initialized.")
    return client.caches.get(name=name)


def update_cache_ttl(name: str, ttl_seconds: int) -> Any:
    """Updates the TTL for a specific cache."""
    if not client:
        raise RuntimeError("Client not initialized.")
    return client.caches.update(
        name=name,
        config=types.UpdateCachedContentConfig(ttl=f"{ttl_seconds}s")
    )


def delete_cache(name: str) -> None:
    """Deletes a cache by name."""
    if not client:
        raise RuntimeError("Client not initialized.")
    client.caches.delete(name=name)


# === FILE METADATA UTILITIES ===
def list_files() -> List[Any]:
    """Lists all uploaded files."""
    if not client:
        raise RuntimeError("Client not initialized.")
    return list(client.files.list())


def delete_file(file_name: str) -> None:
    """Deletes an uploaded file by name."""
    if not client:
        raise RuntimeError("Client not initialized.")
    client.files.delete(name=file_name)
