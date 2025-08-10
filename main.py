# main.py
import streamlit as st
import pathlib
import cache_utils as cu  # Import the refactored utility module

st.set_page_config(page_title="Gemini Cache Manager", layout="wide")
st.title("🎥 Gemini Video + Cache Manager")

# --- API Key and Client Initialization ---
st.sidebar.header("🔑 API Configuration")

# Use session state to persistently store the API key.
if 'api_key' not in st.session_state:
    st.session_state.api_key = None

# Try to load from secrets only if the key isn't already in the session state
if not st.session_state.api_key:
    try:
        st.session_state.api_key = st.secrets["GEMINI_API_KEY"]
        st.sidebar.success("API Key loaded from secrets.", icon="✅")
    except (FileNotFoundError, KeyError):
        st.sidebar.info("No API Key found in secrets. Please provide one below.")

# Get API key from user input, using the session state value as the default
user_api_key_input = st.sidebar.text_input(
    "Enter your Gemini API Key",
    type="password",
    value=st.session_state.api_key or ""
)

# If the user input differs from the session state, update it and rerun
if user_api_key_input != st.session_state.api_key:
    st.session_state.api_key = user_api_key_input
    st.rerun()

# On every script run, initialize the client if an API key is available
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
# Use a model that is known to be compatible with the Caching API
model_id = "models/gemini-2.5-flash"

st.sidebar.divider()
st.sidebar.header("Actions")
action = st.sidebar.radio(
    "Choose an action:",
    ["Upload File", "Create Cache", "Query Cache", "Manage Caches", "Manage Files"]
)

# --- Action Handlers ---
if action == "Upload File":
    st.header("📤 Upload or Download File")
    file_upload = st.file_uploader("Upload a file", type=["mp4", "mp3", "pdf", "jpg", "png"])
    url_input = st.text_input("Or enter a file URL to download and upload")

    if st.button("Process File"):
        path_to_upload = None
        if file_upload:
            temp_dir = pathlib.Path("./temp_uploads")
            temp_dir.mkdir(exist_ok=True)
            path_to_upload = temp_dir / file_upload.name
            with open(path_to_upload, "wb") as f:
                f.write(file_upload.getbuffer())
            st.info(f"Processing uploaded file: {file_upload.name}")
        elif url_input:
            temp_dir = pathlib.Path("./temp_downloads")
            file_name = url_input.split('/')[-1]
            path_to_upload = cu.download_file(url_input, temp_dir / file_name)
            st.info(f"Processing downloaded file: {file_name}")

        if path_to_upload:
            with st.spinner(f"Uploading and processing '{path_to_upload.name}'... This may take a moment."):
                try:
                    file_obj = cu.upload_file(path_to_upload)
                    st.success(f"File processed successfully! URI: {file_obj.uri}")
                    cached_list_files.clear()  # Clear cache to show new file
                except Exception as e:
                    st.error(f"Failed to process file: {e}")
        else:
            st.warning("Please upload a file or provide a URL.")

elif action == "Create Cache":
    st.header("💾 Create Explicit Cache")

    cache_content_source = st.radio("Cache Content Source:", ("From Uploaded File", "From Text Input"), horizontal=True)

    content_to_cache = None

    if cache_content_source == "From Uploaded File":
        files = cached_list_files()
        if not files:
            st.warning("No files found. Please upload a file first.")
        else:
            file_map = {f"{f.display_name} ({f.name})": f for f in files}
            selected_file_display = st.selectbox("Select File to Cache", list(file_map.keys()))
            if selected_file_display:
                content_to_cache = [file_map[selected_file_display]]
    else:  # From Text Input
        text_content = st.text_area("Enter text content to cache:", height=200)
        if text_content:
            content_to_cache = [text_content]

    if content_to_cache:
        sys_inst = st.text_area("System Instruction",
                                "You are an expert content analyzer. Answer queries based on the provided content.")
        ttl = st.number_input("Cache TTL (seconds)", min_value=60, value=3600)
        display_name = st.text_input("Cache Display Name", "my-new-cache")

        if st.button("Create Cache"):
            with st.spinner("Creating cache..."):
                try:
                    cache = cu.create_explicit_cache(model_id, content_to_cache, sys_inst, ttl, display_name)
                    st.success(f"Cache '{display_name}' created successfully! Name: {cache.name}")
                    cached_list_caches.clear()  # Clear cache to show new cache
                except Exception as e:
                    st.error(f"Failed to create cache: {e}")
    else:
        st.info("Please select or enter content to be cached.")


elif action == "Query Cache":
    st.header("❓ Query an Existing Cache")
    caches = cached_list_caches()
    if not caches:
        st.warning("No caches found. Please create a cache first.")
    else:
        cache_map = {f"{c.display_name} ({c.name})": c for c in caches}
        selected_cache_display = st.selectbox("Select Cache to Use", list(cache_map.keys()))
        prompt = st.text_area("Enter Your Prompt", "Summarize the content in three bullet points.")

        if st.button("Run Query"):
            with st.spinner("Generating response from cache..."):
                try:
                    selected_cache_obj = cache_map[selected_cache_display]
                    response = cu.generate_from_cache(model_id, selected_cache_obj.name, prompt)
                    st.session_state['last_query_response'] = response.text  # Store response for download
                except Exception as e:
                    st.error(f"Failed to query cache: {e}")
                    st.session_state['last_query_response'] = None

        if 'last_query_response' in st.session_state and st.session_state['last_query_response']:
            st.subheader("📝 Response")
            response_text = st.session_state['last_query_response']
            st.markdown(response_text)
            st.download_button(
                label="⬇️ Download Response",
                data=response_text,
                file_name="cache_query_response.txt",
                mime="text/plain"
            )

elif action == "Manage Caches":
    st.header("🗂️ Manage Caches")
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
    st.header("📂 Manage Files")
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
