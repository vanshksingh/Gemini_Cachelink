# cache_utils.py
# ---------------------------------------
# Utilities for Gemini Files + Explicit/Implicit Caching
# Uses the *new* google.genai client
# ---------------------------------------
from __future__ import annotations

import os
import time
import pathlib
from typing import List, Union, Optional, Any

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError


_CLIENT: Optional[genai.Client] = None


def initialize_client(api_key: Optional[str] = None) -> genai.Client:
    """
    Initialize and memoize a google.genai Client. Preference order:
    1) Explicit api_key argument
    2) .env -> GEMINI_API_KEY (via load_dotenv)
    3) Environment (already exported in shell)
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    load_dotenv()
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Provide it via .env or pass api_key to initialize_client()."
        )

    _CLIENT = genai.Client(api_key=key)
    return _CLIENT


# -----------------------
# Helpers
# -----------------------
def _safe_iter_list(fn, *, retries: int = 2, sleep: float = 0.7) -> list:
    """
    Call a list() endpoint that yields an iterator. Swallow transient 5xx issues
    and return [] so UI doesn't crash. Never raises to Streamlit layer.
    """
    for attempt in range(retries + 1):
        try:
            it = fn()
            return list(it)
        except ServerError:
            if attempt < retries:
                time.sleep(sleep)
                continue
            return []
        except APIError:
            return []
        except Exception:
            return []
    return []


def estimate_tokens_from_text(text: str) -> int:
    """Rough token estimate (~4 chars/token)."""
    if not text:
        return 0
    s = " ".join(text.split())
    return max(1, int(len(s) / 4))


def min_cache_token_requirement(model_id: str) -> int:
    """Explicit caches on -001 models commonly require >= 4096 tokens."""
    mid = model_id.lower()
    if "-001" in mid:
        return 4096
    return 4096


# -----------------------
# Files API
# -----------------------
def upload_file(path: Union[str, pathlib.Path]):
    """
    Upload a file using Files API and wait until it's processed (if applicable).
    Returns the File object.
    """
    client = initialize_client()
    path = pathlib.Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    f = client.files.upload(file=str(path))

    # Wait for processing for video/pdf etc.
    try:
        state = getattr(f, "state", None)
        name = getattr(f, "name", None)
        while hasattr(state, "name") and state.name == "PROCESSING":
            time.sleep(2)
            f = client.files.get(name=name)
            state = getattr(f, "state", None)
    except Exception:
        pass

    return f


def list_files() -> list:
    client = initialize_client()
    return _safe_iter_list(lambda: client.files.list())


def get_file(name: str, retries: int = 3, delay: float = 0.8):
    """
    Robust fetch of a single file by name. Returns None on persistent error.
    """
    client = initialize_client()
    last_err: Optional[Exception] = None
    for _ in range(retries):
        try:
            return client.files.get(name=name)
        except (ServerError, APIError) as e:
            last_err = e
            time.sleep(delay)
        except Exception as e:
            last_err = e
            time.sleep(delay)
    return None


def delete_file(name: str):
    client = initialize_client()
    return client.files.delete(name=name)


def download_file(url: str, dest_path: Union[str, pathlib.Path]) -> pathlib.Path:
    dest_path = pathlib.Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as wf:
            for chunk in r.iter_content(chunk_size=32768):
                if chunk:
                    wf.write(chunk)
    return dest_path


# -----------------------
# Explicit Cache API
# -----------------------
def _normalize_contents_for_cache(contents: List[Union[str, Any]]) -> List[Union[str, Any]]:
    """
    Accepts:
      - text strings
      - File objects from Files API
      - dict sentinel like {"name": "..."} saved from upload step
    Tries to resolve dict sentinel into a real File object via get_file().
    """
    normalized: List[Union[str, Any]] = []
    for item in contents:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, dict) and "name" in item:
            f = get_file(item["name"])
            if f is not None:
                normalized.append(f)
            # if still None, skip — caller should handle empty results
        else:
            # assume it's a File object already
            normalized.append(item)
    return normalized


def create_explicit_cache(
    model_id: str,
    contents: List[Union[str, Any]],
    system_instruction: str,
    ttl_seconds: int,
    display_name: str,
):
    """
    Create a cache with given contents and system_instruction.
    - contents can be strings and/or File objects returned from Files API.
    - ttl must be a string per API ("300s"), we convert from int seconds.
    """
    client = initialize_client()
    ttl_str = f"{int(ttl_seconds)}s"

    contents = _normalize_contents_for_cache(contents)
    if not contents:
        raise ValueError("No valid cache contents resolved. Please refresh files list and try again.")

    config = types.CreateCachedContentConfig(
        display_name=display_name,
        system_instruction=system_instruction,
        contents=contents,
        ttl=ttl_str,
    )
    cache = client.caches.create(model=model_id, config=config)
    return cache


def list_caches() -> list:
    client = initialize_client()
    return _safe_iter_list(lambda: client.caches.list())


def get_cache(name: str):
    client = initialize_client()
    return client.caches.get(name=name)


def update_cache_ttl(name: str, ttl_seconds: int):
    client = initialize_client()
    return client.caches.update(
        name=name,
        config=types.UpdateCachedContentConfig(ttl=f"{int(ttl_seconds)}s"),
    )


def update_cache_expire_time(name: str, expire_dt_iso: str):
    client = initialize_client()
    return client.caches.update(
        name=name,
        config=types.UpdateCachedContentConfig(expire_time=expire_dt_iso),
    )


def delete_cache(name: str):
    client = initialize_client()
    return client.caches.delete(name=name)


# -----------------------
# Generation Helpers
# -----------------------
def generate_from_cache(model_id: str, cache_name: str, prompt: str):
    client = initialize_client()
    resp = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(cached_content=cache_name),
    )
    return resp


def generate_with_implicit_cache(model_id: str, system_instruction: str, prompt: str):
    client = initialize_client()
    resp = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_instruction),
    )
    return resp
