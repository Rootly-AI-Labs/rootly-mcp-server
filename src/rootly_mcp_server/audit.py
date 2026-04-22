"""Security audit logging for Rootly MCP Server."""

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

# Context variables for tracking session info
current_session: ContextVar[str | None] = ContextVar("current_session", default=None)
current_user: ContextVar[str | None] = ContextVar("current_user", default=None)


class AuditLogger:
    """Structured audit logger for security-relevant events."""

    def __init__(self, logger_name: str = "rootly_mcp_server.audit"):
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        # JSON formatter for structured logs
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "audit_event": %(message)s}'
        )

        # Add console handler if none exists
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def log_permission_change(self, action: str, details: dict[str, Any]):
        """Log permission configuration changes."""
        event = {
            "event_type": "permission_change",
            "action": action,
            "session_id": current_session.get(),
            "user_id": current_user.get(),
            "timestamp": time.time(),
            **details,
        }
        self.logger.info(json.dumps(event))

    def log_tool_validation(
        self, enabled_tools: set[str], valid_tools: set[str], invalid_tools: list[str]
    ):
        """Log tool name validation results."""
        event = {
            "event_type": "tool_validation",
            "requested_tools_count": len(enabled_tools),
            "valid_tools_count": len(valid_tools),
            "invalid_tools_count": len(invalid_tools),
            "invalid_tools": invalid_tools,
            "session_id": current_session.get(),
            "timestamp": time.time(),
        }
        self.logger.info(json.dumps(event))

    def log_server_start(self, config: dict[str, Any]):
        """Log server startup with security-relevant configuration."""
        event = {
            "event_type": "server_start",
            "write_tools_enabled": config.get("enable_write_tools", True),
            "tool_count": config.get("tool_count", 0),
            "hosted_mode": config.get("hosted", False),
            "allowlist_enabled": bool(config.get("enabled_tools")),
            "transport": config.get("transport", "unknown"),
            "timestamp": time.time(),
        }
        self.logger.info(json.dumps(event))

    def log_tool_access_attempt(
        self, tool_name: str, method: str, success: bool, details: dict[str, Any] | None = None
    ):
        """Log individual tool access attempts."""
        event = {
            "event_type": "tool_access",
            "tool_name": tool_name,
            "http_method": method,
            "success": success,
            "session_id": current_session.get(),
            "user_id": current_user.get(),
            "timestamp": time.time(),
            **(details or {}),
        }
        self.logger.info(json.dumps(event))

    def log_configuration_error(
        self, error_type: str, message: str, details: dict[str, Any] | None = None
    ):
        """Log configuration validation errors."""
        event = {
            "event_type": "configuration_error",
            "error_type": error_type,
            "message": message,
            "session_id": current_session.get(),
            "timestamp": time.time(),
            **(details or {}),
        }
        self.logger.warning(json.dumps(event))


# Global audit logger instance
audit = AuditLogger()
