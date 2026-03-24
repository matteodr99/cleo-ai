"""
Backend Flask - Cleo
Uses Google Gemini API + MCP Server
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__, static_folder="static")
CORS(app)

# Configure Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

MCP_SERVER_PATH = Path(__file__).parent / "mcp_server" / "server.py"

SYSTEM_PROMPT = """You are Cleo, a smart and organized personal AI assistant.

You have access to the following tools via the MCP server:

FILE SYSTEM: read_file, write_file, list_files, delete_file
WEB SEARCH: web_search, fetch_url
DATABASE (SQLite): db_query, db_execute, db_schema
  Tables: notes, tasks, contacts
EXTERNAL APIs: get_weather, get_datetime

Always use the appropriate tools to answer requests.
Be proactive, helpful, and concise. Respond in the same language the user writes in.
"""

# Tool definitions for Gemini
TOOL_DEFINITIONS = [
    {"name": "read_file", "description": "Read the content of a file", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}},
    {"name": "write_file", "description": "Write or create a text file", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}}, "required": ["filename", "content"]}},
    {"name": "list_files", "description": "List files in the assistant folder", "parameters": {"type": "object", "properties": {}}},
    {"name": "delete_file", "description": "Delete a file", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}},
    {"name": "web_search", "description": "Search the web using DuckDuckGo", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}},
    {"name": "fetch_url", "description": "Fetch text content from a public web page", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]}},
    {"name": "db_query", "description": "Run a SELECT query on the SQLite database", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "params": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]}},
    {"name": "db_execute", "description": "Run INSERT, UPDATE or DELETE on the database", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "params": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]}},
    {"name": "db_schema", "description": "Show the database table structure", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_weather", "description": "Get real-time weather for a city", "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "latitude": {"type": "number"}, "longitude": {"type": "number"}}}},
    {"name": "get_datetime", "description": "Get current date and time with timezone support", "parameters": {"type": "object", "properties": {"timezone": {"type": "string"}}}},
]

# Build Gemini tools format
gemini_tools = [genai.protos.Tool(
    function_declarations=[
        genai.protos.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    k: genai.protos.Schema(
                        type=genai.protos.Type.STRING if v.get("type") == "string"
                             else genai.protos.Type.NUMBER if v.get("type") in ("number", "integer")
                             else genai.protos.Type.BOOLEAN if v.get("type") == "boolean"
                             else genai.protos.Type.ARRAY if v.get("type") == "array"
                             else genai.protos.Type.STRING,
                        description=v.get("description", "")
                    )
                    for k, v in t["parameters"].get("properties", {}).items()
                },
                required=t["parameters"].get("required", [])
            )
        )
        for t in TOOL_DEFINITIONS
    ]
)]

# Chat sessions (in-memory)
chat_sessions: dict[str, list] = {}


async def call_mcp_tool(tool_name: str, tool_input: dict) -> str:
    """Call a tool on the MCP server via subprocess JSON-RPC."""
    init_request = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "flask-client", "version": "1.0"}}}
    tool_request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": tool_input}}

    process = subprocess.Popen(
        [sys.executable, str(MCP_SERVER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        input_data = (
            json.dumps(init_request) + "\n" +
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n" +
            json.dumps(tool_request) + "\n"
        )
        stdout, _ = process.communicate(input=input_data.encode(), timeout=15)

        for line in stdout.decode().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == 1:
                    content = resp.get("result", {}).get("content", [])
                    if content:
                        return content[0].get("text", "No result")
            except json.JSONDecodeError:
                continue
        return "Tool executed."
    except subprocess.TimeoutExpired:
        process.kill()
        return f"Timeout calling '{tool_name}'"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        process.terminate()


async def run_with_gemini(session_id: str, user_message: str) -> str:
    """Run Gemini with MCP tools in an agentic loop."""

    if session_id not in chat_sessions:
        chat_sessions[session_id] = []

    history = chat_sessions[session_id].copy()

    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=SYSTEM_PROMPT,
        tools=gemini_tools,
    )

    chat = model.start_chat(history=history)

    # Agentic loop
    response = chat.send_message(user_message)

    while True:
        # Check for function calls
        fn_calls = []
        for part in response.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                fn_calls.append(part.function_call)

        if not fn_calls:
            break

        # Execute all tool calls
        tool_responses = []
        for fn_call in fn_calls:
            tool_name = fn_call.name
            tool_args = dict(fn_call.args)
            result = await call_mcp_tool(tool_name, tool_args)
            tool_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=tool_name,
                        response={"result": result}
                    )
                )
            )

        # Send tool results back
        response = chat.send_message(tool_responses)

    # Extract final text
    final_text = ""
    for part in response.parts:
        if hasattr(part, "text") and part.text:
            final_text += part.text

    # Update session history
    chat_sessions[session_id] = list(chat.history)
    if len(chat_sessions[session_id]) > 20:
        chat_sessions[session_id] = chat_sessions[session_id][-20:]

    return final_text or "No response generated."


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    session_id = data.get("session_id", "default")
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400
    try:
        response = asyncio.run(run_with_gemini(session_id, user_message))
        return jsonify({"response": response, "session_id": session_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/clear", methods=["POST"])
def clear_session():
    data = request.json
    session_id = data.get("session_id", "default")
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    return jsonify({"status": "cleared"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "mcp_server": str(MCP_SERVER_PATH.exists())})

if __name__ == "__main__":
    print("🚀 Cleo avviato su http://localhost:5000")
    app.run(debug=True, port=5000)
