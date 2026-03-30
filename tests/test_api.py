"""
Tests for Flask API endpoints.
Covers: /api/chat, /api/clear, /api/health, /
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as cleo_app


@pytest.fixture
def client(tmp_path):
    """Create a Flask test client with a clean state."""
    cleo_app.app.config["TESTING"] = True
    cleo_app.app.config["STATIC_FOLDER"] = str(tmp_path)
    # Create a minimal index.html so the / route works
    (tmp_path / "index.html").write_text("<html><body>Cleo</body></html>")
    cleo_app.chat_sessions.clear()
    with cleo_app.app.test_client() as c:
        yield c


# ─────────────────────────────────────────────────────────────
# HEALTH ENDPOINT
# ─────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert "mcp_server" in data


# ─────────────────────────────────────────────────────────────
# CHAT ENDPOINT
# ─────────────────────────────────────────────────────────────


class TestChatEndpoint:
    @patch("app.run_with_gemini", new_callable=AsyncMock)
    def test_chat_returns_response(self, mock_gemini, client):
        mock_gemini.return_value = "Ciao! Come posso aiutarti?"
        res = client.post("/api/chat", json={"message": "Ciao Cleo", "session_id": "test-session"})
        assert res.status_code == 200
        data = res.get_json()
        assert "response" in data
        assert data["response"] == "Ciao! Come posso aiutarti?"
        assert data["session_id"] == "test-session"

    def test_chat_empty_message_returns_400(self, client):
        res = client.post("/api/chat", json={"message": "", "session_id": "s1"})
        assert res.status_code == 400
        data = res.get_json()
        assert "error" in data

    def test_chat_whitespace_message_returns_400(self, client):
        res = client.post("/api/chat", json={"message": "   ", "session_id": "s1"})
        assert res.status_code == 400

    def test_chat_missing_message_returns_400(self, client):
        res = client.post("/api/chat", json={"session_id": "s1"})
        assert res.status_code == 400

    @patch("app.run_with_gemini", new_callable=AsyncMock)
    def test_chat_uses_default_session_id(self, mock_gemini, client):
        mock_gemini.return_value = "Risposta"
        res = client.post("/api/chat", json={"message": "Ciao"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["session_id"] == "default"

    @patch("app.run_with_gemini", new_callable=AsyncMock)
    def test_chat_gemini_exception_returns_500(self, mock_gemini, client):
        mock_gemini.side_effect = Exception("Gemini API error")
        res = client.post("/api/chat", json={"message": "Ciao", "session_id": "s1"})
        assert res.status_code == 500
        data = res.get_json()
        assert "error" in data

    @patch("app.run_with_gemini", new_callable=AsyncMock)
    def test_chat_preserves_session_between_calls(self, mock_gemini, client):
        mock_gemini.return_value = "Risposta 1"
        client.post("/api/chat", json={"message": "Primo", "session_id": "persist"})
        mock_gemini.return_value = "Risposta 2"
        client.post("/api/chat", json={"message": "Secondo", "session_id": "persist"})
        # Gemini should have been called twice with the same session
        assert mock_gemini.call_count == 2
        calls = [c.args[0] for c in mock_gemini.call_args_list]
        assert all(s == "persist" for s in calls)


# ─────────────────────────────────────────────────────────────
# CLEAR ENDPOINT
# ─────────────────────────────────────────────────────────────


class TestClearEndpoint:
    def test_clear_existing_session(self, client):
        cleo_app.chat_sessions["my-session"] = [{"role": "user", "parts": [{"text": "hi"}]}]
        res = client.post("/api/clear", json={"session_id": "my-session"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "cancellato"
        assert "my-session" not in cleo_app.chat_sessions

    def test_clear_nonexistent_session_is_safe(self, client):
        res = client.post("/api/clear", json={"session_id": "ghost-session"})
        assert res.status_code == 200

    def test_clear_default_session(self, client):
        cleo_app.chat_sessions["default"] = [{"role": "user", "parts": [{"text": "test"}]}]
        res = client.post("/api/clear", json={})
        assert res.status_code == 200
        assert "default" not in cleo_app.chat_sessions


# ─────────────────────────────────────────────────────────────
# TOOL DEFINITIONS
# ─────────────────────────────────────────────────────────────


class TestToolDefinitions:
    def test_all_expected_tools_are_defined(self):
        tool_names = {t["name"] for t in cleo_app.TOOL_DEFINITIONS}
        expected = {
            "read_file",
            "write_file",
            "list_files",
            "delete_file",
            "web_search",
            "fetch_url",
            "db_query",
            "db_execute",
            "db_schema",
            "get_weather",
            "get_datetime",
        }
        assert expected == tool_names

    def test_all_tools_have_required_fields(self):
        for tool in cleo_app.TOOL_DEFINITIONS:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool missing 'description': {tool}"
            assert "parameters" in tool, f"Tool missing 'parameters': {tool}"
            assert tool["description"], f"Tool '{tool['name']}' has empty description"

    def test_required_tools_have_required_parameters(self):
        tools_with_required = {
            "read_file": ["filename"],
            "write_file": ["filename", "content"],
            "delete_file": ["filename"],
            "web_search": ["query"],
            "fetch_url": ["url"],
            "db_query": ["query"],
            "db_execute": ["query"],
        }
        tool_map = {t["name"]: t for t in cleo_app.TOOL_DEFINITIONS}
        for tool_name, required_params in tools_with_required.items():
            tool = tool_map[tool_name]
            actual_required = tool["parameters"].get("required", [])
            for param in required_params:
                assert (
                    param in actual_required
                ), f"Tool '{tool_name}' missing required param '{param}'"

    def test_gemini_tools_object_is_built(self):
        assert cleo_app.gemini_tools is not None
        assert len(cleo_app.gemini_tools) == 1  # one Tool object with all declarations
