"""Tests for the ChatGPT app-aware Rootly tools and widget resource."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from rootly_mcp_server.server import create_rootly_mcp_server
from rootly_mcp_server.tools.chatgpt_app import (
    APP_RESOURCE_MIME,
    APP_RESOURCE_URI,
    register_chatgpt_app_tools,
)


class FakeMCPApp:
    """Minimal registry that captures tool and resource metadata."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}
        self.tool_options: dict[str, dict[str, Any]] = {}
        self.resources: dict[str, Any] = {}
        self.resource_options: dict[str, dict[str, Any]] = {}

    def tool(self, name: str | None = None, **kwargs: Any):
        def decorator(fn):
            tool_name = name or fn.__name__
            self.tools[tool_name] = fn
            self.tool_options[tool_name] = kwargs
            return fn

        return decorator

    def resource(self, uri: str, **kwargs: Any):
        def decorator(fn):
            self.resources[uri] = fn
            self.resource_options[uri] = kwargs
            return fn

        return decorator


class FakeMCPError:
    """Minimal error helper for app tool tests."""

    @staticmethod
    def categorize_error(exception: Exception) -> tuple[str, str]:
        return (exception.__class__.__name__, str(exception))


@pytest.mark.unit
class TestChatGPTAppToolRegistration:
    """Direct registration tests for app-aware tools and resources."""

    def _register(self):
        mcp = FakeMCPApp()
        request = AsyncMock()
        register_chatgpt_app_tools(
            mcp=mcp,
            make_authenticated_request=request,
            strip_heavy_nested_data=lambda data: data,
            mcp_error=FakeMCPError(),
        )
        return mcp, request

    @pytest.mark.asyncio
    async def test_registers_workbench_resource_with_widget_meta(self):
        mcp, _ = self._register()

        assert APP_RESOURCE_URI in mcp.resources
        resource_result = await mcp.resources[APP_RESOURCE_URI]()
        content = resource_result.contents[0]

        assert mcp.resource_options[APP_RESOURCE_URI]["mime_type"] == APP_RESOURCE_MIME
        assert content.mime_type == APP_RESOURCE_MIME
        assert "Rootly Incident Workbench" in content.content
        assert content.meta["openai/widgetDescription"].startswith("A visual Rootly incident workspace")
        assert content.meta["ui"]["prefersBorder"] is True

    @pytest.mark.asyncio
    async def test_workbench_tool_uses_structured_filters_and_returns_structured_content(self):
        mcp, request = self._register()

        team_response = Mock()
        team_response.raise_for_status.return_value = None
        team_response.json.return_value = {
            "data": [
                {
                    "id": "team-infra",
                    "attributes": {"name": "Infrastructure", "slug": "infrastructure"},
                }
            ]
        }

        incidents_response = Mock()
        incidents_response.raise_for_status.return_value = None
        incidents_response.json.return_value = {
            "data": [
                {
                    "id": "inc-123",
                    "type": "incidents",
                    "attributes": {
                        "sequential_id": 829,
                        "title": "Database timeout in production",
                        "summary": "Primary database connection pool exhausted",
                        "status": "resolved",
                        "severity": {
                            "data": {"attributes": {"name": "Critical", "slug": "critical"}}
                        },
                        "started_at": "2026-04-10T15:00:00Z",
                        "resolved_at": "2026-04-10T15:45:00Z",
                        "created_at": "2026-04-10T15:00:10Z",
                        "updated_at": "2026-04-10T15:46:00Z",
                        "retrospective_progress_status": "active",
                        "url": "https://rootly.com/account/incidents/inc-123",
                    },
                }
            ],
            "meta": {"total_count": 1, "next_page": None},
        }

        request.side_effect = [team_response, incidents_response]

        result = await mcp.tools["open_rootly_incident_workbench"](
            teams="Infrastructure",
            severity="critical",
            status="resolved",
            started_after="2026-04-01T00:00:00Z",
            started_before="2026-04-13T23:59:59Z",
            max_results=10,
        )

        assert result.structured_content["view"] == "incident_workbench"
        assert result.structured_content["incidents"][0]["incident_number"] == "INC-829"
        assert result.structured_content["filters"]["resolved_team_ids"] == "team-infra"
        assert "Loaded 1 incident summaries" in result.content[0].text

        request.assert_any_await(
            "GET",
            "/v1/teams",
            params={
                "page[size]": 100,
                "page[number]": 1,
                "filter[slug]": "Infrastructure",
            },
        )
        request.assert_any_await(
            "GET",
            "/v1/incidents",
            params={
                "fields[incidents]": (
                    "id,sequential_id,title,summary,status,severity,created_at,updated_at,url,"
                    "started_at,resolved_at,retrospective_progress_status"
                ),
                "include": "",
                "sort": "-created_at",
                "filter[team_ids]": "team-infra",
                "filter[severity]": "critical",
                "filter[status]": "resolved",
                "filter[started_at][gte]": "2026-04-01T00:00:00Z",
                "filter[started_at][lte]": "2026-04-13T23:59:59Z",
                "page[size]": 10,
                "page[number]": 1,
            },
        )

    @pytest.mark.asyncio
    async def test_detail_tool_returns_incident_detail_payload(self):
        mcp, request = self._register()

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": {
                "id": "inc-123",
                "type": "incidents",
                "attributes": {
                    "sequential_id": 829,
                    "title": "Database timeout in production",
                    "summary": "Primary database connection pool exhausted",
                    "status": "resolved",
                    "severity": "critical",
                    "started_at": "2026-04-10T15:00:00Z",
                    "resolved_at": "2026-04-10T15:45:00Z",
                    "mitigation": "Recycled the connection pool",
                    "resolution": "Scaled replicas and raised pool size",
                    "url": "https://rootly.com/account/incidents/inc-123",
                },
                "relationships": {"services": {"data": []}},
            }
        }
        request.return_value = response

        result = await mcp.tools["get_rootly_incident_detail"](incident_id="inc-123")

        assert result.structured_content["view"] == "incident_detail"
        assert result.structured_content["incident"]["incident_number"] == "INC-829"
        assert result.meta["incidentId"] == "inc-123"


@pytest.mark.unit
class TestChatGPTAppServerIntegration:
    """Integration-style tests against the assembled FastMCP server."""

    @pytest.mark.asyncio
    async def test_model_visible_workbench_tool_is_listed_but_app_only_detail_tool_is_hidden(self):
        with patch("rootly_mcp_server.server._load_swagger_spec") as mock_load_spec:
            mock_load_spec.return_value = {
                "openapi": "3.0.0",
                "info": {"title": "Test API", "version": "1.0.0"},
                "paths": {},
                "components": {"schemas": {}},
            }

            server = create_rootly_mcp_server(hosted=False)
            tools = await server.list_tools()
            tool_names = {tool.name for tool in tools}

        assert "open_rootly_incident_workbench" in tool_names
        assert "get_rootly_incident_detail" not in tool_names

        workbench_tool = next(tool for tool in tools if tool.name == "open_rootly_incident_workbench")
        assert workbench_tool.meta is not None
        assert workbench_tool.annotations is not None
        assert workbench_tool.meta["ui"]["resourceUri"] == APP_RESOURCE_URI
        assert workbench_tool.meta["openai/outputTemplate"] == APP_RESOURCE_URI
        assert workbench_tool.annotations.readOnlyHint is True
