# ✦ Cleo — Personal AI Assistant

An AI chatbot with a web interface, powered by **Google Gemini** and a custom **MCP Server** written in Python.

---

## ⚠️ Prerequisites

- **Python 3.10 or higher** — the `mcp` package requires it. Check your version with:
  ```bash
  python --version
  ```
  If you're on an older version, install Python 3.12 via Homebrew (macOS):
  ```bash
  brew install python@3.12
  ```
  Then recreate your virtual environment:
  ```bash
  deactivate
  python3.12 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- A **Google Gemini API key** — get one for free at [aistudio.google.com](https://aistudio.google.com) → **Get API key**

---

## 🏗️ Architecture

```
┌─────────────────┐     HTTP      ┌─────────────────┐     stdio     ┌─────────────────┐
│   Browser       │ ────────────► │  Flask (app.py) │ ────────────► │  MCP Server     │
│  (index.html)   │ ◄──────────── │  + Gemini API   │ ◄──────────── │  (server.py)    │
└─────────────────┘               └─────────────────┘               └─────────────────┘
```

**Flow:**
1. The user types a message in the browser
2. Flask sends the message to Gemini with the tool definitions
3. Gemini decides which tools to use and calls them
4. Flask invokes the MCP Server via subprocess (JSON-RPC over stdio)
5. The MCP Server executes the real operations and returns the results
6. Gemini synthesizes the final response and displays it in the browser

---

## 🛠️ MCP Tools

### 📁 File System
| Tool | Description |
|------|-------------|
| `read_file` | Read the contents of a file |
| `write_file` | Create or write a file (append mode supported) |
| `list_files` | List all files in the assistant's folder |
| `delete_file` | Delete a file |

> Files are saved in `~/assistant_files/` (sandboxed directory)

### 🔍 Web Search
| Tool | Description |
|------|-------------|
| `web_search` | Search DuckDuckGo (no API key required) |
| `fetch_url` | Retrieve the text content of any public web page |

### 🗄️ SQLite Database
| Tool | Description |
|------|-------------|
| `db_query` | Run SELECT queries |
| `db_execute` | Run INSERT, UPDATE, DELETE |
| `db_schema` | Show the database table structure |

**Default tables:**
- `notes` — Personal notes (title, content, timestamp)
- `tasks` — Todo items (title, description, status, due date)
- `contacts` — Address book (name, email, phone, notes)

### 🌐 External APIs
| Tool | Description |
|------|-------------|
| `get_weather` | Real-time weather via Open-Meteo (free, no API key) |
| `get_datetime` | Current date and time with timezone support |

---

## 🚀 Setup & Run

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Gemini API key
```bash
export GEMINI_API_KEY="your-key-here"
```
Or create a `.env` file:
```
GEMINI_API_KEY=your-key-here
```

### 3. Start the server
```bash
python app.py
```

### 4. Open in browser
```
http://localhost:5000
```

---

## 💬 Example prompts

```
"What time is it in Rome?"
"What's the weather like in Milan tomorrow?"
"Create a file 'meeting_notes.txt' with today's discussion points"
"Add a note: 'Call the dentist on Monday'"
"Show all pending tasks"
"Add a contact: Mario Rossi, mario@email.com, 333-1234567"
"Search the web: latest AI news"
"Read the file meeting_notes.txt"
```

---

## 📁 Project structure

```
cleo-ai/
├── app.py                  # Flask backend + Gemini agent loop
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── mcp_server/
│   └── server.py           # MCP Server with all tools
└── static/
    └── index.html          # Web interface
```

---

## 🔧 Extending the project

To add a new tool to the MCP Server:

1. **Add the definition** in `list_tools()` inside `mcp_server/server.py`
2. **Implement the logic** in `call_tool()` in the same file
3. **Add the tool to the list** in `app.py` (the `TOOL_DEFINITIONS` array)

---

## ⚙️ Advanced configuration

You can customize Cleo's behavior by editing `SYSTEM_PROMPT` in `app.py`.

To use a different Gemini model, change the following line in `app.py`:
```python
model_name="gemini-2.0-flash",  # or gemini-1.5-pro, gemini-2.0-flash-lite, etc.
```

---

*Built with Google Gemini — AI Studio*
