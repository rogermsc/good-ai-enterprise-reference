"""Node implementations for Document Q&A agent."""

import time
from typing import Any

from src.agents.document_qa.models import (
    ConfidenceLevel,
    DocumentQAState,
    QueryType,
    RetrievedChunk,
)
from src.core.config import get_settings
from src.core.llm_gateway import LLMGateway
from src.core.observability import get_logger, get_tracer
from src.core.rag import EmbeddingService, VectorStore

logger = get_logger()
tracer = get_tracer()


class DocumentQANodes:
    """Node implementations for Document Q&A workflow."""

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        embedding_service: EmbeddingService | None = None,
        llm_gateway: LLMGateway | None = None,
    ) -> None:
        self.settings = get_settings()
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.llm_gateway = llm_gateway or LLMGateway()

    def classify_query(self, state: DocumentQAState) -> dict[str, Any]:
        """Classify the type of question for optimal handling."""
        with tracer.start_as_current_span("document_qa.classify_query"):
            question = state.question.lower()

            # Simple keyword-based classification
            if any(word in question for word in ["what is", "who is", "when was", "where is"]):
                query_type = QueryType.FACTUAL
            elif any(word in question for word in ["summarize", "summary", "overview"]):
                query_type = QueryType.SUMMARY
            elif any(word in question for word in ["compare", "difference", "versus", "vs"]):
                query_type = QueryType.COMPARISON
            elif any(word in question for word in ["explain", "why", "how does"]):
                query_type = QueryType.EXPLANATION
            elif any(word in question for word in ["list", "what are", "enumerate"]):
                query_type = QueryType.LIST
            else:
                query_type = QueryType.UNKNOWN

            logger.info(
                "query_classified",
                question=state.question[:100],
                query_type=query_type.value,
            )

            return {"query_type": query_type}

    def rewrite_query(self, state: DocumentQAState) -> dict[str, Any]:
        """Optionally rewrite the query for better retrieval."""
        with tracer.start_as_current_span("document_qa.rewrite_query"):
            # Simple query expansion based on type
            original = state.question

            if state.query_type == QueryType.SUMMARY:
                rewritten = f"key points main ideas {original}"
            elif state.query_type == QueryType.COMPARISON:
                rewritten = f"differences similarities {original}"
            elif state.query_type == QueryType.EXPLANATION:
                rewritten = f"explanation reasoning behind {original}"
            else:
                rewritten = original

            logger.debug(
                "query_rewritten",
                original=original[:100],
                rewritten=rewritten[:100],
            )

            return {"rewritten_query": rewritten}

    def retrieve_chunks(self, state: DocumentQAState) -> dict[str, Any]:
        """Retrieve relevant chunks from the vector store."""
        with tracer.start_as_current_span("document_qa.retrieve_chunks") as span:
            start_time = time.time()

            # Use rewritten query if available
            query = state.rewritten_query or state.question

            try:
                # Get embeddings for the query
                if self.embedding_service:
                    embedding = self.embedding_service.embed(query)
                else:
                    # Mock embedding for testing
                    embedding = [0.0] * 1536

                # Search vector store
                if self.vector_store:
                    results = self.vector_store.search(
                        query_embedding=embedding,
                        limit=state.max_chunks,
                        min_score=state.min_score,
                        filter_metadata=(
                            {"document_id": {"$in": state.document_ids}}
                            if state.document_ids
                            else None
                        ),
                    )

                    chunks = [
                        RetrievedChunk(
                            content=r.content,
                            document_id=r.metadata.get("document_id", "unknown"),
                            chunk_id=r.id,
                            score=r.score,
                            metadata=r.metadata,
                        ).to_dict()
                        for r in results
                    ]
                else:
                    # Mock response for testing
                    chunks = [
                        RetrievedChunk(
                            content=f"Mock content for: {query[:50]}",
                            document_id="mock-doc-1",
                            chunk_id="mock-chunk-1",
                            score=0.85,
                            metadata={"source": "mock"},
                        ).to_dict()
                    ]

                # Build context from chunks
                context = "\n\n".join(
                    f"[Source {i + 1}]: {chunk['content']}" for i, chunk in enumerate(chunks)
                )

                latency = (time.time() - start_time) * 1000
                span.set_attribute("chunks_retrieved", len(chunks))
                span.set_attribute("latency_ms", latency)

                logger.info(
                    "chunks_retrieved",
                    query=query[:100],
                    chunk_count=len(chunks),
                    latency_ms=round(latency, 2),
                )

                return {
                    "retrieved_chunks": chunks,
                    "context": context,
                }

            except Exception as e:
                logger.error("retrieval_failed", error=str(e))
                return {
                    "errors": [*state.errors, f"Retrieval failed: {e!s}"],
                    "retrieved_chunks": [],
                    "context": "",
                }

    def generate_answer(self, state: DocumentQAState) -> dict[str, Any]:
        """Generate an answer based on retrieved context."""
        with tracer.start_as_current_span("document_qa.generate_answer") as span:
            start_time = time.time()

            if not state.context or not state.retrieved_chunks:
                return {
                    "answer": "I couldn't find relevant information to answer your question.",
                    "confidence": ConfidenceLevel.UNCERTAIN,
                }

            # Build prompt based on query type
            if state.query_type == QueryType.SUMMARY:
                instruction = "Provide a concise summary based on the following sources."
            elif state.query_type == QueryType.COMPARISON:
                instruction = "Compare and contrast based on the following sources."
            elif state.query_type == QueryType.EXPLANATION:
                instruction = "Provide a clear explanation based on the following sources."
            elif state.query_type == QueryType.LIST:
                instruction = "List the relevant items based on the following sources."
            else:
                instruction = "Answer the question based on the following sources."

            # Prompt for future LLM integration (currently using mock)
            _ = f"""You are a helpful assistant that answers questions based on provided context.

{instruction}

Context:
{state.context}

Question: {state.question}

Instructions:
1. Only use information from the provided context
2. If the context doesn't contain enough information, say so
3. Be concise but thorough
4. Cite sources when possible

Answer:"""

            try:
                # Use mock response for testing (real implementation would use async LLM call)
                settings = self.settings
                if settings.is_mock_mode or not hasattr(self.llm_gateway, "generate"):
                    # Generate mock answer based on context
                    answer = f"Based on the provided context, {state.question.rstrip('?')}. {state.context[:200]}"
                else:
                    # Real LLM call would go here (async)
                    answer = f"Based on the provided context: {state.context[:200]}"

                # Determine confidence based on chunk scores
                avg_score = sum(c["score"] for c in state.retrieved_chunks) / len(
                    state.retrieved_chunks
                )

                if avg_score >= 0.8:
                    confidence = ConfidenceLevel.HIGH
                elif avg_score >= 0.6:
                    confidence = ConfidenceLevel.MEDIUM
                elif avg_score >= 0.4:
                    confidence = ConfidenceLevel.LOW
                else:
                    confidence = ConfidenceLevel.UNCERTAIN

                latency = (time.time() - start_time) * 1000
                span.set_attribute("confidence", confidence.value)
                span.set_attribute("latency_ms", latency)

                logger.info(
                    "answer_generated",
                    confidence=confidence.value,
                    avg_score=round(avg_score, 3),
                    latency_ms=round(latency, 2),
                )

                return {
                    "answer": answer,
                    "confidence": confidence,
                }

            except Exception as e:
                logger.error("generation_failed", error=str(e))
                return {
                    "answer": None,
                    "confidence": ConfidenceLevel.UNCERTAIN,
                    "errors": [*state.errors, f"Generation failed: {e!s}"],
                }

    def format_sources(self, state: DocumentQAState) -> dict[str, Any]:
        """Format sources for citation."""
        with tracer.start_as_current_span("document_qa.format_sources"):
            if not state.include_sources or not state.retrieved_chunks:
                return {"sources": []}

            sources = []
            seen_docs = set()

            for chunk in state.retrieved_chunks:
                doc_id = chunk.get("document_id", "unknown")

                # Deduplicate by document
                if doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)

                sources.append(
                    {
                        "document_id": doc_id,
                        "relevance_score": round(chunk.get("score", 0), 3),
                        "excerpt": chunk.get("content", "")[:200] + "...",
                        "metadata": chunk.get("metadata", {}),
                    }
                )

            logger.debug("sources_formatted", count=len(sources))

            return {"sources": sources}

    def finalize(self, state: DocumentQAState) -> dict[str, Any]:
        """Finalize the response and calculate metrics."""
        with tracer.start_as_current_span("document_qa.finalize"):
            # Processing time would be tracked by the caller
            # This is just a placeholder for any final processing

            logger.info(
                "document_qa_complete",
                question=state.question[:100],
                has_answer=state.answer is not None,
                confidence=state.confidence.value,
                source_count=len(state.sources),
                error_count=len(state.errors),
            )

            return {}
