<div align="center">

# ✦ Cleo

**A personal AI assistant with a web interface, real tools, and memory.**

Built with Google Gemini 2.5 Flash · Python · MCP · Flask

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-4285F4?style=flat-square&logo=google&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat-square&logo=flask&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-1.0-6e40c9?style=flat-square)
![License](https://img.shields.io/badge/License-All%20Rights%20Reserved-red?style=flat-square)

</div>

---

Cleo is a personal AI assistant that runs locally in your browser. Unlike simple chatbots, Cleo can actually **do things**: read and write files, search the web, query a database, and fetch live data like weather and time — all powered by a custom MCP (Model Context Protocol) server and Google Gemini.

---

## ✨ Features

- 🌐 **Web interface** — clean dark-theme UI, runs in any browser
- 🔍 **Web search** — searches DuckDuckGo in real time, no API key needed
- 📁 **File system** — reads, writes, lists and deletes files in a sandboxed folder
- 🗄️ **SQLite database** — manages notes, tasks and contacts with natural language
- 🌤️ **Live weather** — real-time forecasts via Open-Meteo (free, no API key)
- 🕐 **Date & time** — timezone-aware datetime queries
- 🔁 **Conversation memory** — remembers context across the session
- ⚡ **Retry logic** — handles Gemini rate limits with exponential backoff

---

## 🏗️ Architecture

```
┌──────────────────┐         HTTP          ┌──────────────────┐        stdio (JSON-RPC)       ┌──────────────────┐
│                  │  ──────────────────►  │                  │  ────────────────────────────► │                  │
│    Browser       │                       │   Flask + Gemini  │                               │    MCP Server    │
│  (index.html)    │  ◄──────────────────  │     (app.py)     │  ◄────────────────────────────│   (server.py)    │
│                  │                       │                  │                               │                  │
└──────────────────┘                       └──────────────────┘                               └──────────────────┘
```

**How it works, step by step:**

1. The user types a message in the browser
2. The browser sends it to Flask via a `POST /api/chat` request
3. Flask passes the full conversation history + tool definitions to Gemini 2.5 Flash
4. Gemini decides whether to call one or more tools, or reply directly
5. If tools are needed, Flask spawns the MCP server as a subprocess and communicates via JSON-RPC over stdio
6. The MCP server executes the real operation (file I/O, SQL query, HTTP request, etc.) and returns the result
7. The result is fed back to Gemini, which continues reasoning until it has a final answer
8. The final response is returned to the browser and displayed

This **agentic loop** allows Cleo to chain multiple tool calls in a single turn — for example, searching the web and then saving the result to a file.

---

## 🛠️ MCP Tools

The MCP server exposes 11 tools across 4 categories:

### 📁 File System
| Tool | Description |
|------|-------------|
| `read_file` | Read the contents of a file |
| `write_file` | Create or overwrite a file (append mode supported) |
| `list_files` | List all files in the assistant's sandboxed folder |
| `delete_file` | Delete a file |

> All files are stored in `~/assistant_files/` — isolated from the rest of your system.

### 🔍 Web
| Tool | Description |
|------|-------------|
| `web_search` | Search DuckDuckGo — no API key required |
| `fetch_url` | Fetch and extract text from any public URL |

### 🗄️ Database (SQLite)
| Tool | Description |
|------|-------------|
| `db_query` | Run `SELECT` queries |
| `db_execute` | Run `INSERT`, `UPDATE`, `DELETE` |
| `db_schema` | Inspect the current table structure |

Three tables are created automatically on first run:

| Table | Fields |
|-------|--------|
| `notes` | id, title, content, created_at, updated_at |
| `tasks` | id, title, description, status, due_date, created_at |
| `contacts` | id, name, email, phone, notes, created_at |

### 🌐 External APIs
| Tool | Description |
|------|-------------|
| `get_weather` | Real-time weather + 3-day forecast via [Open-Meteo](https://open-meteo.com) |
| `get_datetime` | Current date, time and day of the week with timezone support |

---

## 🚀 Setup & Run

### Prerequisites

- **Python 3.10+** is required. Check with:
  ```bash
  python --version
  ```

  If you're on macOS and need to upgrade:
  ```bash
  brew install python@3.12
  python3.12 -m venv .venv
  source .venv/bin/activate
  ```

- A **Gemini API key** — free at [aistudio.google.com](https://aistudio.google.com) → **Get API key**

### Step 1 — Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/cleo-ai.git
cd cleo-ai
```

### Step 2 — Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Set your API key

```bash
export GEMINI_API_KEY="your-key-here"
```

Or create a `.env` file in the project root (never commit this):
```
GEMINI_API_KEY=your-key-here
```

### Step 5 — Run

```bash
python app.py
```

Then open [http://localhost:5001](http://localhost:5001) in your browser.

---

## 💬 Example prompts

```
"What time is it in Tokyo?"
"What's the weather like in Milan this week?"
"Search the web for the latest news on AI agents"
"Create a file called 'ideas.txt' and write down 5 startup ideas"
"Add a task: review the project proposal by Friday"
"Show me all my pending tasks"
"Add a contact: Luca Bianchi, luca@email.com, +39 333 1234567"
"Search for the price of NVIDIA stock and save it to a file"
```

---

## 📁 Project Structure

```
cleo-ai/
├── app.py                  # Flask backend — Gemini agentic loop
├── requirements.txt        # Python dependencies
├── README.md
├── .gitignore
├── mcp_server/
│   └── server.py           # MCP Server — all tool implementations
└── static/
    └── index.html          # Frontend — dark theme chat UI
```

---

## 🔧 Adding a New Tool

1. **Define it** — add an entry to `list_tools()` in `mcp_server/server.py`
2. **Implement it** — handle the tool name in `call_tool()` in the same file
3. **Register it** — add the definition to `TOOL_DEFINITIONS` in `app.py`

That's it. Gemini will automatically start using the new tool when relevant.

---

## ⚙️ Configuration

| Setting | Location | Default |
|---------|----------|---------|
| AI model | `app.py` → `model=` | `gemini-2.5-flash` |
| System prompt / personality | `app.py` → `SYSTEM_PROMPT` | Friendly Italian assistant |
| Port | `app.py` → `app.run(port=)` | `5001` |
| File storage path | `mcp_server/server.py` → `FILES_DIR` | `~/assistant_files/` |
| Conversation history length | `app.py` → `messages[-20:]` | Last 20 messages |

---

## 🗺️ Roadmap

- [ ] Support for multiple named sessions / conversations
- [ ] Calendar integration (Google Calendar)
- [ ] Email reading and drafting (Gmail)
- [ ] Voice input support
- [ ] Export conversations to Markdown or PDF
- [ ] Docker support for easy deployment
- [ ] Support for additional AI models (OpenAI, Anthropic)

---

<div align="center">
  <sub>Built by Matteo — powered by Google Gemini</sub>
</div>