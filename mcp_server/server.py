"""
MCP Server - Cleo
Tools: file system, web search, SQLite, external APIs
"""

import asyncio
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("cleo")

FILES_DIR = Path(os.path.expanduser("~")) / "assistant_files"
FILES_DIR.mkdir(exist_ok=True)

DB_PATH = FILES_DIR / "cleo.db"


def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            due_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
    )
    conn.commit()
    conn.close()


init_database()


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_file",
            description="Read the content of a text file",
            inputSchema={
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        ),
        types.Tool(
            name="write_file",
            description="Write or create a text file",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean"},
                },
                "required": ["filename", "content"],
            },
        ),
        types.Tool(
            name="list_files",
            description="List files in the assistant folder",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="delete_file",
            description="Delete a file",
            inputSchema={
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        ),
        types.Tool(
            name="web_search",
            description="Search the web using DuckDuckGo",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                "required": ["query"],
            },
        ),
        types.Tool(
            name="fetch_url",
            description="Fetch text content from a public web page",
            inputSchema={
                "type": "object",
                "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}},
                "required": ["url"],
            },
        ),
        types.Tool(
            name="db_query",
            description="Run a SELECT query on the database",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "params": {"type": "array"}},
                "required": ["query"],
            },
        ),
        types.Tool(
            name="db_execute",
            description="Run INSERT, UPDATE or DELETE on the database",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "params": {"type": "array"}},
                "required": ["query"],
            },
        ),
        types.Tool(
            name="db_schema",
            description="Show the database table structure",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_weather",
            description="Get real-time weather for a city",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                },
            },
        ),
        types.Tool(
            name="get_datetime",
            description="Get current date and time",
            inputSchema={"type": "object", "properties": {"timezone": {"type": "string"}}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "read_file":
        filepath = FILES_DIR / Path(arguments["filename"]).name
        if not filepath.exists():
            return [
                types.TextContent(type="text", text=f"File '{arguments['filename']}' not found.")
            ]
        return [types.TextContent(type="text", text=filepath.read_text(encoding="utf-8"))]

    elif name == "write_file":
        filepath = FILES_DIR / Path(arguments["filename"]).name
        append = arguments.get("append", False)
        existing = filepath.read_text(encoding="utf-8") if append and filepath.exists() else ""
        filepath.write_text(existing + arguments["content"], encoding="utf-8")
        return [
            types.TextContent(
                type="text",
                text=f"File '{arguments['filename']}' written ({filepath.stat().st_size} bytes).",
            )
        ]

    elif name == "list_files":
        files = list(FILES_DIR.iterdir())
        if not files:
            return [types.TextContent(type="text", text="No files found.")]
        return [
            types.TextContent(
                type="text",
                text="\n".join(f"{f.name} ({f.stat().st_size}B)" for f in sorted(files)),
            )
        ]

    elif name == "delete_file":
        filepath = FILES_DIR / Path(arguments["filename"]).name
        if not filepath.exists():
            return [
                types.TextContent(type="text", text=f"File '{arguments['filename']}' not found.")
            ]
        filepath.unlink()
        return [types.TextContent(type="text", text=f"File '{arguments['filename']}' deleted.")]

    elif name == "web_search":
        query = arguments["query"]
        max_results = arguments.get("max_results", 5)
        try:
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            results = []
            if data.get("AbstractText"):
                results.append(f"Summary: {data['AbstractText']}\n{data.get('AbstractURL', '')}")
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(f"- {topic['Text']}\n  {topic.get('FirstURL', '')}")
            return [
                types.TextContent(
                    type="text",
                    text="\n\n".join(results) if results else f"No results for '{query}'.",
                )
            ]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Search error: {str(e)}")]

    elif name == "fetch_url":
        try:
            req = urllib.request.Request(arguments["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            import re

            text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            max_chars = arguments.get("max_chars", 3000)
            return [types.TextContent(type="text", text=text[:max_chars])]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Fetch error: {str(e)}")]

    elif name == "db_query":
        if not arguments["query"].strip().upper().startswith("SELECT"):
            return [types.TextContent(type="text", text="Only SELECT queries allowed.")]
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(arguments["query"], arguments.get("params", []))
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return [types.TextContent(type="text", text="No results.")]
            cols = rows[0].keys()
            result = (
                " | ".join(cols)
                + "\n"
                + "\n".join(" | ".join(str(row[c]) for c in cols) for row in rows)
            )
            return [types.TextContent(type="text", text=result)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"SQL error: {str(e)}")]

    elif name == "db_execute":
        if any(kw in arguments["query"].upper() for kw in ["DROP", "TRUNCATE", "ALTER"]):
            return [types.TextContent(type="text", text="Operation not allowed.")]
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(arguments["query"], arguments.get("params", []))
            conn.commit()
            result = f"Done. Rows affected: {cursor.rowcount}, Last ID: {cursor.lastrowid}"
            conn.close()
            return [types.TextContent(type="text", text=result)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"SQL error: {str(e)}")]

    elif name == "db_schema":
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            parts = []
            for table in tables:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = ", ".join(f"{c[1]} {c[2]}" for c in cursor.fetchall())
                parts.append(f"{table}: {cols}")
            conn.close()
            return [types.TextContent(type="text", text="\n".join(parts))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    elif name == "get_weather":
        city = arguments.get("city", "")
        lat = arguments.get("latitude")
        lon = arguments.get("longitude")
        try:
            if city and not (lat and lon):
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
                req = urllib.request.Request(geo_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    geo = json.loads(resp.read().decode())
                if not geo.get("results"):
                    return [types.TextContent(type="text", text=f"City '{city}' not found.")]
                r = geo["results"][0]
                lat, lon, city = r["latitude"], r["longitude"], r["name"]
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weathercode&daily=temperature_2m_max,temperature_2m_min,weathercode&timezone=auto&forecast_days=3"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                w = json.loads(resp.read().decode())
            c = w["current"]
            d = w["daily"]
            wmo = {
                0: "Clear",
                1: "Mostly clear",
                2: "Partly cloudy",
                3: "Overcast",
                45: "Foggy",
                61: "Rain",
                71: "Snow",
                80: "Showers",
                95: "Thunderstorm",
            }
            result = f"Weather in {city}:\n{c['temperature_2m']}°C, {wmo.get(c['weathercode'], str(c['weathercode']))}, Humidity: {c['relative_humidity_2m']}%, Wind: {c['wind_speed_10m']} km/h\n\nForecast:\n"
            for i in range(min(3, len(d["time"]))):
                result += f"{d['time'][i]}: {d['temperature_2m_min'][i]}°C → {d['temperature_2m_max'][i]}°C, {wmo.get(d['weathercode'][i], '')}\n"
            return [types.TextContent(type="text", text=result)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Weather error: {str(e)}")]

    elif name == "get_datetime":
        tz_name = arguments.get("timezone", "Europe/Rome")
        try:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(tz_name)
            now = datetime.now(tz)
            return [
                types.TextContent(
                    type="text",
                    text=f"Date: {now.strftime('%d/%m/%Y')}\nTime: {now.strftime('%H:%M:%S')}\nDay: {now.strftime('%A')}\nTimezone: {tz_name} (UTC{now.strftime('%z')})",
                )
            ]
        except Exception:
            now = datetime.utcnow()
            return [
                types.TextContent(type="text", text=f"UTC: {now.strftime('%d/%m/%Y %H:%M:%S')}")
            ]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
