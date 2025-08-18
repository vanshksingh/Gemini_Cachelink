# tests/test_cache_utils.py
# -------------------------------------------------------
# Tests for cache_utils.py (mocked google.genai client)
# Uses pytest + unittest.mock; no external API calls.
# -------------------------------------------------------
from __future__ import annotations

import os
import io
import json
import time
import types as pytypes
import pathlib
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# Import the module under test
import cache_utils as cu


# -----------------------------
# Helpers: Fake objects / structs
# -----------------------------
class _State:
    def __init__(self, name: str):
        self.name = name


class _FakeFile:
    """Minimal shape for Files API object returned by google.genai."""
    def __init__(self, name: str, url: str = "https://example.com/f"):
        self.name = name
        self.uri = url
        self.state = _State("ACTIVE")


class _FakeProcessingFile(_FakeFile):
    """Starts in PROCESSING; becomes ACTIVE after one poll"""
    def __init__(self, name: str):
        super().__init__(name)
        self.state = _State("PROCESSING")
        self._polls = 0


class _FakeCache:
    def __init__(self, name: str, display_name: str = "my-cache"):
        self.name = name
        self.display_name = display_name


class _FakeGenAIClient:
    """
    Minimal fake for google.genai.Client with nested namespaces:
      - files: upload/get/list/delete
      - caches: create/get/list/update/delete
      - models: generate_content
    """
    def __init__(self, api_key: str = "dummy"):
        self.api_key = api_key

        self.files = pytypes.SimpleNamespace()
        self.caches = pytypes.SimpleNamespace()
        self.models = pytypes.SimpleNamespace()

        self._files: Dict[str, _FakeFile] = {}
        self._caches: Dict[str, _FakeCache] = {}

        # ==== Files API fakes ====
        def _upload(file: str):
            name = f"files/{pathlib.Path(file).name}"
            if "processing" in file:
                f = _FakeProcessingFile(name)
            else:
                f = _FakeFile(name)
            self._files[name] = f
            return f

        def _get_file(name: str):
            f = self._files.get(name)
            if isinstance(f, _FakeProcessingFile):
                f._polls += 1
                if f._polls >= 1:
                    f.state = _State("ACTIVE")
            return f

        def _list_files():
            for f in list(self._files.values()):
                yield f

        def _delete_file(name: str):
            self._files.pop(name, None)
            return pytypes.SimpleNamespace(name=name, deleted=True)

        self.files.upload = MagicMock(side_effect=_upload)
        self.files.get = MagicMock(side_effect=_get_file)
        self.files.list = MagicMock(side_effect=_list_files)
        self.files.delete = MagicMock(side_effect=_delete_file)

        # ==== Caches API fakes ====
        def _create_cache(model: str, config: Any):
            name = f"caches/{config.display_name}"
            cache = _FakeCache(name=name, display_name=config.display_name)
            self._caches[name] = cache
            return cache

        def _get_cache(name: str):
            return self._caches[name]

        def _list_caches():
            for c in list(self._caches.values()):
                yield c

        def _update_cache(name: str, config: Any):
            cache = self._caches.get(name, _FakeCache(name))
            self._caches[name] = cache
            return cache

        def _delete_cache(name: str):
            self._caches.pop(name, None)
            return pytypes.SimpleNamespace(name=name, deleted=True)

        self.caches.create = MagicMock(side_effect=_create_cache)
        self.caches.get = MagicMock(side_effect=_get_cache)
        self.caches.list = MagicMock(side_effect=_list_caches)
        self.caches.update = MagicMock(side_effect=_update_cache)
        self.caches.delete = MagicMock(side_effect=_delete_cache)

        # ==== Models API fakes ====
        def _generate_content(model: str, contents: Any, config: Any):
            return pytypes.SimpleNamespace(
                model=model,
                contents=contents,
                config=config,
                text=lambda: f"FAKE[{model}] -> {contents}"
            )

        self.models.generate_content = MagicMock(side_effect=_generate_content)


# -----------------------------
# Fixtures
# -----------------------------
@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch):
    """
    Ensure the module-level client memo is cleared between tests.
    Also make sure GEMINI_API_KEY is set for tests that rely on env.
    """
    cu._CLIENT = None
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    yield
    cu._CLIENT = None


@pytest.fixture
def fake_client():
    return _FakeGenAIClient(api_key="test_key")


@pytest.fixture
def patch_client(fake_client, monkeypatch):
    """
    Patch genai.Client to return our fake client, and patch type objects we need.
    """
    # Patch constructor
    monkeypatch.setattr(cu.genai, "Client", lambda api_key=None: fake_client)

    # Patch types.* used by cache_utils
    class CreateCachedContentConfig:
        def __init__(self, display_name, system_instruction, contents, ttl):
            self.display_name = display_name
            self.system_instruction = system_instruction
            self.contents = contents
            self.ttl = ttl

    class UpdateCachedContentConfig:
        def __init__(self, ttl=None, expire_time=None):
            self.ttl = ttl
            self.expire_time = expire_time

    class GenerateContentConfig:
        def __init__(self, cached_content=None, system_instruction=None):
            self.cached_content = cached_content
            self.system_instruction = system_instruction

    monkeypatch.setattr(cu.types, "CreateCachedContentConfig", CreateCachedContentConfig)
    monkeypatch.setattr(cu.types, "UpdateCachedContentConfig", UpdateCachedContentConfig)
    monkeypatch.setattr(cu.types, "GenerateContentConfig", GenerateContentConfig)

    return fake_client


# -----------------------------
# Tests: Client initialization
# -----------------------------
def test_initialize_client_uses_env(patch_client):
    client = cu.initialize_client()
    assert isinstance(client, _FakeGenAIClient)
    assert cu._CLIENT is client  # memoized

def test_initialize_client_explicit_key_overrides_env(monkeypatch, patch_client):
    monkeypatch.setenv("GEMINI_API_KEY", "env_key")
    client = cu.initialize_client(api_key="explicit_key")
    assert isinstance(client, _FakeGenAIClient)
    client2 = cu.initialize_client()
    assert client2 is client

def test_initialize_client_raises_when_missing_key(monkeypatch):
    """
    Robust even if a real .env exists or an autouse fixture sets the key.

    Steps:
      - Clear the memoized client
      - Remove GEMINI_API_KEY from the environment
      - Stub load_dotenv() so it can't repopulate from a .env file
      - Expect ValueError from initialize_client()
    """
    cu._CLIENT = None
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cu, "load_dotenv", lambda: None)
    with pytest.raises(ValueError):
        cu.initialize_client()



# -----------------------------
# Tests: Helper functions
# -----------------------------
@pytest.mark.parametrize(
    "text, expected_min",
    [
        ("", 0),
        ("abcd", 1),
        # Your implementation uses int(len/4); for 11 chars -> 2
        ("eight chars", 2),
    ],
)
def test_estimate_tokens_from_text(text, expected_min):
    tokens = cu.estimate_tokens_from_text(text)
    assert isinstance(tokens, int)
    assert tokens >= expected_min

def test_min_cache_token_requirement_default():
    assert cu.min_cache_token_requirement("gemini-2.5-flash") == 4096

def test_min_cache_token_requirement_dash001():
    assert cu.min_cache_token_requirement("gemini-2.0-pro-001") == 4096


# -----------------------------
# Tests: Files API
# -----------------------------
def test_upload_file_success(tmp_path, patch_client):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")
    f = cu.upload_file(file_path)
    assert f.name.startswith("files/")
    assert f.state.name == "ACTIVE"

def test_upload_file_waits_for_processing(tmp_path, patch_client):
    file_path2 = tmp_path / "file_processing_video.mp4"
    file_path2.write_text("pretend video")
    f = cu.upload_file(file_path2)
    assert f.state.name == "ACTIVE"

def test_upload_file_missing_path_raises(patch_client):
    with pytest.raises(FileNotFoundError):
        cu.upload_file("not_found.any")

def test_list_files_ok(patch_client, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    cu.upload_file(p)
    files = cu.list_files()
    assert len(files) >= 1

def test_get_file_with_retries_returns_none_on_persistent_error(monkeypatch, patch_client):
    def raiser(name: str):
        raise cu.APIError("boom")
    original = patch_client.files.get
    patch_client.files.get = MagicMock(side_effect=raiser)
    res = cu.get_file("files/not-there")
    assert res is None
    patch_client.files.get = original

def test_download_file_streams(monkeypatch, tmp_path, patch_client):
    class _Resp:
        def __init__(self):
            self._chunks = [b"abc", b"def", b"ghi"]
        def raise_for_status(self): return None
        def iter_content(self, chunk_size=32768):
            for c in self._chunks:
                yield c
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

    def fake_get(url, stream=True, timeout=60):
        return _Resp()

    monkeypatch.setattr(cu, "requests", pytypes.SimpleNamespace(get=fake_get))
    dest = tmp_path / "dl.bin"
    out = cu.download_file("https://example.com/file", dest)
    assert out.exists()
    assert out.read_bytes() == b"abcdefghi"


# -----------------------------
# Tests: Explicit Cache API
# -----------------------------
def test_normalize_contents_for_cache_accepts_str_and_file(patch_client, tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hi")
    fobj = cu.upload_file(path)
    contents = ["some text", fobj, {"name": fobj.name}]
    norm = cu._normalize_contents_for_cache(contents)
    assert isinstance(norm[0], str)
    assert hasattr(norm[1], "name")
    assert hasattr(norm[2], "name")

def test_create_explicit_cache_builds_config_and_calls_api(patch_client, tmp_path):
    path = tmp_path / "ctx.txt"
    path.write_text("context")
    fobj = cu.upload_file(path)

    cache = cu.create_explicit_cache(
        model_id="gemini-2.5-flash",
        contents=["alpha", fobj],
        system_instruction="You are helpful",
        ttl_seconds=300,
        display_name="exp-cache-1",
    )
    assert isinstance(cache, _FakeCache)
    assert cache.display_name == "exp-cache-1"
    called_args, called_kwargs = patch_client.caches.create.call_args
    assert called_kwargs["model"] == "gemini-2.5-flash"
    cfg = called_kwargs["config"]
    assert cfg.ttl == "300s"
    assert cfg.system_instruction == "You are helpful"

def test_create_explicit_cache_raises_on_empty_contents(patch_client, monkeypatch):
    monkeypatch.setattr(cu, "_normalize_contents_for_cache", lambda x: [])
    with pytest.raises(ValueError):
        cu.create_explicit_cache(
            model_id="gemini-2.5-flash",
            contents=[],
            system_instruction="x",
            ttl_seconds=120,
            display_name="will-fail",
        )

def test_list_get_update_delete_cache_roundtrip(patch_client):
    cache = cu.create_explicit_cache(
        model_id="gemini-2.0-pro",
        contents=["ctx"],
        system_instruction="sys",
        ttl_seconds=60,
        display_name="round",
    )
    lst = cu.list_caches()
    assert any(c.name == cache.name for c in lst)
    got = cu.get_cache(cache.name)
    assert got.name == cache.name
    upd = cu.update_cache_ttl(cache.name, 120)
    assert upd.name == cache.name
    upd2 = cu.update_cache_expire_time(cache.name, "2099-01-01T00:00:00Z")
    assert upd2.name == cache.name
    res = cu.delete_cache(cache.name)
    assert getattr(res, "deleted", False) is True


# -----------------------------
# Tests: Generation Helpers
# -----------------------------
def test_generate_from_cache_calls_models_with_cached_content(patch_client):
    cache = cu.create_explicit_cache(
        model_id="gemini-2.0-pro",
        contents=["ctx"],
        system_instruction="sys",
        ttl_seconds=120,
        display_name="gencache",
    )
    resp = cu.generate_from_cache(
        model_id="gemini-2.0-pro",
        cache_name=cache.name,
        prompt="What is 2+2?",
    )
    assert "2+2" in resp.text()
    args, kwargs = patch_client.models.generate_content.call_args
    cfg = kwargs["config"]
    assert cfg.cached_content == cache.name
    assert cfg.system_instruction is None

def test_generate_with_implicit_cache_sets_system_instruction(patch_client):
    resp = cu.generate_with_implicit_cache(
        model_id="gemini-2.5-flash",
        system_instruction="Be terse",
        prompt="Hello?",
    )
    assert "Hello?" in resp.text()
    args, kwargs = patch_client.models.generate_content.call_args
    cfg = kwargs["config"]
    assert cfg.system_instruction == "Be terse"
    assert cfg.cached_content is None


# -----------------------------
# Edge / resiliency: _safe_iter_list
# -----------------------------
def test_safe_iter_list_handles_server_error(monkeypatch):
    monkeypatch.setattr(cu, "ServerError", type("ServerError", (Exception,), {}))
    monkeypatch.setattr(cu, "APIError", type("APIError", (Exception,), {}))

    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise cu.ServerError("temporary")
        return iter([1, 2, 3])

    out = cu._safe_iter_list(flaky, retries=2, sleep=0.01)
    assert out == [1, 2, 3]

def test_safe_iter_list_returns_empty_on_apierror(monkeypatch):
    monkeypatch.setattr(cu, "APIError", type("APIError", (Exception,), {}))
    def always_apierror():
        raise cu.APIError("nope")
    out = cu._safe_iter_list(always_apierror)
    assert out == []


# ======================================================
# Optional: allow running tests via `python test_cache_utils.py`
# ======================================================
def main():
    """
    Allow: `python tests/test_cache_utils.py -k pattern`
    """
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main(sys.argv[1:] or ["-q"]))


if __name__ == "__main__":
    main()
