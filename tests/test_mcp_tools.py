"""
Tests for the MCP Server tools.
Covers: file system, SQLite database, weather API, datetime, web search.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def isolated_files_dir(tmp_path, monkeypatch):
    """Redirect FILES_DIR and DB_PATH to a temp dir for every test."""
    import mcp_server.server as srv

    monkeypatch.setattr(srv, "FILES_DIR", tmp_path)
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "test_cleo.db")
    srv.init_database()
    return tmp_path


# ─────────────────────────────────────────────────────────────
# FILE SYSTEM TOOLS
# ─────────────────────────────────────────────────────────────


class TestFileTools:
    async def test_write_and_read_file(self):
        from mcp_server.server import call_tool

        await call_tool("write_file", {"filename": "hello.txt", "content": "Ciao Matteo!"})
        result = await call_tool("read_file", {"filename": "hello.txt"})
        assert "Ciao Matteo!" in result[0].text

    async def test_write_append_mode(self):
        from mcp_server.server import call_tool

        await call_tool("write_file", {"filename": "log.txt", "content": "line1\n"})
        await call_tool("write_file", {"filename": "log.txt", "content": "line2\n", "append": True})
        result = await call_tool("read_file", {"filename": "log.txt"})
        assert "line1" in result[0].text
        assert "line2" in result[0].text

    async def test_read_nonexistent_file(self):
        from mcp_server.server import call_tool

        result = await call_tool("read_file", {"filename": "ghost.txt"})
        assert "not found" in result[0].text.lower() or "non trovato" in result[0].text.lower()

    async def test_list_files_empty(self, isolated_files_dir):
        from mcp_server.server import call_tool

        # Remove db file created by fixture so the folder is truly empty
        db = isolated_files_dir / "test_cleo.db"
        if db.exists():
            db.unlink()
        result = await call_tool("list_files", {})
        assert "no files" in result[0].text.lower() or "nessun" in result[0].text.lower()

    async def test_list_files_after_write(self):
        from mcp_server.server import call_tool

        await call_tool("write_file", {"filename": "note.txt", "content": "test"})
        result = await call_tool("list_files", {})
        assert "note.txt" in result[0].text

    async def test_delete_file(self):
        from mcp_server.server import call_tool

        await call_tool("write_file", {"filename": "temp.txt", "content": "delete me"})
        result = await call_tool("delete_file", {"filename": "temp.txt"})
        assert "delet" in result[0].text.lower()
        result2 = await call_tool("read_file", {"filename": "temp.txt"})
        assert "not found" in result2[0].text.lower() or "non trovato" in result2[0].text.lower()

    async def test_delete_nonexistent_file(self):
        from mcp_server.server import call_tool

        result = await call_tool("delete_file", {"filename": "doesnotexist.txt"})
        assert "not found" in result[0].text.lower() or "non trovato" in result[0].text.lower()

    async def test_path_traversal_is_sandboxed(self):
        from mcp_server.server import FILES_DIR, call_tool

        await call_tool("write_file", {"filename": "../evil.txt", "content": "hack"})
        evil_path = FILES_DIR.parent / "evil.txt"
        assert not evil_path.exists()


# ─────────────────────────────────────────────────────────────
# DATABASE TOOLS
# ─────────────────────────────────────────────────────────────


class TestDatabaseTools:
    async def test_db_schema_returns_tables(self):
        from mcp_server.server import call_tool

        result = await call_tool("db_schema", {})
        text = result[0].text
        assert "notes" in text
        assert "tasks" in text
        assert "contacts" in text

    async def test_insert_and_query_note(self):
        from mcp_server.server import call_tool

        await call_tool(
            "db_execute",
            {
                "query": "INSERT INTO notes (title, content) VALUES (?, ?)",
                "params": ["Test Note", "This is a test"],
            },
        )
        result = await call_tool("db_query", {"query": "SELECT title, content FROM notes"})
        assert "Test Note" in result[0].text
        assert "This is a test" in result[0].text

    async def test_insert_and_query_task(self):
        from mcp_server.server import call_tool

        await call_tool(
            "db_execute",
            {
                "query": "INSERT INTO tasks (title, status) VALUES (?, ?)",
                "params": ["Buy milk", "pending"],
            },
        )
        result = await call_tool(
            "db_query",
            {"query": "SELECT title, status FROM tasks WHERE status = ?", "params": ["pending"]},
        )
        assert "Buy milk" in result[0].text

    async def test_update_task_status(self):
        from mcp_server.server import call_tool

        await call_tool(
            "db_execute",
            {
                "query": "INSERT INTO tasks (title, status) VALUES (?, ?)",
                "params": ["Write tests", "pending"],
            },
        )
        await call_tool(
            "db_execute",
            {
                "query": "UPDATE tasks SET status = ? WHERE title = ?",
                "params": ["done", "Write tests"],
            },
        )
        result = await call_tool(
            "db_query",
            {"query": "SELECT status FROM tasks WHERE title = ?", "params": ["Write tests"]},
        )
        assert "done" in result[0].text

    async def test_db_query_empty_table(self):
        from mcp_server.server import call_tool

        result = await call_tool("db_query", {"query": "SELECT * FROM contacts"})
        assert "no results" in result[0].text.lower() or "nessun" in result[0].text.lower()

    async def test_db_query_rejects_non_select(self):
        from mcp_server.server import call_tool

        result = await call_tool("db_query", {"query": "DELETE FROM notes"})
        assert "select" in result[0].text.lower() or "only" in result[0].text.lower()

    async def test_db_execute_rejects_drop(self):
        from mcp_server.server import call_tool

        result = await call_tool("db_execute", {"query": "DROP TABLE notes"})
        assert "not allowed" in result[0].text.lower() or "consentita" in result[0].text.lower()

    async def test_db_execute_rejects_truncate(self):
        from mcp_server.server import call_tool

        result = await call_tool("db_execute", {"query": "TRUNCATE TABLE tasks"})
        assert "not allowed" in result[0].text.lower() or "consentita" in result[0].text.lower()

    async def test_insert_contact(self):
        from mcp_server.server import call_tool

        await call_tool(
            "db_execute",
            {
                "query": "INSERT INTO contacts (name, email, phone) VALUES (?, ?, ?)",
                "params": ["Mario Rossi", "mario@email.com", "+39 333 1234567"],
            },
        )
        result = await call_tool("db_query", {"query": "SELECT name, email FROM contacts"})
        assert "Mario Rossi" in result[0].text
        assert "mario@email.com" in result[0].text


# ─────────────────────────────────────────────────────────────
# DATETIME TOOL
# ─────────────────────────────────────────────────────────────


class TestDatetimeTool:
    async def test_get_datetime_rome(self):
        from mcp_server.server import call_tool

        result = await call_tool("get_datetime", {"timezone": "Europe/Rome"})
        assert "Europe/Rome" in result[0].text or "UTC" in result[0].text

    async def test_get_datetime_utc(self):
        from mcp_server.server import call_tool

        result = await call_tool("get_datetime", {"timezone": "UTC"})
        assert "UTC" in result[0].text

    async def test_get_datetime_default(self):
        from mcp_server.server import call_tool

        result = await call_tool("get_datetime", {})
        assert any(c.isdigit() for c in result[0].text)

    async def test_get_datetime_invalid_timezone(self):
        from mcp_server.server import call_tool

        result = await call_tool("get_datetime", {"timezone": "Invalid/Zone"})
        assert result[0].text  # should not crash


# ─────────────────────────────────────────────────────────────
# WEATHER TOOL (mocked)
# ─────────────────────────────────────────────────────────────


class TestWeatherTool:
    @patch("urllib.request.urlopen")
    async def test_get_weather_by_city(self, mock_urlopen):
        from mcp_server.server import call_tool

        geo_response = json.dumps(
            {"results": [{"name": "Milan", "latitude": 45.46, "longitude": 9.19}]}
        ).encode()
        weather_response = json.dumps(
            {
                "current": {
                    "temperature_2m": 18.5,
                    "relative_humidity_2m": 65,
                    "wind_speed_10m": 12.3,
                    "weathercode": 1,
                },
                "daily": {
                    "time": ["2025-01-01", "2025-01-02", "2025-01-03"],
                    "temperature_2m_max": [20.0, 21.0, 19.0],
                    "temperature_2m_min": [10.0, 11.0, 9.0],
                    "weathercode": [1, 2, 3],
                },
            }
        ).encode()

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: s
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_cm.read = MagicMock(side_effect=[geo_response, weather_response])
        mock_urlopen.return_value = mock_cm

        result = await call_tool("get_weather", {"city": "Milan"})
        assert "Milan" in result[0].text or "18" in result[0].text

    @patch("urllib.request.urlopen")
    async def test_get_weather_city_not_found(self, mock_urlopen):
        from mcp_server.server import call_tool

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: s
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_cm.read = MagicMock(return_value=json.dumps({"results": []}).encode())
        mock_urlopen.return_value = mock_cm

        result = await call_tool("get_weather", {"city": "NonExistentCity12345"})
        assert "not found" in result[0].text.lower() or "non trovata" in result[0].text.lower()

    @patch("urllib.request.urlopen")
    async def test_get_weather_by_coordinates(self, mock_urlopen):
        from mcp_server.server import call_tool

        weather_response = json.dumps(
            {
                "current": {
                    "temperature_2m": 22.0,
                    "relative_humidity_2m": 50,
                    "wind_speed_10m": 8.0,
                    "weathercode": 0,
                },
                "daily": {
                    "time": ["2025-01-01"],
                    "temperature_2m_max": [25.0],
                    "temperature_2m_min": [15.0],
                    "weathercode": [0],
                },
            }
        ).encode()

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: s
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_cm.read = MagicMock(return_value=weather_response)
        mock_urlopen.return_value = mock_cm

        result = await call_tool("get_weather", {"latitude": 45.46, "longitude": 9.19})
        assert "22" in result[0].text or "°C" in result[0].text


# ─────────────────────────────────────────────────────────────
# WEB SEARCH TOOL (mocked)
# ─────────────────────────────────────────────────────────────


class TestWebSearchTool:
    @patch("urllib.request.urlopen")
    async def test_web_search_returns_results(self, mock_urlopen):
        from mcp_server.server import call_tool

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: s
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_cm.read = MagicMock(
            return_value=json.dumps(
                {
                    "AbstractText": "Python is a high-level programming language.",
                    "AbstractURL": "https://en.wikipedia.org/wiki/Python",
                    "RelatedTopics": [
                        {"Text": "Python programming language", "FirstURL": "https://python.org"},
                    ],
                }
            ).encode()
        )
        mock_urlopen.return_value = mock_cm

        result = await call_tool("web_search", {"query": "Python programming"})
        assert "Python" in result[0].text

    @patch("urllib.request.urlopen")
    async def test_web_search_no_results(self, mock_urlopen):
        from mcp_server.server import call_tool

        mock_cm = MagicMock()
        mock_cm.__enter__ = lambda s: s
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_cm.read = MagicMock(
            return_value=json.dumps(
                {"AbstractText": "", "AbstractURL": "", "RelatedTopics": []}
            ).encode()
        )
        mock_urlopen.return_value = mock_cm

        result = await call_tool("web_search", {"query": "xyzzy12345abcdef"})
        assert "no results" in result[0].text.lower() or "nessun" in result[0].text.lower()

    @patch("urllib.request.urlopen")
    async def test_web_search_error_handling(self, mock_urlopen):
        from mcp_server.server import call_tool

        mock_urlopen.side_effect = Exception("Network error")
        result = await call_tool("web_search", {"query": "test"})
        assert "error" in result[0].text.lower() or "errore" in result[0].text.lower()


# ─────────────────────────────────────────────────────────────
# UNKNOWN TOOL
# ─────────────────────────────────────────────────────────────


class TestUnknownTool:
    async def test_unknown_tool_returns_error(self):
        from mcp_server.server import call_tool

        result = await call_tool("nonexistent_tool", {})
        assert "unknown" in result[0].text.lower() or "non riconosciuto" in result[0].text.lower()
