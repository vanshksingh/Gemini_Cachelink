import os
import pathlib
import time
import datetime
import requests
from typing import Any, List, Union

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

# === INIT ===
def load_gemini_client() -> genai.Client:
    load_dotenv()
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# === FILE UTILITIES ===
def download_file(url: str, dest_path: Union[str, pathlib.Path]) -> pathlib.Path:
    path = pathlib.Path(dest_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as wf:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=32768):
                wf.write(chunk)
    return path

def upload_file(client: genai.Client, path: Union[str, pathlib.Path]) -> Any:
    file_obj = client.files.upload(file=pathlib.Path(path))
    while file_obj.state.name == 'PROCESSING':
        time.sleep(2)
        file_obj = client.files.get(name=file_obj.name)
    return file_obj

# === CACHE UTILITIES ===
def create_explicit_cache(client, model, contents, system_instruction, ttl_seconds, display_name):
    cache = client.caches.create(
        model=model,
        config=types.CreateCachedContentConfig(
            display_name=display_name,
            system_instruction=system_instruction,
            contents=contents,
            ttl=f"{ttl_seconds}s"
        )
    )
    return cache

def generate_from_cache(client, model, cache_name, prompt):
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(cached_content=cache_name)
    )
    return response

def list_caches(client):
    return list(client.caches.list())

def delete_cache(client, name):
    client.caches.delete(name=name)

def list_files(client):
    return list(client.files.list())

def delete_file(client, file_name):
    client.files.delete(name=file_name)

# === STREAMLIT UI ===
def main():
    st.title("🎥 Gemini Video + Cache Manager")

    client = load_gemini_client()
    model_id = "models/gemini-2.0-flash-001"

    st.sidebar.header("Actions")
    action = st.sidebar.radio("Choose an action:", ["Upload File", "Create Cache", "Query Cache", "Manage Caches", "Manage Files"])

    if action == "Upload File":
        st.subheader("Upload or Download File")
        file_upload = st.file_uploader("Upload a file", type=["mp4", "mp3", "wav", "txt", "pdf"])
        url_input = st.text_input("Or enter a file URL to download")

        if st.button("Process File"):
            if file_upload:
                temp_path = pathlib.Path(f"./uploads/{file_upload.name}")
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                with open(temp_path, "wb") as f:
                    f.write(file_upload.read())
                file_obj = upload_file(client, temp_path)
                st.success(f"Uploaded: {file_obj.uri}")
            elif url_input:
                dl_path = download_file(url_input, f"./downloads/{url_input.split('/')[-1]}")
                file_obj = upload_file(client, dl_path)
                st.success(f"Downloaded & Uploaded: {file_obj.uri}")
            else:
                st.warning("Upload a file or enter a URL.")

    elif action == "Create Cache":
        st.subheader("Create Explicit Cache")
        files = list_files(client)
        file_map = {f.name: f for f in files}
        selected_file = st.selectbox("Select File", list(file_map.keys()))
        sys_inst = st.text_area("System Instruction", "You are an expert analyzer.")
        ttl = st.number_input("TTL (seconds)", min_value=60, value=300)
        display_name = st.text_input("Cache Display Name", "my_cache")

        if st.button("Create Cache"):
            cache = create_explicit_cache(
                client, model_id, [file_map[selected_file]], sys_inst, ttl, display_name
            )
            st.success(f"Cache created: {cache.name}")

    elif action == "Query Cache":
        st.subheader("Query an Existing Cache")
        caches = list_caches(client)
        cache_map = {c.display_name: c for c in caches}
        selected_cache = st.selectbox("Select Cache", list(cache_map.keys()))
        prompt = st.text_area("Enter Prompt", "List characters with timestamps.")

        if st.button("Run Query"):
            response = generate_from_cache(client, model_id, cache_map[selected_cache].name, prompt)
            st.write("### Response")
            st.write(response.text)
            st.write("### Usage Metadata")
            st.json(response.usage_metadata)

    elif action == "Manage Caches":
        st.subheader("All Caches")
        caches = list_caches(client)
        for c in caches:
            st.write(f"**Name:** {c.display_name}")
            st.write(f"ID: {c.name}")
            st.write(f"Created: {c.create_time}")
            st.write(f"Expires: {c.expire_time}")
            if st.button(f"Delete {c.display_name}", key=c.name):
                delete_cache(client, c.name)
                st.success(f"Deleted cache {c.display_name}")
                st.experimental_rerun()

    elif action == "Manage Files":
        st.subheader("All Uploaded Files")
        files = list_files(client)
        for f in files:
            st.write(f"**Name:** {f.name}")
            st.write(f"URI: {f.uri}")
            st.write(f"Created: {f.create_time}")
            if st.button(f"Delete {f.name}", key=f.name):
                delete_file(client, f.name)
                st.success(f"Deleted file {f.name}")
                st.experimental_rerun()

if __name__ == "__main__":
    main()
