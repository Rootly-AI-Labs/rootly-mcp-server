"""ChatGPT app-aware tools and resources for Rootly MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib import resources
from typing import Annotated, Any, Literal, Protocol

from fastmcp.apps.config import AppConfig, ResourceCSP
from fastmcp.resources.base import ResourceContent, ResourceResult
from fastmcp.tools.base import ToolResult
from pydantic import Field

from .incidents import _summarize_incident_record, prepare_incident_query_context

JsonDict = dict[str, Any]
MakeAuthenticatedRequest = Callable[..., Awaitable[Any]]
StripHeavyNestedData = Callable[[JsonDict], JsonDict]

APP_RESOURCE_URI = "ui://rootly/incident-workbench.html"
APP_RESOURCE_MIME = "text/html;profile=mcp-app"


class MCPErrorLike(Protocol):
    """Protocol for MCP error categorization used by app handlers."""

    @staticmethod
    def categorize_error(exception: Exception) -> tuple[str, str]: ...


def _load_incident_workbench_html() -> str:
    """Load the embedded incident workbench widget."""
    return (
        resources.files("rootly_mcp_server.data")
        .joinpath("chatgpt_incident_workbench.html")
        .read_text(encoding="utf-8")
    )


def _build_workbench_summary(
    *,
    incidents: list[dict[str, Any]],
    filters: dict[str, Any],
    truncated: bool,
    total_matching_count: int | None,
) -> str:
    """Build a compact model-facing summary for the incident workbench."""
    filter_bits: list[str] = []
    if filters.get("teams"):
        filter_bits.append(f"teams={filters['teams']}")
    elif filters.get("resolved_team_ids"):
        filter_bits.append(f"team_ids={filters['resolved_team_ids']}")
    if filters.get("severity"):
        filter_bits.append(f"severity={filters['severity']}")
    if filters.get("status"):
        filter_bits.append(f"status={filters['status']}")
    if filters.get("started_after") or filters.get("started_before"):
        filter_bits.append(
            f"started={filters.get('started_after') or '…'} to {filters.get('started_before') or '…'}"
        )

    scope_text = f" for {', '.join(filter_bits)}" if filter_bits else ""
    total_text = (
        f" out of {total_matching_count} matching incidents" if total_matching_count is not None else ""
    )
    suffix = " Results were truncated." if truncated else ""

    return (
        f"Loaded {len(incidents)} incident summaries{scope_text}{total_text}."
        f"{suffix} Open the incident workbench to browse and drill into a specific incident."
    )


def _summarize_incident_detail(incident: dict[str, Any]) -> dict[str, Any]:
    """Return a compact detail payload for the app widget."""
    attrs = incident.get("attributes", {})
    relationships = incident.get("relationships", {})
    sequential_id = attrs.get("sequential_id")

    return {
        "incident_id": incident.get("id"),
        "incident_number": f"INC-{sequential_id}" if sequential_id is not None else None,
        "title": attrs.get("title"),
        "summary": attrs.get("summary"),
        "status": attrs.get("status"),
        "severity": attrs.get("severity"),
        "created_at": attrs.get("created_at"),
        "updated_at": attrs.get("updated_at"),
        "started_at": attrs.get("started_at"),
        "resolved_at": attrs.get("resolved_at"),
        "customer_impact_summary": attrs.get("customer_impact_summary"),
        "mitigation": attrs.get("mitigation"),
        "resolution": attrs.get("resolution"),
        "retrospective_progress_status": attrs.get("retrospective_progress_status"),
        "url": attrs.get("url"),
        "relationships": relationships,
    }


def register_chatgpt_app_tools(
    mcp: Any,
    make_authenticated_request: MakeAuthenticatedRequest,
    strip_heavy_nested_data: StripHeavyNestedData,
    mcp_error: MCPErrorLike,
) -> None:
    """Register ChatGPT app-aware Rootly tools and HTML resources."""

    widget_csp = {
        "ui": {
            "prefersBorder": True,
            "csp": {
                "connectDomains": [],
                "resourceDomains": [],
            },
        },
        "openai/widgetDescription": (
            "A visual Rootly incident workspace for browsing filtered incidents and opening details."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {
            "connect_domains": [],
            "resource_domains": [],
        },
    }

    @mcp.resource(APP_RESOURCE_URI, name="Rootly Incident Workbench", mime_type=APP_RESOURCE_MIME)
    async def rootly_incident_workbench_resource() -> ResourceResult:
        """Serve the incident workbench widget for ChatGPT."""
        return ResourceResult(
            contents=[
                ResourceContent(
                    _load_incident_workbench_html(),
                    mime_type=APP_RESOURCE_MIME,
                    meta=widget_csp,
                )
            ]
        )

    @mcp.tool(
        name="open_rootly_incident_workbench",
        title="Open Rootly Incident Workbench",
        description="Open a visual Rootly incident workbench with structured filters and bounded incident results.",
        annotations={"readOnlyHint": True},
        app=AppConfig(
            resourceUri=APP_RESOURCE_URI,
            visibility=["model", "app"],
            prefersBorder=True,
            csp=ResourceCSP(connectDomains=[], resourceDomains=[]),
        ),
        meta={
            "openai/outputTemplate": APP_RESOURCE_URI,
            "openai/toolInvocation/invoking": "Loading incidents…",
            "openai/toolInvocation/invoked": "Incident workbench ready",
        },
    )
    async def open_rootly_incident_workbench(
        query: Annotated[
            str,
            Field(description="Optional free-text search across incident titles and summaries"),
        ] = "",
        teams: Annotated[
            str,
            Field(description="Comma-separated team names or slugs to filter incidents"),
        ] = "",
        team_ids: Annotated[
            str,
            Field(description="Comma-separated Rootly team IDs to filter incidents"),
        ] = "",
        service_ids: Annotated[
            str,
            Field(description="Comma-separated Rootly service IDs to filter incidents"),
        ] = "",
        severity: Annotated[
            str,
            Field(description="Optional severity filter such as critical, high, medium, or low"),
        ] = "",
        status: Annotated[
            str,
            Field(description="Optional incident status filter such as started, investigating, or resolved"),
        ] = "",
        started_after: Annotated[
            str,
            Field(description="Filter incidents that started at or after this ISO 8601 timestamp"),
        ] = "",
        started_before: Annotated[
            str,
            Field(description="Filter incidents that started at or before this ISO 8601 timestamp"),
        ] = "",
        max_results: Annotated[
            int,
            Field(description="Maximum number of incidents to collect into the workbench (max: 50)", ge=1, le=50),
        ] = 25,
        sort: Annotated[
            Literal["created_at", "-created_at", "updated_at", "-updated_at"],
            Field(description="Sort order for incidents"),
        ] = "-created_at",
    ) -> ToolResult:
        """Collect filtered incidents and render them inside the incident workbench widget."""
        try:
            params, filters = await prepare_incident_query_context(
                make_authenticated_request=make_authenticated_request,
                query=query,
                teams=teams,
                team_ids=team_ids,
                service_ids=service_ids,
                severity=severity,
                status=status,
                started_after=started_after,
                started_before=started_before,
                custom_field_selected_option_ids="",
                sort=sort,
            )
        except ValueError as e:
            return ToolResult(
                content=f"Could not open the incident workbench: {e}",
                structured_content={"view": "error", "message": str(e)},
            )
        except Exception as e:
            error_type, error_message = mcp_error.categorize_error(e)
            return ToolResult(
                content=f"Could not open the incident workbench: {error_message}",
                structured_content={
                    "view": "error",
                    "message": error_message,
                    "error_type": error_type,
                },
            )

        collected_incidents: list[dict[str, Any]] = []
        page_number = 1
        total_matching_count: int | None = None
        results_truncated = False

        try:
            while len(collected_incidents) < max_results:
                page_params = dict(params)
                page_params["page[size]"] = min(max_results, 25)
                page_params["page[number]"] = page_number

                response = await make_authenticated_request("GET", "/v1/incidents", params=page_params)
                response.raise_for_status()

                response_data = strip_heavy_nested_data(response.json())
                page_incidents = response_data.get("data", [])
                meta = response_data.get("meta", {})

                if total_matching_count is None:
                    total_matching_count = meta.get("total_count")

                if not page_incidents:
                    break

                remaining = max_results - len(collected_incidents)
                if len(page_incidents) > remaining:
                    results_truncated = True
                collected_incidents.extend(page_incidents[:remaining])

                next_page = meta.get("next_page")
                if next_page is None:
                    break
                if len(collected_incidents) >= max_results:
                    results_truncated = True
                    break
                page_number = next_page

            if total_matching_count is not None and total_matching_count > len(collected_incidents):
                results_truncated = True

            incidents = [_summarize_incident_record(incident) for incident in collected_incidents]
            payload = {
                "view": "incident_workbench",
                "title": "Rootly Incident Workbench",
                "filters": filters,
                "incidents": incidents,
                "collection": {
                    "max_results": max_results,
                    "total_matching_count": total_matching_count,
                    "results_truncated": results_truncated,
                },
            }
            return ToolResult(
                content=_build_workbench_summary(
                    incidents=incidents,
                    filters=filters,
                    truncated=results_truncated,
                    total_matching_count=total_matching_count,
                ),
                structured_content=payload,
            )
        except Exception as e:
            error_type, error_message = mcp_error.categorize_error(e)
            return ToolResult(
                content=f"Could not load incidents: {error_message}",
                structured_content={
                    "view": "error",
                    "message": error_message,
                    "error_type": error_type,
                },
            )

    @mcp.tool(
        name="get_rootly_incident_detail",
        title="Get Rootly Incident Detail",
        description="Fetch detailed information for a single Rootly incident so the app widget can drill in.",
        annotations={"readOnlyHint": True},
        app=AppConfig(
            resourceUri=APP_RESOURCE_URI,
            visibility=["app"],
            prefersBorder=True,
            csp=ResourceCSP(connectDomains=[], resourceDomains=[]),
        ),
        meta={
            "openai/outputTemplate": APP_RESOURCE_URI,
            "openai/toolInvocation/invoking": "Opening incident…",
            "openai/toolInvocation/invoked": "Incident detail ready",
        },
    )
    async def get_rootly_incident_detail(
        incident_id: Annotated[str, Field(description="Rootly incident ID to retrieve")],
    ) -> ToolResult:
        """Fetch a detailed incident payload for the widget detail pane."""
        try:
            response = await make_authenticated_request("GET", f"/v1/incidents/{incident_id}")
            response.raise_for_status()
            response_data = response.json()

            raw_incident = response_data.get("data", {})
            stripped = strip_heavy_nested_data({"data": [raw_incident]})
            incident = stripped.get("data", [{}])[0]
            detail = _summarize_incident_detail(incident)

            return ToolResult(
                content=f"Opened details for {detail.get('incident_number') or incident_id}.",
                structured_content={
                    "view": "incident_detail",
                    "incident": detail,
                },
                meta={"incidentId": incident_id},
            )
        except Exception as e:
            error_type, error_message = mcp_error.categorize_error(e)
            return ToolResult(
                content=f"Could not load incident {incident_id}: {error_message}",
                structured_content={
                    "view": "error",
                    "message": error_message,
                    "error_type": error_type,
                    "incident_id": incident_id,
                },
            )
