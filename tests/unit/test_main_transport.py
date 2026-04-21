"""Tests for CLI transport normalization and config propagation in __main__."""

import argparse
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from rootly_mcp_server.__main__ import _get_sorted_tool_names, get_server, main, normalize_transport


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("stdio", "stdio"),
        ("sse", "sse"),
        ("streamable-http", "streamable-http"),
        ("streamable", "streamable-http"),
        ("http", "streamable-http"),
        ("both", "both"),
        ("dual", "both"),
        ("dual-http", "both"),
        ("streamable+sse", "both"),
        ("sse+streamable", "both"),
    ],
)
def test_normalize_transport_supported_aliases(value: str, expected: str):
    assert normalize_transport(value) == expected


def test_normalize_transport_rejects_invalid_value():
    with pytest.raises(argparse.ArgumentTypeError):
        normalize_transport("invalid-transport")


def test_get_server_passes_write_tool_env_flag():
    with patch.dict(
        "os.environ",
        {"ROOTLY_MCP_ENABLE_WRITE_TOOLS": "true"},
        clear=True,
    ):
        with patch("rootly_mcp_server.__main__.create_rootly_mcp_server") as mock_create:
            get_server()

    assert mock_create.call_args is not None
    assert mock_create.call_args.kwargs["enable_write_tools"] is True


def test_get_server_passes_enabled_tools_env_flag():
    with patch.dict(
        "os.environ",
        {"ROOTLY_MCP_ENABLED_TOOLS": "list_incidents,getIncident"},
        clear=True,
    ):
        with patch("rootly_mcp_server.__main__.create_rootly_mcp_server") as mock_create:
            get_server()

    assert mock_create.call_args is not None
    assert mock_create.call_args.kwargs["enabled_tools"] == {"list_incidents", "getIncident"}


def test_get_server_defaults_self_hosted_to_read_only():
    with patch.dict("os.environ", {}, clear=True):
        with patch("rootly_mcp_server.__main__.create_rootly_mcp_server") as mock_create:
            get_server()

    assert mock_create.call_args is not None
    assert mock_create.call_args.kwargs["hosted"] is False
    assert mock_create.call_args.kwargs["enable_write_tools"] is False


def test_get_server_keeps_hosted_default_write_surface():
    with patch.dict("os.environ", {"ROOTLY_HOSTED": "true"}, clear=True):
        with patch("rootly_mcp_server.__main__.create_rootly_mcp_server") as mock_create:
            get_server()

    assert mock_create.call_args is not None
    assert mock_create.call_args.kwargs["hosted"] is True
    assert mock_create.call_args.kwargs["enable_write_tools"] is True


@pytest.mark.asyncio
async def test_get_sorted_tool_names_returns_sorted_names():
    server = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=[
                SimpleNamespace(name="getIncident"),
                SimpleNamespace(name="createIncident"),
                SimpleNamespace(name="listTeams"),
            ]
        )
    )

    names = await _get_sorted_tool_names(server)

    assert names == ["createIncident", "getIncident", "listTeams"]


def test_main_list_tools_prints_effective_tool_names_and_exits(capsys):
    args = SimpleNamespace(
        swagger_path=None,
        log_level="ERROR",
        name="Rootly",
        transport="stdio",
        debug=False,
        base_url=None,
        allowed_paths=None,
        hosted=False,
        enable_code_mode=False,
        enable_write_tools=False,
        enabled_tools=None,
        list_tools=True,
        code_mode_path=None,
        host=False,
    )
    fake_server = object()

    def fake_asyncio_run(coro):
        coro.close()
        return ["get_server_version", "list_incidents"]

    with patch("rootly_mcp_server.__main__.parse_args", return_value=args):
        with patch("rootly_mcp_server.__main__.setup_logging"):
            with patch("rootly_mcp_server.__main__.check_api_token"):
                with patch(
                    "rootly_mcp_server.__main__.create_rootly_mcp_server", return_value=fake_server
                ):
                    with patch(
                        "rootly_mcp_server.__main__.asyncio.run",
                        side_effect=fake_asyncio_run,
                    ) as mock_run:
                        main()

    assert mock_run.call_count == 1
    assert capsys.readouterr().out.splitlines() == ["get_server_version", "list_incidents"]
