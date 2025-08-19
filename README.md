
# 🎥 Gemini API Cache Manager

<img width="1199" height="674" alt="Screenshot 2025-08-19 at 8 59 31 PM" src="https://github.com/user-attachments/assets/7816f809-5848-4761-a5f0-4cd223e56025" />

🚀 Streamlit-powered UI for creating, managing, and querying caches with Gemini 2.0/2.5 API
🔗 GSoC 2025 Project Utility — Adds Explicit & Implicit Context Caching, File Uploads, and Token Savings Reports

---

## 📖 Overview

**Gemini API Cache Manager** is an interactive Streamlit app that helps developers, researchers, and AI engineers efficiently manage **context caching** with the Gemini API.

It supports **explicit and implicit caching**, file uploads, text-based context, and provides detailed **usage reports** to optimize token costs.

---

## ✨ Key Features

### 🛠️ Configuration Panel

* Secure API key entry (stored in session state, not persisted)
* Model selection (`gemini-2.5-flash`, `gemini-2.0-pro`, etc.)

### 💾 Cache Creation

* Create explicit caches from:

  * Uploaded files (TXT, PDF, DOCX, JSON, CSV)
  * Direct text input
  * YouTube reference URLs (metadata only)
* Automatic validation of token size (min 4096 tokens required)
* Fallback: if content too small → user can switch to **implicit caching**

### 🔍 Query with Cache

* Run single or multiple prompts against:

  * No cache
  * Explicit cache (`@use_cache`)
  * Implicit prefix reuse
* Inline display of answers
* Export all queries + answers + usage report as **TXT file**

### 📂 File Management

* Upload files for caching or reference
* Search, refresh, and manage uploaded files
* Automatic detection of supported formats

### 📊 Reports & Token Savings

* Track input, output, and total tokens
* Cached vs. billable token breakdown
* Estimated cost savings from cache hits
* Exportable report

---

## 🔧 Setup Instructions

1. **Clone the Repo**

```bash
git clone https://github.com/vanshksingh/Gemini_CacheManager.git
cd Gemini_CacheManager
```

2. **Create Virtual Environment**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. **Install Dependencies**

```bash
pip install -r requirements.txt
```

4. **Get Your Gemini API Key**
   👉 [Generate API Key](https://aistudio.google.com/app/apikey)

5. **Configure `.env`**

```env
GEMINI_API_KEY=your_api_key_here
```

---

## 📂 Repository Structure

```
Gemini_CacheManager/
├── main.py               # Streamlit app entrypoint (UI + logic)
├── cache_utils.py        # Explicit/implicit cache helpers
├── gem_cache.py          # Cache-aware planning logic
├── requirements.txt      # Python dependencies
├── README.md             # Documentation
```

---

## 🧠 Run Modes & Context Options

| Mode         | Description                                                  |
| ------------ | ------------------------------------------------------------ |
| **No Cache** | Always send full context (most expensive)                    |
| **Explicit** | Upload once, guaranteed reuse (up to 75% cheaper)            |
| **Implicit** | Auto-reuse overlapping prefixes (saves cost, not guaranteed) |

---

## 🔍 Example Usage

**Run the App**

```bash
streamlit run main.py
```

**Workflow Example**

1. Enter API Key and select model (`gemini-2.5-flash`)
2. Upload a file or paste text to create a cache
3. Run queries with **explicit cache**
4. Get structured answers inline
5. Export all Q\&A + token report as TXT

---

## 📊 Reports & Exports

✅ **Usage Report**

* Prompts count
* Token usage (input/output/total)
* Cached vs. billable tokens
* Cost savings from cache

📜 **Q\&A Export**

* Each query + answer
* Final usage report at the end

---

## 🛡️ Error Handling

* **Invalid API Key** → guided fix prompt
* **File too small (< 4096 tokens)** → fallback option to implicit cache
* **Unconfirmed upload** → "Refresh files list" retry button
* **Server errors** → safe retry with error display

---

## 🧑‍💻 Contributing

* Fork this repo
* Create a feature branch: `git checkout -b feature/xyz`
* Push changes and open a PR 🚀

---

## 📄 License

MIT License © 2025 Vansh Kumar Singh

---

## 🔗 Useful Links

* [Gemini API Docs](https://ai.google.dev/docs)
* [Google AI Studio](https://aistudio.google.com/)
* [DeepCache Project (related work)](https://github.com/google-deepmind)

