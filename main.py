import streamlit as st
import pathlib
import datetime
import re

# --- Page and State Configuration ---
# This MUST be the first Streamlit command in your script.
st.set_page_config(page_title="Gemini Cache Manager", layout="wide")

# Import third-party and local modules AFTER page config
import streamlit_cookies_manager
import cache_utils as cu  # Import the refactored utility module

# --- Constants ---
COOKIE_API_KEY = "gemini_cache_api_key"
PAGES = ["Upload File", "Create Cache", "Query Cache", "Manage Caches", "Manage Files"]

# --- Cookie and Session State Initialization ---
cookies = streamlit_cookies_manager.CookieManager()
if not cookies.ready():
    # Wait for the frontend to send cookies to the backend.
    st.spinner()
    st.stop()

st.title("🎥 Gemini Video + Cache Manager")

# --- Initialize Session State ---
if 'api_key' not in st.session_state:
    st.session_state.api_key = None
if 'page_index' not in st.session_state:
    st.session_state.page_index = 0
if 'source_youtube_url' not in st.session_state:
    st.session_state.source_youtube_url = None


# --- Helper Functions ---
def linkify_timestamps(text, base_url):
    """Finds timestamps (MM:SS or HH:MM:SS) and converts them to clickable YouTube links."""

    def replacer(match):
        parts = [int(p) for p in match.groups() if p is not None]
        if len(parts) == 3:  # HH:MM:SS
            seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
        else:  # MM:SS
            seconds = parts[0] * 60 + parts[1]

        timestamp_text = match.group(0)
        url = f"{base_url}&t={seconds}s"
        return f'[{timestamp_text}]({url})'

    # Regex to find HH:MM:SS or MM:SS patterns
    timestamp_pattern = re.compile(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})')
    return timestamp_pattern.sub(replacer, text)


# --- API Key and Client Initialization ---
st.sidebar.header("🔑 API Configuration")

# Try to load from cookies only if the key isn't already in the session state
if not st.session_state.api_key:
    st.session_state.api_key = cookies.get(COOKIE_API_KEY)

user_api_key_input = st.sidebar.text_input(
    "Enter your Gemini API Key",
    type="password",
    value=st.session_state.api_key or ""
)

if user_api_key_input != st.session_state.api_key:
    st.session_state.api_key = user_api_key_input
    cookies[COOKIE_API_KEY] = user_api_key_input  # Set cookie
    st.rerun()

if st.sidebar.button("Clear & Forget API Key"):
    st.session_state.api_key = None
    if COOKIE_API_KEY in cookies:
        del cookies[COOKIE_API_KEY]
    st.rerun()

if st.session_state.api_key:
    try:
        cu.initialize_client(st.session_state.api_key)
    except Exception as e:
        st.error(f"Failed to initialize Gemini client: {e}")
        st.stop()
else:
    st.info("Please provide your API key in the sidebar to begin.")
    st.stop()


# --- Cached Data Fetching ---
@st.cache_data(ttl=60)
def cached_list_files():
    return cu.list_files()


@st.cache_data(ttl=60)
def cached_list_caches():
    return cu.list_caches()


# --- Main UI ---
st.sidebar.divider()
st.sidebar.header("⚙️ Model Selection")
# Add a model selector in the sidebar
model_id = st.sidebar.selectbox(
    "Choose a Gemini Model",
    ("models/gemini-1.5-pro-latest", "models/gemini-1.5-flash-latest"),
    help="Select a model compatible with the Caching API."
)

# --- Navigation ---
st.write(f"### **Step {st.session_state.page_index + 1}/{len(PAGES)}: {PAGES[st.session_state.page_index]}**")
nav_cols = st.columns([1, 8, 1])
with nav_cols[0]:
    if st.button("⬅️ Back", use_container_width=True, disabled=(st.session_state.page_index == 0)):
        st.session_state.page_index -= 1
        st.rerun()
with nav_cols[2]:
    if st.button("Next ➡️", use_container_width=True, disabled=(st.session_state.page_index == len(PAGES) - 1)):
        st.session_state.page_index += 1
        st.rerun()
st.divider()

# --- Page Content ---
action = PAGES[st.session_state.page_index]

if action == "Upload File":
    st.header("📤 Step 1: Upload or Download File")
    file_upload = st.file_uploader("Upload a file from your device", type=["mp4", "mp3", "pdf", "jpg", "png"])
    url_input = st.text_input("Or enter a file URL to download and upload")

    if st.button("Process File"):
        path_to_upload = None
        # Reset youtube url state
        st.session_state.source_youtube_url = None

        if file_upload:
            temp_dir = pathlib.Path("./temp_uploads")
            temp_dir.mkdir(exist_ok=True)
            path_to_upload = temp_dir / file_upload.name
            with open(path_to_upload, "wb") as f:
                f.write(file_upload.getbuffer())
            st.info(f"Processing uploaded file: {file_upload.name}")
        elif url_input:
            if "youtube.com" in url_input or "youtu.be" in url_input:
                # Store the base URL for timestamp linking
                st.session_state.source_youtube_url = url_input.split('&')[0]

            temp_dir = pathlib.Path("./temp_downloads")
            file_name = url_input.split('/')[-1]
            path_to_upload = cu.download_file(url_input, temp_dir / file_name)
            st.info(f"Processing downloaded file: {file_name}")

        if path_to_upload:
            with st.spinner(f"Uploading and processing '{path_to_upload.name}'... This may take a moment."):
                try:
                    file_obj = cu.upload_file(path_to_upload)
                    st.success(f"File processed successfully! URI: {file_obj.uri}")
                    cached_list_files.clear()
                except Exception as e:
                    st.error(f"Failed to process file: {e}")
        else:
            st.warning("Please upload a file or provide a URL.")

elif action == "Create Cache":
    st.header("💾 Step 2: Create Explicit Cache")
    cache_content_source = st.radio("Cache Content Source:", ("From Uploaded File", "From Text Input"), horizontal=True)
    content_to_cache = None

    if cache_content_source == "From Uploaded File":
        files = cached_list_files()
        if not files:
            st.warning("No files found. Please go back to Step 1 to upload a file.")
        else:
            file_map = {f"{f.display_name} ({f.name})": f for f in files}
            selected_file_display = st.selectbox("Select File to Cache", list(file_map.keys()))
            if selected_file_display:
                content_to_cache = [file_map[selected_file_display]]
    else:
        text_content = st.text_area("Enter text content to cache:", height=200)
        if text_content:
            content_to_cache = [text_content]

    if content_to_cache:
        sys_inst = st.text_area("System Instruction",
                                "You are an expert video analyzer. When answering questions, provide timestamps from the video to support your answer.")
        ttl = st.number_input("Cache TTL (seconds)", min_value=60, value=3600)
        display_name = st.text_input("Cache Display Name", "my-new-cache")

        if st.button("Create Cache"):
            with st.spinner("Creating cache..."):
                try:
                    cache = cu.create_explicit_cache(model_id, content_to_cache, sys_inst, ttl, display_name)
                    st.success(f"Cache '{display_name}' created successfully! Name: {cache.name}")
                    cached_list_caches.clear()
                except Exception as e:
                    st.error(f"Failed to create cache: {e}")
    else:
        st.info("Please select or enter content to be cached.")

elif action == "Query Cache":
    st.header("❓ Step 3: Query an Existing Cache")
    caches = cached_list_caches()
    if not caches:
        st.warning("No caches found. Please go back to Step 2 to create a cache.")
    else:
        cache_map = {f"{c.display_name} ({c.name})": c for c in caches}
        selected_cache_display = st.selectbox("Select Cache to Use", list(cache_map.keys()))
        prompt = st.text_area("Enter Your Prompt", "Summarize the video. Include timestamps for key events.")

        if st.button("Run Query"):
            with st.spinner("Generating response from cache..."):
                try:
                    selected_cache_obj = cache_map[selected_cache_display]
                    response = cu.generate_from_cache(model_id, selected_cache_obj.name, prompt)
                    st.session_state['last_query_response'] = response.text
                except Exception as e:
                    st.error(f"Failed to query cache: {e}")
                    st.session_state['last_query_response'] = None

        if st.session_state.get('last_query_response'):
            st.subheader("📝 Response")
            response_text = st.session_state['last_query_response']

            # Linkify timestamps if the source was a YouTube video
            if st.session_state.get('source_youtube_url'):
                response_text = linkify_timestamps(response_text, st.session_state.source_youtube_url)

            st.markdown(response_text, unsafe_allow_html=True)
            st.download_button(
                label="⬇️ Download Full Response",
                data=st.session_state['last_query_response'],  # Download the raw text
                file_name="cache_query_response.txt",
                mime="text/plain"
            )

elif action == "Manage Caches":
    st.header("🗂️ Step 4: Manage Caches")
    if st.button("Refresh Cache List"):
        cached_list_caches.clear()
        st.rerun()
    caches = cached_list_caches()
    if not caches:
        st.info("No caches available.")
    for c in caches:
        with st.container(border=True):
            st.write(f"**Display Name:** {c.display_name}")
            st.code(f"ID: {c.name}", language=None)
            st.write(f"**Created:** {c.create_time.strftime('%Y-%m-%d %H:%M')}")
            st.write(f"**Expires:** {c.expire_time.strftime('%Y-%m-%d %H:%M')}")
            if st.button(f"Delete Cache '{c.display_name}'", key=c.name):
                cu.delete_cache(c.name)
                st.success(f"Deleted cache {c.display_name}")
                cached_list_caches.clear()
                st.rerun()

elif action == "Manage Files":
    st.header("📂 Step 5: Manage Files")
    if st.button("Refresh File List"):
        cached_list_files.clear()
        st.rerun()
    files = cached_list_files()
    if not files:
        st.info("No files uploaded.")
    for f in files:
        with st.container(border=True):
            st.write(f"**Display Name:** {f.display_name}")
            st.code(f"ID: {f.name}", language=None)
            st.code(f"URI: {f.uri}", language=None)
            st.write(f"**Created:** {f.create_time.strftime('%Y-%m-%d %H:%M')}")
            if st.button(f"Delete File '{f.display_name}'", key=f.name):
                cu.delete_file(f.name)
                st.success(f"Deleted file {f.display_name}")
                cached_list_files.clear()
                st.rerun()
