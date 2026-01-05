"""Models for Code Review agent."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IssueSeverity(str, Enum):
    """Severity of code issues."""

    CRITICAL = "critical"  # Must fix before merge
    HIGH = "high"  # Should fix before merge
    MEDIUM = "medium"  # Recommended to fix
    LOW = "low"  # Nice to have
    INFO = "info"  # Informational only


class IssueCategory(str, Enum):
    """Category of code issues."""

    SECURITY = "security"  # Security vulnerabilities
    BUG = "bug"  # Potential bugs
    PERFORMANCE = "performance"  # Performance concerns
    STYLE = "style"  # Code style issues
    MAINTAINABILITY = "maintainability"  # Code complexity/readability
    BEST_PRACTICE = "best_practice"  # Coding best practices
    DOCUMENTATION = "documentation"  # Missing or poor docs
    TEST = "test"  # Testing concerns


class ReviewDecision(str, Enum):
    """Overall review decision."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    COMMENT = "comment"


@dataclass
class CodeIssue:
    """A single code issue found during review."""

    category: IssueCategory
    severity: IssueSeverity
    message: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    suggestion: str | None = None
    rule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "suggestion": self.suggestion,
            "rule_id": self.rule_id,
        }


@dataclass
class FileAnalysis:
    """Analysis result for a single file."""

    path: str
    language: str
    lines_added: int = 0
    lines_removed: int = 0
    issues: list[CodeIssue] = field(default_factory=list)
    score: float = 100.0  # Quality score 0-100

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "path": self.path,
            "language": self.language,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "issues": [i.to_dict() for i in self.issues],
            "score": self.score,
        }


class CodeReviewInput(BaseModel):
    """Input for Code Review agent."""

    model_config = ConfigDict(extra="allow")

    code: str = Field(..., description="Code to review (or diff)")
    file_path: str = Field(default="unknown", description="Path to the file")
    language: str = Field(default="python", description="Programming language")
    context: str | None = Field(default=None, description="Additional context")
    check_security: bool = Field(default=True, description="Check for security issues")
    check_style: bool = Field(default=True, description="Check style issues")
    check_performance: bool = Field(default=True, description="Check performance")
    check_tests: bool = Field(default=True, description="Check testing patterns")
    tenant_id: str = Field(default="default", description="Tenant identifier")
    user_id: str = Field(default="anonymous", description="User identifier")


class CodeReviewState(BaseModel):
    """State for Code Review workflow."""

    model_config = ConfigDict(extra="allow")

    # Input
    code: str
    file_path: str = "unknown"
    language: str = "python"
    context: str | None = None
    check_security: bool = True
    check_style: bool = True
    check_performance: bool = True
    check_tests: bool = True
    tenant_id: str = "default"
    user_id: str = "anonymous"

    # Processing state
    issues: list[dict[str, Any]] = Field(default_factory=list)
    file_analysis: dict[str, Any] | None = None

    # Output
    decision: ReviewDecision | None = None
    summary: str | None = None
    quality_score: float = 0.0
    suggestions: list[str] = Field(default_factory=list)

    # Workflow metadata
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: float = 0.0

    @classmethod
    def from_input(cls, input_data: CodeReviewInput) -> "CodeReviewState":
        """Create state from input."""
        return cls(
            code=input_data.code,
            file_path=input_data.file_path,
            language=input_data.language,
            context=input_data.context,
            check_security=input_data.check_security,
            check_style=input_data.check_style,
            check_performance=input_data.check_performance,
            check_tests=input_data.check_tests,
            tenant_id=input_data.tenant_id,
            user_id=input_data.user_id,
        )


class CodeReviewResult(BaseModel):
    """Result from Code Review agent."""

    model_config = ConfigDict(extra="allow")

    file_path: str
    language: str
    decision: ReviewDecision | None = None
    summary: str | None = None
    quality_score: float = 0.0
    issues: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    processing_time_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_state(cls, state: CodeReviewState) -> "CodeReviewResult":
        """Create result from state."""
        # Count issues by severity
        issue_counts: dict[str, int] = {}
        for issue in state.issues:
            severity = issue.get("severity", "unknown")
            issue_counts[severity] = issue_counts.get(severity, 0) + 1

        return cls(
            file_path=state.file_path,
            language=state.language,
            decision=state.decision,
            summary=state.summary,
            quality_score=state.quality_score,
            issues=state.issues,
            suggestions=state.suggestions,
            issue_counts=issue_counts,
            processing_time_ms=state.processing_time_ms,
            errors=state.errors,
        )

    @property
    def success(self) -> bool:
        """Check if review completed successfully."""
        return self.decision is not None and len(self.errors) == 0

    @property
    def has_critical_issues(self) -> bool:
        """Check if there are critical issues."""
        return self.issue_counts.get("critical", 0) > 0
