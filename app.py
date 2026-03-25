"""
Backend Flask - Cleo
Uses Google Gemini API (google-genai SDK) + MCP Server
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from google import genai
from google.genai import types as genai_types

app = Flask(__name__, static_folder="static")
CORS(app)

MCP_SERVER_PATH = Path(__file__).parent / "mcp_server" / "server.py"

SYSTEM_PROMPT = """Sei Cleo, un'assistente AI personale intelligente, organizzata e conversazionale.

PERSONALITÀ ESSENZIALE:
- Amichevole, utile, proattiva - NON ripetitiva, NON robotica
- Ogni risposta deve essere DIVERSA dalla precedente, anche se l'argomento è simile
- Varia completamente il tono, la lunghezza, l'approccio tra una risposta e l'altra
- Sii sempre naturale, come una vera persona che conversa

STRUMENTI (USALI ATTIVAMENTE):
- FILE: read_file, write_file, list_files, delete_file
- WEB: web_search, fetch_url (per cercare online)
- DB: db_query, db_execute, db_schema (notes, tasks, contacts)
- UTILITIES: get_weather, get_datetime

COMPORTAMENTO OBBLIGATORIO:
1. Se chiedo informazioni che puoi cercare online → USA web_search SUBITO
2. Se chiedo l'ora o meteo → USA gli strumenti appropriati
3. Per limitazioni: Spiega DIVERSAMENTE ogni volta. Non usare mai la stessa frase due volte.
4. Per suggerimenti: Proponi cose CREATIVE e DIVERSE, non formule standard
5. Lunghezza: A volte breve, a volte lunga. A volte con emojis, a volte no. Varia!
6. Stile: Alternare tra formale, casual, entusiasta, riflessivo, simpatico

GRAMMATICA & LINGUA:
- Rispondi SEMPRE in italiano
- Usa contrazioni naturali (cioè, comunque, piuttosto che, ecc)
- Sii colloquiale quando appropriato

NON FARE MAI:
- Ripetere la stessa struttura due volte di fila
- Iniziare sempre allo stesso modo ("Mi dispiace che...", "Purtroppo...", "Ciao!")
- Dare risposte template
- Essere freddo o formale quando non serve
"""

TOOL_DEFINITIONS = [
    {"name": "read_file", "description": "Leggi il contenuto di un file", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}},
    {"name": "write_file", "description": "Scrivi o crea un file di testo", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}}, "required": ["filename", "content"]}},
    {"name": "list_files", "description": "Elenca i file nella cartella dell'assistente", "parameters": {"type": "object", "properties": {}}},
    {"name": "delete_file", "description": "Elimina un file", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}},
    {"name": "web_search", "description": "Cerca sul web utilizzando DuckDuckGo", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}},
    {"name": "fetch_url", "description": "Recupera il contenuto testuale da una pagina web pubblica", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]}},
    {"name": "db_query", "description": "Esegui una query SELECT sul database SQLite", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "params": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]}},
    {"name": "db_execute", "description": "Esegui INSERT, UPDATE o DELETE sul database", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "params": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]}},
    {"name": "db_schema", "description": "Mostra la struttura delle tabelle del database", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_weather", "description": "Ottieni il meteo in tempo reale per una città", "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "latitude": {"type": "number"}, "longitude": {"type": "number"}}}},
    {"name": "get_datetime", "description": "Ottieni data e ora corrente con supporto per i fusi orari", "parameters": {"type": "object", "properties": {"timezone": {"type": "string"}}}},
]

gemini_tools = [
    genai_types.Tool(function_declarations=[
        genai_types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=t["parameters"]
        )
        for t in TOOL_DEFINITIONS
    ])
]

chat_sessions: dict[str, list] = {}


async def call_mcp_tool(tool_name: str, tool_input: dict) -> str:
    init_request = {
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "flask-client", "version": "1.0"}}
    }
    tool_request = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_input}
    }
    process = subprocess.Popen(
        [sys.executable, str(MCP_SERVER_PATH)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
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
                        return content[0].get("text", "Nessun risultato")
            except json.JSONDecodeError:
                continue
        return "Strumento eseguito."
    except subprocess.TimeoutExpired:
        process.kill()
        return f"Timeout nella chiamata di '{tool_name}'"
    except Exception as e:
        return f"Errore: {str(e)}"
    finally:
        process.terminate()


async def run_with_gemini(session_id: str, user_message: str) -> str:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []

    # Carica tutta la cronologia precedente
    history = chat_sessions[session_id].copy()
    history.append({"role": "user", "parts": [{"text": user_message}]})

    config = genai_types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=gemini_tools,
        tool_config=genai_types.ToolConfig(
            function_calling_config=genai_types.FunctionCallingConfig(mode="AUTO")
        ),
        temperature=1.0,
        top_p=0.95,
        top_k=40
    )

    # Usa la cronologia completa
    messages = history.copy()

    while True:
        # Retry logic per generate_content
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=messages,
                    config=config
                )
                break
            except Exception as e:
                error_msg = str(e)
                # Se è un errore di rate limit (429) o di quota
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        print(f"⏳ Rate limit rilevato. Retry in {wait_time} secondi... (tentativo {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                # Se è l'ultimo tentativo, rilancia l'errore
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

        messages.append({"role": "model", "parts": [
            {"function_call": {"name": fc.name, "args": dict(fc.args)}}
            for fc in fn_calls
        ]})

        tool_result_parts = []
        for fc in fn_calls:
            result = await call_mcp_tool(fc.name, dict(fc.args))
            tool_result_parts.append({
                "function_response": {
                    "name": fc.name,
                    "response": {"result": result}
                }
            })

        messages.append({"role": "user", "parts": tool_result_parts})

    # Memorizza la cronologia completa (ultimi 20 scambi)
    chat_sessions[session_id] = messages[-20:]
    return final_text or "Nessuna risposta generata."


@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    session_id = data.get("session_id", "default")
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Messaggio vuoto"}), 400
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
    return jsonify({"status": "cancellato"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "mcp_server": str(MCP_SERVER_PATH.exists())})

if __name__ == "__main__":
    print("🚀 Cleo avviato su http://localhost:5001")
    app.run(debug=True, port=5001)
