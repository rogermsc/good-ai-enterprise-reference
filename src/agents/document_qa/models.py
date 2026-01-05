"""Models for Document Q&A agent."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QueryType(str, Enum):
    """Type of query for routing."""

    FACTUAL = "factual"  # Looking for specific facts
    SUMMARY = "summary"  # Wants a summary
    COMPARISON = "comparison"  # Comparing items
    EXPLANATION = "explanation"  # Wants explanation
    LIST = "list"  # Wants a list of items
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    """Confidence in the answer."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"


@dataclass
class RetrievedChunk:
    """A chunk retrieved from the vector store."""

    content: str
    document_id: str
    chunk_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "content": self.content,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "score": self.score,
            "metadata": self.metadata,
        }


class DocumentQAInput(BaseModel):
    """Input for Document Q&A agent."""

    model_config = ConfigDict(extra="allow")

    question: str = Field(..., description="The question to answer")
    document_ids: list[str] | None = Field(
        default=None,
        description="Specific document IDs to search (None = search all)",
    )
    max_chunks: int = Field(default=5, description="Maximum chunks to retrieve")
    min_score: float = Field(default=0.5, description="Minimum similarity score")
    include_sources: bool = Field(default=True, description="Include source citations")
    tenant_id: str = Field(default="default", description="Tenant identifier")
    user_id: str = Field(default="anonymous", description="User identifier")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentQAState(BaseModel):
    """State for Document Q&A workflow."""

    model_config = ConfigDict(extra="allow")

    # Input
    question: str
    document_ids: list[str] | None = None
    max_chunks: int = 5
    min_score: float = 0.5
    include_sources: bool = True
    tenant_id: str = "default"
    user_id: str = "anonymous"

    # Processing state
    query_type: QueryType | None = None
    rewritten_query: str | None = None
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    context: str = ""

    # Output
    answer: str | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.UNCERTAIN
    sources: list[dict[str, Any]] = Field(default_factory=list)

    # Workflow metadata
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: float = 0.0

    @classmethod
    def from_input(cls, input_data: DocumentQAInput) -> "DocumentQAState":
        """Create state from input."""
        return cls(
            question=input_data.question,
            document_ids=input_data.document_ids,
            max_chunks=input_data.max_chunks,
            min_score=input_data.min_score,
            include_sources=input_data.include_sources,
            tenant_id=input_data.tenant_id,
            user_id=input_data.user_id,
        )


class DocumentQAResult(BaseModel):
    """Result from Document Q&A agent."""

    model_config = ConfigDict(extra="allow")

    question: str
    answer: str | None
    confidence: ConfidenceLevel
    sources: list[dict[str, Any]] = Field(default_factory=list)
    query_type: QueryType | None = None
    chunks_retrieved: int = 0
    processing_time_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_state(cls, state: DocumentQAState) -> "DocumentQAResult":
        """Create result from state."""
        return cls(
            question=state.question,
            answer=state.answer,
            confidence=state.confidence,
            sources=state.sources if state.include_sources else [],
            query_type=state.query_type,
            chunks_retrieved=len(state.retrieved_chunks),
            processing_time_ms=state.processing_time_ms,
            errors=state.errors,
        )

    @property
    def success(self) -> bool:
        """Check if query was answered successfully."""
        return self.answer is not None and len(self.errors) == 0
