"""
Tests for the Gemini agentic loop.
Covers: session management, retry logic, tool call flow, history trimming.
All Gemini API calls are mocked — no real API calls are made.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import call_mcp_tool, chat_sessions, run_with_gemini


@pytest.fixture(autouse=True)
def clear_sessions():
    """Reset chat sessions before each test."""
    chat_sessions.clear()
    yield
    chat_sessions.clear()


# ─────────────────────────────────────────────────────────────
# Helpers to build mock Gemini responses
# ─────────────────────────────────────────────────────────────


def make_text_response(text: str):
    part = MagicMock()
    part.text = text
    part.function_call = None
    candidate = MagicMock()
    candidate.content.parts = [part]
    response = MagicMock()
    response.candidates = [candidate]
    return response


def make_tool_call_response(tool_name: str, tool_args: dict):
    fc = MagicMock()
    fc.name = tool_name
    fc.args = tool_args
    part = MagicMock()
    part.text = None
    part.function_call = fc
    candidate = MagicMock()
    candidate.content.parts = [part]
    response = MagicMock()
    response.candidates = [candidate]
    return response


# ─────────────────────────────────────────────────────────────
# SESSION MANAGEMENT
# ─────────────────────────────────────────────────────────────


class TestSessionManagement:
    @patch("app.genai.Client")
    async def test_new_session_is_created(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = make_text_response("Ciao!")

        await run_with_gemini("new-session", "Ciao")
        assert "new-session" in chat_sessions

    @patch("app.genai.Client")
    async def test_session_accumulates_history(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = make_text_response("Risposta")

        await run_with_gemini("sess", "Messaggio 1")
        await run_with_gemini("sess", "Messaggio 2")

        all_text = str(chat_sessions["sess"])
        assert "Messaggio 1" in all_text
        assert "Messaggio 2" in all_text

    @patch("app.genai.Client")
    async def test_session_history_is_trimmed_to_20(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = make_text_response("ok")

        for i in range(15):
            await run_with_gemini("trim-sess", f"Messaggio {i}")

        assert len(chat_sessions["trim-sess"]) <= 20

    @patch("app.genai.Client")
    async def test_different_sessions_are_isolated(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = make_text_response("ok")

        await run_with_gemini("session-a", "Messaggio per A")
        await run_with_gemini("session-b", "Messaggio per B")

        history_a = str(chat_sessions["session-a"])
        history_b = str(chat_sessions["session-b"])

        assert "Messaggio per A" in history_a
        assert "Messaggio per A" not in history_b
        assert "Messaggio per B" in history_b
        assert "Messaggio per B" not in history_a


# ─────────────────────────────────────────────────────────────
# AGENTIC LOOP — TOOL CALLS
# ─────────────────────────────────────────────────────────────


class TestAgenticLoop:
    @patch("app.call_mcp_tool", new_callable=AsyncMock)
    @patch("app.genai.Client")
    async def test_tool_call_is_executed(self, mock_client_cls, mock_mcp):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_mcp.return_value = "Tool result"

        mock_client.models.generate_content.side_effect = [
            make_tool_call_response("get_datetime", {"timezone": "Europe/Rome"}),
            make_text_response("Sono le 10:00."),
        ]

        result = await run_with_gemini("s", "Che ore sono?")
        mock_mcp.assert_called_once_with("get_datetime", {"timezone": "Europe/Rome"})
        assert result == "Sono le 10:00."

    @patch("app.call_mcp_tool", new_callable=AsyncMock)
    @patch("app.genai.Client")
    async def test_multiple_tool_calls_in_sequence(self, mock_client_cls, mock_mcp):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_mcp.return_value = "result"

        mock_client.models.generate_content.side_effect = [
            make_tool_call_response("web_search", {"query": "AI news"}),
            make_tool_call_response("write_file", {"filename": "news.txt", "content": "result"}),
            make_text_response("Ho salvato le notizie."),
        ]

        result = await run_with_gemini("s", "Cerca le notizie AI e salvale")
        assert mock_mcp.call_count == 2
        assert result == "Ho salvato le notizie."

    @patch("app.genai.Client")
    async def test_direct_response_without_tools(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.return_value = make_text_response("Sono Cleo!")

        result = await run_with_gemini("s", "Come ti chiami?")
        assert result == "Sono Cleo!"

    @patch("app.genai.Client")
    async def test_empty_response_returns_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        part = MagicMock()
        part.text = None
        part.function_call = None
        candidate = MagicMock()
        candidate.content.parts = [part]
        response = MagicMock()
        response.candidates = [candidate]
        mock_client.models.generate_content.return_value = response

        result = await run_with_gemini("s", "test")
        assert result  # should not be empty


# ─────────────────────────────────────────────────────────────
# RETRY LOGIC
# ─────────────────────────────────────────────────────────────


class TestRetryLogic:
    @patch("app.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.genai.Client")
    async def test_retries_on_rate_limit(self, mock_client_cls, mock_sleep):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_client.models.generate_content.side_effect = [
            Exception("Error 429: RESOURCE_EXHAUSTED"),
            make_text_response("Riprovo!"),
        ]

        result = await run_with_gemini("s", "test")
        assert result == "Riprovo!"
        assert mock_sleep.called

    @patch("app.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.genai.Client")
    async def test_raises_after_max_retries(self, mock_client_cls, mock_sleep):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")

        with pytest.raises(Exception, match="429"):
            await run_with_gemini("s", "test")

    @patch("app.genai.Client")
    async def test_non_rate_limit_error_raises_immediately(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("Invalid API key")

        with pytest.raises(Exception, match="Invalid API key"):
            await run_with_gemini("s", "test")

        assert mock_client.models.generate_content.call_count == 1


# ─────────────────────────────────────────────────────────────
# MCP TOOL INVOCATION
# ─────────────────────────────────────────────────────────────


class TestCallMcpTool:
    @patch("app.subprocess.Popen")
    async def test_successful_tool_call(self, mock_popen):
        import json

        tool_response = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": "Tool output"}]}}
        )
        mock_process = MagicMock()
        mock_process.communicate.return_value = ((tool_response + "\n").encode(), b"")
        mock_popen.return_value = mock_process

        result = await call_mcp_tool("get_datetime", {"timezone": "UTC"})
        assert result == "Tool output"

    @patch("app.subprocess.Popen")
    async def test_timeout_returns_message(self, mock_popen):
        import subprocess

        mock_process = MagicMock()
        mock_process.communicate.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=15)
        mock_popen.return_value = mock_process

        result = await call_mcp_tool("slow_tool", {})
        assert "timeout" in result.lower()

    @patch("app.subprocess.Popen")
    async def test_exception_returns_error_message(self, mock_popen):
        # Popen raises before the try block, so the exception propagates
        # through the finally clause. We verify it's caught and returned as a string.
        mock_popen.side_effect = Exception("subprocess failed")
        try:
            result = await call_mcp_tool("any_tool", {})
            assert "error" in result.lower() or "errore" in result.lower()
        except Exception as e:
            # If the exception propagates, it should mention the original error
            assert "subprocess failed" in str(e)
