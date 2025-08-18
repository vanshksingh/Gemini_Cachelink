# test_main.py
# Single-file pytest suite for main.py (Streamlit Gemini Cache Manager)
# - Fixes: session_state now supports attribute access like real Streamlit.
# - Mocks Streamlit + cache_utils with lightweight fakes.
# - Tests helpers and key page flows without real API calls or launching Streamlit.

import types
import io
import datetime as _dt
import pathlib
import importlib
import sys

import pytest


# ---------------------------
# AttrDict to mimic st.session_state attr access
# ---------------------------
class AttrDict(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)
    def __setattr__(self, k, v):
        self[k] = v
    def __delattr__(self, k):
        try:
            del self[k]
        except KeyError:
            raise AttributeError(k)


# ---------------------------
# Minimal Streamlit Test Double
# ---------------------------
class _Ctx:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False


class FakeStSidebar(_Ctx):
    def __init__(self, st):
        self._st = st

    def header(self, *a, **k): self._st._log.append(("sidebar.header", a, k))

    def text_input(self, label, type=None, key=None, on_change=None, value="", help=None):
        self._st._log.append(("sidebar.text_input", (label,), {"value": value, "key": key}))
        # emulate Streamlit 'key' behavior
        if key is not None:
            # If test pre-seeded a value, return it; else return provided default
            return self._st.session_state.get(key, value)
        return value

    def button(self, label):
        return self._st.button(label)

    def divider(self): self._st._log.append(("sidebar.divider", (), {}))

    def selectbox(self, label, options, help=None):
        self._st._last_selectbox_options = options
        ret = self._st._selectboxes.get(f"sidebar::{label}", options[0] if options else None)
        self._st._log.append(("sidebar.selectbox", (label,), {"ret": ret}))
        return ret


class FakeSt(_Ctx):
    def __init__(self):
        self.session_state = AttrDict()
        self._log = []
        self._buttons_true = set()       # labels that should return True once
        self._buttons_persistent = set() # labels that should always return True
        self._radios = {}                # label -> selected value
        self._text_inputs = {}           # label -> value
        self._text_areas = {}            # label -> value
        self._selectboxes = {}           # label -> selected option
        self._checkboxes = {}            # label -> bool
        self._number_inputs = {}         # label -> number
        self._stopped = False
        self.sidebar = FakeStSidebar(self)

    # --- Decorators ---
    def cache_data(self, ttl=None, show_spinner=None):
        def _decorator(fn):
            class _CWrapper:
                def __init__(self, f): self._f = f
                def __call__(self, *a, **k): return self._f(*a, **k)
                def clear(self): pass
            return _CWrapper(fn)
        return _decorator

    # --- Core ---
    def set_page_config(self, *a, **k): self._log.append(("set_page_config", a, k))
    def title(self, *a, **k): self._log.append(("title", a, k))
    def header(self, *a, **k): self._log.append(("header", a, k))
    def subheader(self, *a, **k): self._log.append(("subheader", a, k))
    def write(self, *a, **k): self._log.append(("write", a, k))
    def divider(self): self._log.append(("divider", (), {}))
    def caption(self, *a, **k): self._log.append(("caption", a, k))
    def json(self, *a, **k): self._log.append(("json", a, k))
    def code(self, *a, **k): self._log.append(("code", a, k))
    def markdown(self, *a, **k): self._log.append(("markdown", a, k))

    # --- Widgets ---
    def button(self, label, use_container_width=None, disabled=False, key=None):
        if disabled: return False
        if label in self._buttons_persistent: return True
        if label in self._buttons_true:
            self._buttons_true.remove(label)
            return True
        return False

    def file_uploader(self, label, type=None):
        # Return a fake upload object if pre-set; else None
        return self._text_inputs.get(("file_uploader", label))

    def text_input(self, label, **k):
        # generic non-sidebar text_input
        return self._text_inputs.get(label, k.get("value", ""))

    def text_area(self, label, value=None, height=None, placeholder=None):
        if label in self._text_areas:
            return self._text_areas[label]
        return value or ""

    def number_input(self, label, min_value=None, value=None, step=None):
        return self._number_inputs.get(label, value)

    def radio(self, label, options, horizontal=False, key=None):
        return self._radios.get(label, options[0])

    def checkbox(self, label, key=None, value=False):
        return self._checkboxes.get(key or label, value)

    def selectbox(self, label, options):
        sel = self._selectboxes.get(label, options[0] if options else None)
        return sel

    def columns(self, spec, vertical_alignment=None):
        # Return N context managers
        n = len(spec) if isinstance(spec, (list, tuple)) else 2
        return [ _Ctx() for _ in range(n) ]

    def container(self, border=False):
        return _Ctx()

    def download_button(self, *a, **k): self._log.append(("download_button", a, k))
    def spinner(self, label):
        class _Spin:
            def __enter__(_s): return _s
            def __exit__(_s, exc_type, exc, tb): return False
        return _Spin()

    # --- Status / flow ---
    def info(self, *a, **k): self._log.append(("info", a, k))
    def warning(self, *a, **k): self._log.append(("warning", a, k))
    def error(self, *a, **k): self._log.append(("error", a, k))
    def success(self, *a, **k): self._log.append(("success", a, k))
    def rerun(self): self._log.append(("rerun", (), {}))
    def stop(self):
        self._stopped = True
        raise SystemExit("st.stop() called")


# ---------------------------
# Fixtures to import main.py with fakes
# ---------------------------
@pytest.fixture()
def fake_env(tmp_path, monkeypatch):
    """
    Prepare a sandbox import of main.py with:
    - Fake streamlit (attr-style session_state)
    - Fake cache_utils (cu)
    """
    # Create fake streamlit instance (singleton)
    fst = FakeSt()

    # Build a module-like object for streamlit
    st_mod = types.ModuleType("streamlit")
    _singleton = fst

    # Bind module attributes to call the singleton methods
    for name in dir(FakeSt):
        if name.startswith("_"): continue
        attr = getattr(FakeSt, name)
        if callable(attr):
            def _make(method_name):
                def _wrapper(*a, **k):
                    return getattr(_singleton, method_name)(*a, **k)
                return _wrapper
            setattr(st_mod, name, _make(name))

    # Special attributes: session_state, sidebar, cache_data
    st_mod.session_state = _singleton.session_state
    st_mod.sidebar = _singleton.sidebar
    st_mod.cache_data = _singleton.cache_data

    monkeypatch.setitem(sys.modules, "streamlit", st_mod)

    # Fake cache_utils with call recording
    calls = {
        "initialize_client": [],
        "list_files": [],
        "list_caches": [],
        "upload_file": [],
        "download_file": [],
        "create_explicit_cache": [],
        "delete_cache": [],
        "delete_file": [],
        "generate_from_cache": [],
        "generate_with_implicit_cache": [],
        "min_cache_token_requirement": [],
        "estimate_tokens_from_text": [],
    }

    class CU:
        def initialize_client(api_key=None):
            calls["initialize_client"].append(api_key)
            return True

        def list_files():
            calls["list_files"].append(True)
            return []

        def list_caches():
            calls["list_caches"].append(True)
            return []

        def upload_file(path: pathlib.Path):
            calls["upload_file"].append(str(path))
            class _F:
                name = "files/abc123"
                display_name = path.name
                uri = f"gs://fake/{path.name}"
            return _F()

        def download_file(url, dest_path: pathlib.Path):
            calls["download_file"].append((url, str(dest_path)))
            dest_path.write_bytes(b"hello")
            return dest_path

        def create_explicit_cache(model_id, content_to_cache, sys_inst, ttl, display_name):
            calls["create_explicit_cache"].append(
                (model_id, content_to_cache, sys_inst, ttl, display_name)
            )
            class _C:
                name = "caches/xyz789"
                display_name = display_name
                create_time = _dt.datetime(2025, 8, 1, 12, 0, 0)
                expire_time = _dt.datetime(2025, 8, 1, 13, 0, 0)
                usage_metadata = types.SimpleNamespace(cached_content_token_count=1234)
            return _C()

        def delete_cache(name):
            calls["delete_cache"].append(name)

        def delete_file(name):
            calls["delete_file"].append(name)

        def generate_from_cache(model_id, cache_name, q):
            calls["generate_from_cache"].append((model_id, cache_name, q))
            class _R:
                text = f"Answer to: {q}"
                usage_metadata = types.SimpleNamespace(
                    prompt_token_count=10,
                    cached_content_token_count=100,
                    candidates_token_count=20,
                    total_token_count=130,
                )
            return _R()

        def generate_with_implicit_cache(model_id, sys_inst, q):
            calls["generate_with_implicit_cache"].append((model_id, sys_inst[:20], q))
            class _R:
                text = f"[implicit] {q}"
                usage_metadata = None
            return _R()

        def min_cache_token_requirement(model_id):
            calls["min_cache_token_requirement"].append(model_id)
            return 200  # arbitrary minimum

        def estimate_tokens_from_text(text):
            calls["estimate_tokens_from_text"].append(len(text))
            return max(1, len(text) // 4)

    cu_mod = types.SimpleNamespace(
        initialize_client=CU.initialize_client,
        list_files=CU.list_files,
        list_caches=CU.list_caches,
        upload_file=CU.upload_file,
        download_file=CU.download_file,
        create_explicit_cache=CU.create_explicit_cache,
        delete_cache=CU.delete_cache,
        delete_file=CU.delete_file,
        generate_from_cache=CU.generate_from_cache,
        generate_with_implicit_cache=CU.generate_with_implicit_cache,
        min_cache_token_requirement=CU.min_cache_token_requirement,
        estimate_tokens_from_text=CU.estimate_tokens_from_text,
    )
    monkeypatch.setitem(sys.modules, "cache_utils", cu_mod)

    # Import main fresh each time
    if "main" in sys.modules:
        del sys.modules["main"]
    import main as main_mod

    return types.SimpleNamespace(st=fst, st_mod=st_mod, cu_calls=calls, main=main_mod)


# ---------------------------
# Tests: pure helpers
# ---------------------------
def test_initialize_session_state_sets_defaults(fake_env):
    m = fake_env.main
    s = fake_env.st.session_state
    assert dict(s) == {}
    m.initialize_session_state()
    assert s.page_index == 0
    assert s.api_key is None
    assert s.source_youtube_url is None
    assert s.last_query_responses == []
    assert s.last_uploaded_file is None
    assert s.default_query_mode == "Explicit Cache"


def test_fmt_ts_variants(fake_env):
    m = fake_env.main
    assert m.fmt_ts(None) == "—"
    dt = _dt.datetime(2025, 8, 18, 10, 22, 59)
    assert m.fmt_ts(dt) == "2025-08-18 10:22"
    # string passthrough (trim)
    assert m.fmt_ts("2025-08-18T10:22:59.100Z") == "2025-08-18 10:22:59"


def test_build_yt_system_instruction_contains_links(fake_env):
    m = fake_env.main
    url = "https://www.youtube.com/watch?v=abcd"
    s = m.build_yt_system_instruction(url)
    assert url in s
    assert "[01:23]" in s
    assert "&t=83s" in s


# ---------------------------
# Tests: page_upload_file — upload flow
# ---------------------------
class _UploadObj(io.BytesIO):
    def __init__(self, name, data=b"filedata"):
        super().__init__(data)
        self.name = name
    def getbuffer(self):
        return super().getbuffer()


def test_page_upload_file_on_uploaded_file_sets_last_uploaded(fake_env, tmp_path, monkeypatch):
    m = fake_env.main
    st = fake_env.st

    # emulate choosing a file and clicking "Process File"
    st._text_inputs[("file_uploader", "Upload a file from your device")] = _UploadObj("notes.txt", b"hello")
    st._buttons_true.add("Process File")

    # set working dir
    monkeypatch.chdir(tmp_path)

    # run page
    m.initialize_session_state()
    m.page_upload_file()

    # Verify last_uploaded_file is set
    last = st.session_state["last_uploaded_file"]
    assert last is not None
    assert last["display_name"] == "notes.txt"
    assert last["uri"].startswith("gs://fake/notes.txt")


# ---------------------------
# Tests: page_query_cache (Implicit mode)
# ---------------------------
def test_page_query_cache_implicit_generates_and_saves(fake_env):
    m = fake_env.main
    st = fake_env.st
    calls = fake_env.cu_calls

    m.initialize_session_state()
    st._radios["Query Mode:"] = "Implicit (system+prompt only)"
    st._text_areas["Queries"] = "Q1\nQ2\n"
    st._buttons_true.add("Run Queries")

    m.page_query_cache(model_id="models/gemini-2.5-flash")

    # Verify cu called for each query
    g = calls["generate_with_implicit_cache"]
    assert len(g) == 2
    # And results captured
    results = st.session_state["last_query_responses"]
    assert len(results) == 2
    assert results[0][0] == "Q1"
    assert results[0][2] == "implicit"


# ---------------------------
# Tests: page_query_cache (Explicit mode)
# ---------------------------
def _mk_cache(display_name="demo", name="caches/1"):
    c = types.SimpleNamespace()
    c.display_name = display_name
    c.name = name
    c.create_time = _dt.datetime(2025, 8, 18, 9, 0, 0)
    c.expire_time = _dt.datetime(2025, 8, 18, 10, 0, 0)
    c.usage_metadata = types.SimpleNamespace(cached_content_token_count=999)
    return c


def test_page_query_cache_explicit_uses_selected_cache(fake_env, monkeypatch):
    m = fake_env.main
    st = fake_env.st
    calls = fake_env.cu_calls

    # Monkeypatch cached_list_caches() to return a cache and expose clear()
    class _CacheLister:
        def __call__(self): return [_mk_cache("cacheA", "caches/A")]
        def clear(self): pass
    monkeypatch.setattr(m, "cached_list_caches", _CacheLister())

    m.initialize_session_state()
    st._radios["Query Mode:"] = "Explicit Cache"
    st._text_areas["Queries"] = "Alpha\nBeta\n"
    st._buttons_true.add("Run Queries")
    # selectbox default picks first cache

    m.page_query_cache(model_id="models/gemini-2.0-flash-001")

    used = calls["generate_from_cache"]
    assert len(used) == 2
    assert used[0][1] == "caches/A"
    assert used[0][2] == "Alpha"


# ---------------------------
# Tests: page_manage_caches deletion flow
# ---------------------------
def test_page_manage_caches_delete_calls_cu_delete(fake_env, monkeypatch):
    m = fake_env.main
    st = fake_env.st
    calls = fake_env.cu_calls

    cache_obj = _mk_cache("to-delete", "caches/Z")

    class _CacheLister:
        def __call__(self): return [cache_obj]
        def clear(self): pass

    monkeypatch.setattr(m, "cached_list_caches", _CacheLister())

    m.initialize_session_state()
    # confirm + click
    st._checkboxes[f"del_confirm_{cache_obj.name}"] = True  # matches key used in main via unique key
    st._buttons_true.add("Delete Cache")

    m.page_manage_caches()

    assert calls["delete_cache"] == ["caches/Z"]


# ---------------------------
# Tests: page_manage_files deletion flow
# ---------------------------
def _mk_file(display_name="f", name="files/X", uri="gs://x"):
    f = types.SimpleNamespace()
    f.display_name = display_name
    f.name = name
    f.uri = uri
    f.create_time = _dt.datetime(2025, 8, 18, 9, 30, 0)
    return f


def test_page_manage_files_delete_calls_cu_delete(fake_env, monkeypatch):
    m = fake_env.main
    st = fake_env.st
    calls = fake_env.cu_calls

    file_obj = _mk_file("to-del", "files/9", "gs://9")

    class _FileLister:
        def __call__(self): return [file_obj]
        def clear(self): pass

    monkeypatch.setattr(m, "cached_list_files", _FileLister())

    m.initialize_session_state()
    st._checkboxes[f"del_confirm_file_{file_obj.name}"] = True  # matches key used in main
    st._buttons_true.add("Delete File")

    m.page_manage_files()

    assert calls["delete_file"] == ["files/9"]


# ---------------------------
# Tests: main() handles bad client init by stopping the app
# ---------------------------
def test_main_stops_on_bad_client_init(fake_env, monkeypatch):
    m = fake_env.main
    st = fake_env.st

    # Force initialize_client to raise
    def _bad_init(api_key=None):
        raise RuntimeError("bad key")
    monkeypatch.setattr(m.cu, "initialize_client", _bad_init)

    # seed required session_state for sidebar text_input path
    st.session_state["api_key_input"] = ""

    with pytest.raises(SystemExit) as ei:
        m.main()
    assert "st.stop()" in str(ei.value)
