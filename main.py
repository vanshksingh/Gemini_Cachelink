# main.py
# ----------------------------------------------------
# Streamlit UI for Files API + Explicit/Implicit Cache
# - Uses google.genai (new client)
# - Correct .env usage via cache_utils.initialize_client()
# - Modular functions, no argparse
# - Exports per-query responses + one combined export
# - Proactive token checks for explicit caching
# ----------------------------------------------------
from __future__ import annotations

import pathlib
import textwrap
from typing import List, Tuple

import streamlit as st
from dotenv import load_dotenv  # loaded inside cache_utils as well
import cache_utils as cu  # local module


# -------------------------------
# Session-state & helpers
# -------------------------------
def initialize_session_state():
    if "page_index" not in st.session_state:
        st.session_state.page_index = 0
    if "api_key" not in st.session_state:
        st.session_state.api_key = None  # sidebar input takes precedence
    if "source_youtube_url" not in st.session_state:
        st.session_state.source_youtube_url = None
    if "last_query_responses" not in st.session_state:
        st.session_state.last_query_responses: List[Tuple[str, object, str]] = []


@st.cache_data(ttl=60, show_spinner=False)
def cached_list_files():
    return cu.list_files()


@st.cache_data(ttl=60, show_spinner=False)
def cached_list_caches():
    return cu.list_caches()


def fmt_ts(tsobj) -> str:
    if tsobj is None:
        return "—"
    if hasattr(tsobj, "strftime"):
        try:
            return tsobj.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    s = str(tsobj)
    return s.split(".")[0].replace("T", " ")


def build_yt_system_instruction(yt_url_base: str) -> str:
    return (
        "You are an expert video analyzer.\n"
        f"The user has provided a video from the URL: {yt_url_base}\n\n"
        "When you identify a key moment in the video, you MUST embed a clickable timestamp in your response.\n"
        "Format each timestamp as a Markdown link like: `[MM:SS](URL&t=XXs)` where `XX` is total seconds from start.\n\n"
        f"Example: `[01:23]({yt_url_base}&t=83s)` and `[12:05]({yt_url_base}&t=725s)`.\n"
        "Answer the user's question while providing precise, clickable timestamps as evidence."
    )


def render_navigation(pages: List[str]):
    st.write(
        f"### **Step {st.session_state.page_index + 1}/{len(pages)}: "
        f"{pages[st.session_state.page_index]}**"
    )
    nav_cols = st.columns([1, 8, 1])
    with nav_cols[0]:
        if st.button("⬅️ Back", use_container_width=True, disabled=(st.session_state.page_index == 0)):
            st.session_state.page_index -= 1
            st.rerun()
    with nav_cols[2]:
        if st.button(
            "Next ➡️",
            use_container_width=True,
            disabled=(st.session_state.page_index == len(pages) - 1),
        ):
            st.session_state.page_index += 1
            st.rerun()
    st.divider()


# -------------------------------
# Pages
# -------------------------------
def page_upload_file():
    st.header("📤 Step 1: Upload or Download File")

    file_upload = st.file_uploader(
        "Upload a file from your device",
        type=["mp4", "mp3", "pdf", "jpg", "png", "jpeg", "wav", "mkv"],
    )
    url_input = st.text_input("Or enter a file/YouTube URL")

    if st.button("Process File"):
        path_to_upload = None
        st.session_state.source_youtube_url = None

        if file_upload:
            temp_dir = pathlib.Path("./temp_uploads")
            temp_dir.mkdir(exist_ok=True, parents=True)
            path_to_upload = temp_dir / file_upload.name
            with open(path_to_upload, "wb") as f:
                f.write(file_upload.getbuffer())
            st.info(f"Processing uploaded file: {file_upload.name}")

        elif url_input:
            if "youtube.com/" in url_input or "youtu.be/" in url_input:
                st.session_state.source_youtube_url = url_input
                st.success("YouTube URL detected. It will be referenced in instructions; no upload needed.")
            else:
                file_name = url_input.split("/")[-1].split("?")[0] or "downloaded_file"
                temp_dir = pathlib.Path("./temp_downloads")
                temp_dir.mkdir(exist_ok=True, parents=True)
                try:
                    path_to_upload = cu.download_file(url_input, temp_dir / file_name)
                    st.info(f"Processing downloaded file: {file_name}")
                except Exception as e:
                    st.error(f"Failed to download file: {e}")

        if path_to_upload:
            with st.spinner(f"Uploading '{path_to_upload.name}' to Gemini and waiting for processing..."):
                try:
                    file_obj = cu.upload_file(path=path_to_upload)
                    st.success(f"File processed successfully! URI: {getattr(file_obj, 'uri', 'n/a')}")
                    cached_list_files.clear()
                except Exception as e:
                    st.error(f"Failed to process file: {e}")
        elif not file_upload and not url_input:
            st.warning("Please upload a file or provide a URL.")


def _token_hint_box(model_id: str, example_text: str):
    """Utility to show an estimate vs min required tokens."""
    min_needed = cu.min_cache_token_requirement(model_id)
    est = cu.estimate_tokens_from_text(example_text)
    ok = est >= min_needed
    st.info(
        f"Estimated tokens: **~{est}** • Minimum required for explicit cache on this model: **{min_needed}** "
        f"{'✅ OK' if ok else '❌ Too small'}"
    )
    return ok, est, min_needed


def page_create_cache(model_id: str):
    st.header("💾 Step 2: Create Explicit Cache")

    cache_content_source = st.radio(
        "Cache Content Source:",
        ("From Uploaded File", "From Text Input", "From YouTube URL (reference only)"),
        horizontal=True,
    )

    content_to_cache = None
    text_preview_for_estimate = ""

    if cache_content_source == "From Uploaded File":
        files = cached_list_files()
        if not files:
            st.warning("No files found. Please go back to Step 1 to upload a file.")
        else:
            def _label(f):
                disp = getattr(f, "display_name", None) or getattr(f, "name", "file")
                return f"{disp} ({getattr(f, 'name', 'n/a')})"

            file_map = {_label(f): f for f in files}
            selected_file_display = st.selectbox("Select File to Cache", list(file_map.keys()))
            if selected_file_display:
                content_to_cache = [file_map[selected_file_display]]
                st.caption("Files are typically large enough to satisfy token minimums.")

    elif cache_content_source == "From Text Input":
        text_content = st.text_area("Enter text content to cache:", height=220, placeholder="Paste large context here...")
        if text_content:
            content_to_cache = [text_content]
            text_preview_for_estimate = text_content
            _token_hint_box(model_id, text_preview_for_estimate)

    else:
        yt = st.session_state.get("source_youtube_url")
        if not yt:
            st.warning("No YouTube URL detected in Step 1. Paste it below or go back to Upload.")
            yt = st.text_input("YouTube URL")
        if yt:
            # IMPORTANT: a bare URL is far below token minimum (your 400 error).
            st.error(
                "A bare YouTube URL is **too small** for explicit caching. "
                "Either upload a file / paste a large transcript in **Text Input**, "
                "or switch to **Implicit** in Step 3."
            )
            # We intentionally DO NOT set content_to_cache here to block cache creation.

    # Default system instruction
    system_instruction_template = (
        "You are an expert content analyzer. When answering questions about the provided file, "
        "be precise, thorough, and helpful."
    )

    # Auto YT instruction
    if st.session_state.get("source_youtube_url"):
        clean_base_url = st.session_state.source_youtube_url.split("&")[0]
        system_instruction_template = build_yt_system_instruction(clean_base_url)

    sys_inst = st.text_area(
        "System Instruction (auto-generated for YouTube URLs)",
        system_instruction_template,
        height=220,
    )

    ttl = st.number_input("Cache TTL (seconds)", min_value=60, value=3600, step=60)
    display_name = st.text_input("Cache Display Name", "my-new-cache")

    # Explicit cache model sanity check
    if not model_id.endswith("-001"):
        st.warning(
            "For explicit caching you must use a model with an explicit version suffix, e.g. "
            "'models/gemini-2.0-flash-001' (not '-latest')."
        )

    # If text content is used, ensure it meets the min requirement before enabling the button
    allow_create = content_to_cache is not None
    if content_to_cache and isinstance(content_to_cache[0], str):
        ok, _, _ = _token_hint_box(model_id, text_preview_for_estimate or "")
        if not ok:
            allow_create = False
            st.error("Content is below the minimum token requirement for explicit caching on this model.")

    if allow_create:
        if st.button("Create Cache"):
            with st.spinner("Creating cache..."):
                try:
                    cache = cu.create_explicit_cache(model_id, content_to_cache, sys_inst, ttl, display_name)
                    st.success(f"Cache '{display_name}' created successfully!\nName: {getattr(cache, 'name', 'n/a')}")
                    cached_list_caches.clear()
                except Exception as e:
                    st.error(f"Failed to create cache: {e}")
    else:
        if cache_content_source == "From YouTube URL (reference only)":
            st.info("Switch to Implicit mode in Step 3 for YouTube URL–only workflows.")


def page_query_cache(model_id: str):
    st.header("❓ Step 3: Query an Existing Cache")

    query_mode = st.radio(
        "Query Mode:",
        ("Explicit Cache", "Implicit (system+prompt only)"),
        horizontal=True,
    )

    st.write("Enter one query per line:")
    default_prompts = textwrap.dedent(
        """\
        Summarize the video. Include timestamps for key events.
        List the main characters.
        Give 5 bullet key moments with timestamps.
        """
    ).strip()
    multi_query_text = st.text_area("Queries", default_prompts, height=140)

    if query_mode == "Explicit Cache":
        caches = cached_list_caches()
        if not caches:
            st.warning("No caches found. Please go back to Step 2 to create a cache.")
            return

        def _label(c):
            disp = getattr(c, "display_name", None) or getattr(c, "name", "cache")
            return f"{disp} ({getattr(c, 'name', 'n/a')})"

        cache_map = {_label(c): c for c in caches}
        selected_cache_display = st.selectbox("Select Cache to Use", list(cache_map.keys()))

        if st.button("Run Queries"):
            st.session_state.last_query_responses.clear()
            queries = [q.strip() for q in multi_query_text.splitlines() if q.strip()]
            selected_cache_obj = cache_map[selected_cache_display]

            for q in queries:
                with st.spinner(f"Generating (explicit) → {q}"):
                    try:
                        response = cu.generate_from_cache(model_id, selected_cache_obj.name, q)
                        st.session_state.last_query_responses.append((q, response, "explicit"))
                    except Exception as e:
                        st.error(f"Failed on query '{q}': {e}")

    else:
        # Implicit mode hint: works best on 2.5 models
        if "2.5" not in model_id:
            st.info(
                "Implicit caching is automatically enabled on Gemini 2.5 models. "
                "Consider switching to a 2.5 model for best results."
            )

        sys_inst = "You are a helpful content analyzer."
        if st.session_state.get("source_youtube_url"):
            yt_url = st.session_state.source_youtube_url.split("&")[0]
            sys_inst = build_yt_system_instruction(yt_url)

        if st.button("Run Queries"):
            st.session_state.last_query_responses.clear()
            queries = [q.strip() for q in multi_query_text.splitlines() if q.strip()]

            for q in queries:
                with st.spinner(f"Generating (implicit) → {q}"):
                    try:
                        response = cu.generate_with_implicit_cache(model_id, sys_inst, q)
                        st.session_state.last_query_responses.append((q, response, "implicit"))
                    except Exception as e:
                        st.error(f"Failed on query '{q}': {e}")

    # Render results + combined export
    if st.session_state.last_query_responses:
        combined_lines: List[str] = []
        for q, resp, mode in st.session_state.last_query_responses:
            st.subheader(f"🔎 [{mode}] Query: {q}")

            text = getattr(resp, "text", None) or "_No text response_"
            st.markdown(text, unsafe_allow_html=True)

            # Per-response download
            st.download_button(
                label=f"⬇️ Download Response ({mode} / {q[:20]}...)",
                data=text,
                file_name=f"response_{mode}_{q[:20].replace(' ', '_')}.txt",
                mime="text/plain",
            )

            # Usage metadata
            st.caption("📈 Usage Metadata")
            usage = getattr(resp, "usage_metadata", None)
            if usage:
                st.json(
                    {
                        "Prompt Token Count": getattr(usage, "prompt_token_count", None),
                        "Cached Content Token Count": getattr(usage, "cached_content_token_count", None),
                        "Candidates Token Count": getattr(usage, "candidates_token_count", None),
                        "Total Token Count": getattr(usage, "total_token_count", None),
                    }
                )
            else:
                st.write("No usage metadata available.")

            combined_lines.append(f"### [{mode}] {q}\n{text}\n")

        # Combined export
        combined_out = "\n\n---\n\n".join(combined_lines)
        st.download_button(
            label="⬇️ Download ALL Responses (combined)",
            data=combined_out,
            file_name="batch_responses_combined.txt",
            mime="text/plain",
        )


def page_manage_caches():
    st.header("🗂️ Step 4: Manage Caches")
    search_term_cache = st.text_input("Search caches by display name:")

    caches = cached_list_caches()
    if not caches:
        st.info("No caches available or listing temporarily unavailable.")
        return

    filtered = [c for c in caches if search_term_cache.lower() in (getattr(c, "display_name", "") or "").lower()]
    if not filtered:
        st.warning("No caches match your search.")

    for c in filtered:
        with st.container(border=True):
            st.write(f"**Display Name:** {getattr(c, 'display_name', '—')}")
            st.code(f"ID: {getattr(c, 'name', '—')}", language=None)
            st.write(f"**Created:** {fmt_ts(getattr(c, 'create_time', None))}")
            st.write(f"**Expires:** {fmt_ts(getattr(c, 'expire_time', None))}")

            um = getattr(c, "usage_metadata", None)
            if um:
                st.json({"Cached Tokens": getattr(um, "cached_content_token_count", None)})

            confirm_delete = st.checkbox(
                f"Confirm deletion of '{getattr(c, 'display_name', getattr(c, 'name', 'cache'))}'",
                key=f"del_confirm_{getattr(c, 'name', id(c))}",
            )
            if st.button(
                "Delete Cache",
                key=f"del_btn_{getattr(c, 'name', id(c))}",
                disabled=not confirm_delete,
            ):
                try:
                    cu.delete_cache(c.name)
                    st.success(f"Deleted cache {getattr(c, 'display_name', getattr(c, 'name', 'cache'))}")
                    cached_list_caches.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")


def page_manage_files():
    st.header("📂 Step 5: Manage Files")
    search_term_file = st.text_input("Search files by display name:")

    files = cached_list_files()
    if not files:
        st.info("No files uploaded or listing temporarily unavailable.")
        return

    filtered = [f for f in files if search_term_file.lower() in (getattr(f, "display_name", "") or "").lower()]
    if not filtered:
        st.warning("No files match your search.")

    for f in filtered:
        with st.container(border=True):
            st.write(f"**Display Name:** {getattr(f, 'display_name', '—')}")
            st.code(f"ID: {getattr(f, 'name', '—')}", language=None)
            st.code(f"URI: {getattr(f, 'uri', '—')}", language=None)
            st.write(f"**Created:** {fmt_ts(getattr(f, 'create_time', None))}")

            confirm_delete_file = st.checkbox(
                f"Confirm deletion of '{getattr(f, 'display_name', getattr(f, 'name', 'file'))}'",
                key=f"del_confirm_file_{getattr(f, 'name', id(f))}",
            )
            if st.button(
                "Delete File",
                key=f"del_btn_file_{getattr(f, 'name', id(f))}",
                disabled=not confirm_delete_file,
            ):
                try:
                    cu.delete_file(f.name)
                    st.success(f"Deleted file {getattr(f, 'display_name', getattr(f, 'name', 'file'))}")
                    cached_list_files.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")


# -------------------------------
# App entry
# -------------------------------
def main():
    # Must be first Streamlit call
    st.set_page_config(page_title="Gemini Cache Manager", layout="wide")
    st.title("🎥 Gemini API Cache Manager")

    PAGES = ["Upload File", "Create Cache", "Query Cache", "Manage Caches", "Manage Files"]
    initialize_session_state()

    # Sidebar: API Key
    st.sidebar.header("🔑 API Configuration")

    def _apply_key():
        st.session_state.api_key = st.session_state.api_key_input

    st.sidebar.text_input(
        "Enter your Gemini API Key",
        type="password",
        key="api_key_input",
        on_change=_apply_key,
        value=st.session_state.api_key or "",
        help="Tip: you can also set GEMINI_API_KEY in a .env file.",
    )

    if st.sidebar.button("Clear API Key"):
        st.session_state.api_key = None
        st.session_state.api_key_input = ""
        st.rerun()

    # Initialize client (honors .env as well)
    try:
        cu.initialize_client(st.session_state.api_key)
    except Exception as e:
        st.error(f"Failed to configure Gemini client: {e}")
        st.stop()

    # Sidebar: model selection
    st.sidebar.divider()
    st.sidebar.header("⚙️ Model Selection")
    model_id = st.sidebar.selectbox(
        "Choose a Gemini Model",
        (
            # Explicit cache-friendly (must end with -001)
            "models/gemini-2.0-flash-001",
            "models/gemini-1.5-pro-001",
            # Implicit cache-friendly (2.5 family)
            "models/gemini-2.5-flash",
            "models/gemini-2.5-pro",
        ),
        help=(
            "Explicit caching requires a model with explicit version suffix '-001'. "
            "Implicit caching is automatically enabled on Gemini 2.5 models."
        ),
    )

    # Navigation
    render_navigation(PAGES)

    # Routing
    page = PAGES[st.session_state.page_index]
    if page == "Upload File":
        page_upload_file()
    elif page == "Create Cache":
        page_create_cache(model_id)
    elif page == "Query Cache":
        page_query_cache(model_id)
    elif page == "Manage Caches":
        page_manage_caches()
    elif page == "Manage Files":
        page_manage_files()


if __name__ == "__main__":
    main()
