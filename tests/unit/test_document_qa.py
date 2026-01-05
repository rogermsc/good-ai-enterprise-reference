"""Tests for Document Q&A agent."""

import pytest

from src.agents.document_qa import (
    DocumentQAInput,
    DocumentQAResult,
    DocumentQAState,
    create_document_qa_graph,
)
from src.agents.document_qa.models import ConfidenceLevel, QueryType, RetrievedChunk
from src.agents.document_qa.nodes import DocumentQANodes


class TestDocumentQAInput:
    """Tests for DocumentQAInput model."""

    def test_default_values(self) -> None:
        input_data = DocumentQAInput(question="What is Python?")
        assert input_data.question == "What is Python?"
        assert input_data.max_chunks == 5
        assert input_data.min_score == 0.5
        assert input_data.include_sources is True

    def test_custom_values(self) -> None:
        input_data = DocumentQAInput(
            question="Explain the architecture",
            document_ids=["doc-1", "doc-2"],
            max_chunks=10,
            min_score=0.7,
            tenant_id="acme-corp",
        )
        assert input_data.document_ids == ["doc-1", "doc-2"]
        assert input_data.max_chunks == 10
        assert input_data.tenant_id == "acme-corp"


class TestDocumentQAState:
    """Tests for DocumentQAState model."""

    def test_from_input(self) -> None:
        input_data = DocumentQAInput(
            question="What is AI?",
            document_ids=["doc-1"],
            max_chunks=3,
        )
        state = DocumentQAState.from_input(input_data)

        assert state.question == "What is AI?"
        assert state.document_ids == ["doc-1"]
        assert state.max_chunks == 3
        assert state.answer is None
        assert state.confidence == ConfidenceLevel.UNCERTAIN


class TestDocumentQAResult:
    """Tests for DocumentQAResult model."""

    def test_from_state(self) -> None:
        state = DocumentQAState(
            question="What is AI?",
            answer="AI is artificial intelligence.",
            confidence=ConfidenceLevel.HIGH,
            sources=[{"document_id": "doc-1"}],
            retrieved_chunks=[{"content": "test"}],
            processing_time_ms=150.5,
        )
        result = DocumentQAResult.from_state(state)

        assert result.question == "What is AI?"
        assert result.answer == "AI is artificial intelligence."
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.success is True
        assert result.chunks_retrieved == 1

    def test_success_with_errors(self) -> None:
        state = DocumentQAState(
            question="Test",
            answer="Answer",
            confidence=ConfidenceLevel.MEDIUM,
            errors=["Some error occurred"],
        )
        result = DocumentQAResult.from_state(state)
        assert result.success is False

    def test_success_no_answer(self) -> None:
        state = DocumentQAState(
            question="Test",
            answer=None,
            confidence=ConfidenceLevel.UNCERTAIN,
        )
        result = DocumentQAResult.from_state(state)
        assert result.success is False


class TestRetrievedChunk:
    """Tests for RetrievedChunk model."""

    def test_create_chunk(self) -> None:
        chunk = RetrievedChunk(
            content="This is the content",
            document_id="doc-123",
            chunk_id="chunk-456",
            score=0.85,
            metadata={"page": 5},
        )
        assert chunk.content == "This is the content"
        assert chunk.score == 0.85

    def test_serialization(self) -> None:
        chunk = RetrievedChunk(
            content="Content",
            document_id="doc-1",
            chunk_id="chunk-1",
            score=0.9,
        )
        data = chunk.to_dict()
        assert data["document_id"] == "doc-1"
        assert data["score"] == 0.9


class TestDocumentQANodes:
    """Tests for DocumentQANodes."""

    @pytest.fixture
    def nodes(self) -> DocumentQANodes:
        return DocumentQANodes()

    def test_classify_factual_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(question="What is the capital of France?")
        result = nodes.classify_query(state)
        assert result["query_type"] == QueryType.FACTUAL

    def test_classify_summary_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(question="Please summarize the document")
        result = nodes.classify_query(state)
        assert result["query_type"] == QueryType.SUMMARY

    def test_classify_comparison_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(question="Compare Python vs Java")
        result = nodes.classify_query(state)
        assert result["query_type"] == QueryType.COMPARISON

    def test_classify_explanation_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(question="Explain how neural networks work")
        result = nodes.classify_query(state)
        assert result["query_type"] == QueryType.EXPLANATION

    def test_classify_list_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(question="What are the main features?")
        result = nodes.classify_query(state)
        assert result["query_type"] == QueryType.LIST

    def test_classify_unknown_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(question="Random question here")
        result = nodes.classify_query(state)
        assert result["query_type"] == QueryType.UNKNOWN

    def test_rewrite_summary_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="Summarize the article",
            query_type=QueryType.SUMMARY,
        )
        result = nodes.rewrite_query(state)
        assert "key points" in result["rewritten_query"]

    def test_rewrite_comparison_query(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="Compare A and B",
            query_type=QueryType.COMPARISON,
        )
        result = nodes.rewrite_query(state)
        assert "differences" in result["rewritten_query"]

    def test_retrieve_chunks_mock(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="What is Python?",
            rewritten_query="What is Python programming language?",
        )
        result = nodes.retrieve_chunks(state)

        assert "retrieved_chunks" in result
        assert len(result["retrieved_chunks"]) > 0
        assert "context" in result
        assert result["context"] != ""

    def test_generate_answer_no_context(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="What is Python?",
            context="",
            retrieved_chunks=[],
        )
        result = nodes.generate_answer(state)

        assert "couldn't find" in result["answer"].lower()
        assert result["confidence"] == ConfidenceLevel.UNCERTAIN

    def test_generate_answer_with_context(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="What is Python?",
            query_type=QueryType.FACTUAL,
            context="Python is a programming language created by Guido van Rossum.",
            retrieved_chunks=[{"content": "Python is a programming language", "score": 0.9}],
        )
        result = nodes.generate_answer(state)

        assert result["answer"] is not None
        assert result["confidence"] != ConfidenceLevel.UNCERTAIN

    def test_format_sources(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="Test",
            include_sources=True,
            retrieved_chunks=[
                {
                    "content": "Content 1",
                    "document_id": "doc-1",
                    "score": 0.9,
                    "metadata": {"title": "Doc 1"},
                },
                {
                    "content": "Content 2",
                    "document_id": "doc-2",
                    "score": 0.8,
                    "metadata": {"title": "Doc 2"},
                },
            ],
        )
        result = nodes.format_sources(state)

        assert len(result["sources"]) == 2
        assert result["sources"][0]["document_id"] == "doc-1"
        assert result["sources"][0]["relevance_score"] == 0.9

    def test_format_sources_deduplicates(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="Test",
            include_sources=True,
            retrieved_chunks=[
                {"content": "Chunk 1", "document_id": "doc-1", "score": 0.9},
                {"content": "Chunk 2", "document_id": "doc-1", "score": 0.8},
                {"content": "Chunk 3", "document_id": "doc-2", "score": 0.7},
            ],
        )
        result = nodes.format_sources(state)

        # Should deduplicate to 2 documents
        assert len(result["sources"]) == 2

    def test_format_sources_disabled(self, nodes: DocumentQANodes) -> None:
        state = DocumentQAState(
            question="Test",
            include_sources=False,
            retrieved_chunks=[{"content": "Content", "document_id": "doc-1", "score": 0.9}],
        )
        result = nodes.format_sources(state)
        assert result["sources"] == []


class TestDocumentQAGraph:
    """Tests for Document Q&A graph."""

    def test_create_graph(self) -> None:
        graph = create_document_qa_graph()
        assert graph is not None

    def test_run_graph(self) -> None:
        from src.agents.document_qa.graph import run_document_qa

        input_data = DocumentQAInput(
            question="What is machine learning?",
            tenant_id="test-tenant",
        )

        result = run_document_qa(input_data)

        assert isinstance(result, DocumentQAResult)
        assert result.question == "What is machine learning?"
        assert result.chunks_retrieved > 0
        assert result.processing_time_ms > 0

    def test_run_graph_with_options(self) -> None:
        from src.agents.document_qa.graph import run_document_qa

        input_data = DocumentQAInput(
            question="Summarize the key points",
            document_ids=["doc-123"],
            max_chunks=3,
            include_sources=True,
        )

        result = run_document_qa(input_data)

        assert result.query_type == QueryType.SUMMARY


class TestDocumentQAAsync:
    """Tests for async Document Q&A."""

    @pytest.mark.asyncio
    async def test_run_async(self) -> None:
        from src.agents.document_qa.graph import run_document_qa_async

        input_data = DocumentQAInput(question="What is AI?")

        result = await run_document_qa_async(input_data)

        assert isinstance(result, DocumentQAResult)
        assert result.question == "What is AI?"
