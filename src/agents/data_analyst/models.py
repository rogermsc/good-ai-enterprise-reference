"""Models for Data Analyst agent."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QueryIntent(str, Enum):
    """Intent of the data query."""

    SELECT = "select"  # Retrieve data
    AGGREGATE = "aggregate"  # Count, sum, avg, etc.
    JOIN = "join"  # Multi-table query
    TREND = "trend"  # Time-series analysis
    COMPARISON = "comparison"  # Compare groups
    TOP_N = "top_n"  # Ranking query
    UNKNOWN = "unknown"


class QueryRisk(str, Enum):
    """Risk level of the query."""

    LOW = "low"  # Read-only, limited scope
    MEDIUM = "medium"  # Complex joins, large tables
    HIGH = "high"  # Full table scans, sensitive data
    BLOCKED = "blocked"  # Contains unsafe operations


@dataclass
class TableSchema:
    """Schema information for a database table."""

    name: str
    columns: list[dict[str, str]]  # name, type, description
    row_count: int | None = None
    is_sensitive: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "columns": self.columns,
            "row_count": self.row_count,
            "is_sensitive": self.is_sensitive,
            "description": self.description,
        }


@dataclass
class QueryValidation:
    """Result of query validation."""

    is_valid: bool
    is_safe: bool
    risk_level: QueryRisk
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "is_valid": self.is_valid,
            "is_safe": self.is_safe,
            "risk_level": self.risk_level.value,
            "issues": self.issues,
            "suggestions": self.suggestions,
        }


class DataAnalystInput(BaseModel):
    """Input for Data Analyst agent."""

    model_config = ConfigDict(extra="allow")

    question: str = Field(..., description="Natural language question about the data")
    database: str = Field(default="default", description="Target database name")
    tables: list[str] | None = Field(
        default=None,
        description="Specific tables to query (None = auto-detect)",
    )
    max_rows: int = Field(default=100, description="Maximum rows to return")
    include_explanation: bool = Field(default=True, description="Include query explanation")
    execute: bool = Field(default=False, description="Execute the query")
    tenant_id: str = Field(default="default", description="Tenant identifier")
    user_id: str = Field(default="anonymous", description="User identifier")


class DataAnalystState(BaseModel):
    """State for Data Analyst workflow."""

    model_config = ConfigDict(extra="allow")

    # Input
    question: str
    database: str = "default"
    tables: list[str] | None = None
    max_rows: int = 100
    include_explanation: bool = True
    execute: bool = False
    tenant_id: str = "default"
    user_id: str = "anonymous"

    # Processing state
    intent: QueryIntent | None = None
    available_tables: list[dict[str, Any]] = Field(default_factory=list)
    selected_tables: list[str] = Field(default_factory=list)
    generated_sql: str | None = None
    validation: dict[str, Any] | None = None

    # Execution results
    query_executed: bool = False
    results: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0

    # Output
    explanation: str | None = None
    summary: str | None = None

    # Workflow metadata
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: float = 0.0

    @classmethod
    def from_input(cls, input_data: DataAnalystInput) -> "DataAnalystState":
        """Create state from input."""
        return cls(
            question=input_data.question,
            database=input_data.database,
            tables=input_data.tables,
            max_rows=input_data.max_rows,
            include_explanation=input_data.include_explanation,
            execute=input_data.execute,
            tenant_id=input_data.tenant_id,
            user_id=input_data.user_id,
        )


class DataAnalystResult(BaseModel):
    """Result from Data Analyst agent."""

    model_config = ConfigDict(extra="allow")

    question: str
    intent: QueryIntent | None = None
    generated_sql: str | None = None
    validation: dict[str, Any] | None = None
    explanation: str | None = None
    summary: str | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: float = 0.0
    processing_time_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_state(cls, state: DataAnalystState) -> "DataAnalystResult":
        """Create result from state."""
        return cls(
            question=state.question,
            intent=state.intent,
            generated_sql=state.generated_sql,
            validation=state.validation,
            explanation=state.explanation,
            summary=state.summary,
            results=state.results,
            row_count=state.row_count,
            execution_time_ms=state.execution_time_ms,
            processing_time_ms=state.processing_time_ms,
            errors=state.errors,
        )

    @property
    def success(self) -> bool:
        """Check if query generation was successful."""
        return self.generated_sql is not None and len(self.errors) == 0
