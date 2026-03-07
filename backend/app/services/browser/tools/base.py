"""
Base classes for browser tools.

Provides the tool registry primitives that browser tool classes depend on.
These were originally in a shared agent framework; here they're scoped to
the browser service since CarFINDa uses Gemini-driven agents rather than
an OpenAI function-calling tool registry.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolParameter:
    """Schema for a single tool parameter."""

    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    items: Optional[dict] = None


@dataclass
class ToolSchema:
    """Schema describing a tool's interface."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    category: str = ""
    execution_timeout: Optional[int] = None


@dataclass
class ToolResult:
    """Result returned from a tool execution."""

    success: bool
    data: Optional[dict[str, Any]] = None
    message: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    retryable: bool = False


class BaseTool:
    """Abstract base class for browser tools."""

    @classmethod
    def get_schema(cls) -> ToolSchema:
        raise NotImplementedError

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError
