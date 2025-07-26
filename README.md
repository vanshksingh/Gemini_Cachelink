
# Gemini CacheLink

Gemini CacheLink is a Streamlit-based frontend for managing Google Gemini API file uploads, explicit caching, and content generation.
It provides an easy-to-use UI to:
- Upload local files or download from URLs
- Create explicit caches with TTL and system instructions
- Query caches for efficient re-use of tokens
- Manage (list, delete) caches and uploaded files

## 🚀 Features
- **File Uploads**: Upload audio/video/text files to the Gemini Files API.
- **Explicit Caching**: Create caches for long-term content re-use and token cost optimization.
- **Cache Querying**: Run prompts against existing caches for high-speed inference.
- **File Management**: View and delete uploaded files directly from the UI.
- **Streamlit Frontend**: Fully interactive web interface.

## 📂 Repository Structure
```
gemini_cachelink/
│── main.py         # Streamlit frontend
│── .env            # Contains GEMINI_API_KEY
│── requirements.txt
│── README.md
```

## 🛠️ Installation

1. **Clone the repo**
```bash
git clone https://github.com/vanshksingh/gemini_cachelink.git
cd gemini_cachelink
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```
*(or manually)*
```bash
pip install streamlit python-dotenv google-genai requests
```

3. **Set up environment variables**
Create a `.env` file in the project root:
```
GEMINI_API_KEY=your_gemini_api_key_here
```

## ▶️ Usage

Run the Streamlit app:
```bash
streamlit run main.py
```

Open the local URL displayed in the terminal (usually `http://localhost:8501`).

### 🔹 Uploading Files
- Upload via file uploader OR provide a direct URL.
- Files are processed and stored in the Gemini Files API.

### 🔹 Creating Explicit Cache
- Select an uploaded file.
- Enter system instructions and TTL (time-to-live).
- Create cache for re-use.

### 🔹 Querying Cache
- Select an existing cache.
- Enter a prompt and run the query.
- View results and usage metadata.

### 🔹 Managing Caches & Files
- List all caches and delete if needed.
- View and delete uploaded files.

## 📌 Requirements
- Python 3.9+
- Google Gemini API key

## 📝 Notes
- Uses `google-genai` official client.
- Optimized for `gemini-2.0-flash-001` model by default.
- Explicit cache reduces token cost by up to 75% per hit.

## 📜 License
MIT License © 2025 Vansh K Singh
