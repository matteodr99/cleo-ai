"""
Backend Flask - Cleo
Uses Google Gemini API (google-genai SDK) + MCP Server
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from google import genai
from google.genai import types as genai_types

app = Flask(__name__, static_folder="static")
CORS(app)

MCP_SERVER_PATH = Path(__file__).parent / "mcp_server" / "server.py"

SYSTEM_PROMPT = """You are Cleo, an intelligent, organized, and conversational personal AI assistant.

ESSENTIAL PERSONALITY:
- Friendly, helpful, proactive - NOT repetitive, NOT robotic
- Every response must be DIFFERENT from the previous one, even if the topic is similar
- Vary the tone, length, and approach completely between responses
- Always be natural, like a real person conversing

TOOLS (USE THEM ACTIVELY):
- FILE: read_file, write_file, list_files, delete_file
- WEB: web_search, fetch_url (to search online)
- DB: db_query, db_execute, db_schema (notes, tasks, contacts)
- UTILITIES: get_weather, get_datetime

MANDATORY BEHAVIOR:
1. If I ask for information you can search online → USE web_search IMMEDIATELY
2. If I ask for time or weather → USE the appropriate tools
3. For limitations: Explain DIFFERENTLY each time. Never use the same phrase twice.
4. For suggestions: Propose CREATIVE and DIVERSE things, not standard formulas
5. Length: Sometimes short, sometimes long. Sometimes with emojis, sometimes not. Vary!
6. Style: Alternate between formal, casual, enthusiastic, reflective, friendly

GRAMMAR & LANGUAGE:
- Always respond in English
- Use natural contractions (i.e., anyway, rather than, etc.)
- Be colloquial when appropriate

NEVER DO:

- Repeat the same structure twice in a row
- Always start the same way ("I'm sorry that...", "Unfortunately...", "Hi!")
- Give template responses
- Be cold or formal when not needed
"""

TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read the content of a file",
        "parameters": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or create a text file",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean"},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in the assistant folder",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_file",
        "description": "Delete a file",
        "parameters": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web using DuckDuckGo",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch text content from a public web page",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}},
            "required": ["url"],
        },
    },
    {
        "name": "db_query",
        "description": "Run a SELECT query on the SQLite database",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "params": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
    },
    {
        "name": "db_execute",
        "description": "Run INSERT, UPDATE or DELETE on the database",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "params": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
    },
    {
        "name": "db_schema",
        "description": "Show the database table structure",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_weather",
        "description": "Get real-time weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
        },
    },
    {
        "name": "get_datetime",
        "description": "Get current date and time with timezone support",
        "parameters": {"type": "object", "properties": {"timezone": {"type": "string"}}},
    },
]

gemini_tools = [
    genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(
                name=t["name"],  # type: ignore[arg-type]
                description=t["description"],  # type: ignore[arg-type]
                parameters=t["parameters"],  # type: ignore[arg-type]
            )
            for t in TOOL_DEFINITIONS
        ]
    )
]

chat_sessions: dict[str, list] = {}


async def call_mcp_tool(tool_name: str, tool_input: dict) -> str:
    init_request = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "flask-client", "version": "1.0"},
        },
    }
    tool_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_input},
    }
    process = subprocess.Popen(
        [sys.executable, str(MCP_SERVER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        input_data = (
            json.dumps(init_request)
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            + "\n"
            + json.dumps(tool_request)
            + "\n"
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
                        return content[0].get("text", "No results")
            except json.JSONDecodeError:
                continue
        return "Tool executed."
    except subprocess.TimeoutExpired:
        process.kill()
        return f"Timeout in call to '{tool_name}'"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        process.terminate()


async def run_with_gemini(session_id: str, user_message: str) -> str:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []

    # Load all previous history
    history = chat_sessions[session_id].copy()
    history.append({"role": "user", "parts": [{"text": user_message}]})

    config = genai_types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=gemini_tools,  # type: ignore[arg-type]
        tool_config=genai_types.ToolConfig(
            function_calling_config=genai_types.FunctionCallingConfig(mode="AUTO")  # type: ignore[arg-type]
        ),
        temperature=1.0,
        top_p=0.95,
        top_k=40,
    )

    # Use the complete history
    messages = history.copy()

    while True:
        # Retry logic for generate_content
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash", contents=messages, config=config
                )
                break
            except Exception as e:
                error_msg = str(e)
                # If it's a rate limit error (429) or quota
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2**attempt)  # Exponential backoff
                        print(
                            f"⏳ Rate limit detected. Retry in {wait_time} seconds... (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                # If it's the last attempt, re-raise the error
                raise

        fn_calls = []
        for part in response.candidates[0].content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fn_calls.append(part.function_call)

        if not fn_calls:
            final_text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    final_text += part.text
            break

        messages.append(
            {
                "role": "model",
                "parts": [
                    {"function_call": {"name": fc.name, "args": dict(fc.args)}} for fc in fn_calls
                ],
            }
        )

        tool_result_parts = []
        for fc in fn_calls:
            result = await call_mcp_tool(fc.name, dict(fc.args))
            tool_result_parts.append(
                {"function_response": {"name": fc.name, "response": {"result": result}}}
            )

        messages.append({"role": "user", "parts": tool_result_parts})

    # Store the complete history (last 20 exchanges)
    chat_sessions[session_id] = messages[-20:]
    return final_text or "No response generated."


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
    print("🚀 Cleo started on http://localhost:5001")
    app.run(debug=True, port=5001)
