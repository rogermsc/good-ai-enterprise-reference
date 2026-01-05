"""LangGraph workflow for Document Q&A agent."""

import time

from langgraph.graph import END, StateGraph

from src.agents.document_qa.models import (
    DocumentQAInput,
    DocumentQAResult,
    DocumentQAState,
)
from src.agents.document_qa.nodes import DocumentQANodes
from src.core.llm_gateway import LLMGateway
from src.core.observability import get_logger, get_tracer
from src.core.rag import EmbeddingService, VectorStore

logger = get_logger()
tracer = get_tracer()


def create_document_qa_graph(
    vector_store: VectorStore | None = None,
    embedding_service: EmbeddingService | None = None,
    llm_gateway: LLMGateway | None = None,
) -> StateGraph:
    """
    Create the Document Q&A workflow graph.

    The workflow follows these steps:
    1. classify_query: Determine the type of question
    2. rewrite_query: Optionally expand/rewrite for better retrieval
    3. retrieve_chunks: Get relevant document chunks
    4. generate_answer: Generate answer from context
    5. format_sources: Format source citations
    6. finalize: Complete processing

    Args:
        vector_store: Vector store for document retrieval
        embedding_service: Service for generating embeddings
        llm_gateway: Gateway for LLM calls

    Returns:
        Compiled LangGraph workflow
    """
    nodes = DocumentQANodes(
        vector_store=vector_store,
        embedding_service=embedding_service,
        llm_gateway=llm_gateway,
    )

    # Create the graph
    workflow = StateGraph(DocumentQAState)

    # Add nodes
    workflow.add_node("classify_query", nodes.classify_query)
    workflow.add_node("rewrite_query", nodes.rewrite_query)
    workflow.add_node("retrieve_chunks", nodes.retrieve_chunks)
    workflow.add_node("generate_answer", nodes.generate_answer)
    workflow.add_node("format_sources", nodes.format_sources)
    workflow.add_node("finalize", nodes.finalize)

    # Define edges
    workflow.set_entry_point("classify_query")
    workflow.add_edge("classify_query", "rewrite_query")
    workflow.add_edge("rewrite_query", "retrieve_chunks")
    workflow.add_edge("retrieve_chunks", "generate_answer")
    workflow.add_edge("generate_answer", "format_sources")
    workflow.add_edge("format_sources", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()


def run_document_qa(
    input_data: DocumentQAInput,
    vector_store: VectorStore | None = None,
    embedding_service: EmbeddingService | None = None,
    llm_gateway: LLMGateway | None = None,
) -> DocumentQAResult:
    """
    Run the Document Q&A workflow.

    Args:
        input_data: Input containing question and options
        vector_store: Vector store for retrieval
        embedding_service: Embedding service
        llm_gateway: LLM gateway

    Returns:
        DocumentQAResult with answer and metadata

    Example:
        result = run_document_qa(
            DocumentQAInput(
                question="What are the key features of the product?",
                document_ids=["doc-123"],
                max_chunks=5,
            )
        )
        print(result.answer)
        print(result.sources)
    """
    with tracer.start_as_current_span("document_qa.run") as span:
        start_time = time.time()

        span.set_attribute("tenant_id", input_data.tenant_id)
        span.set_attribute("user_id", input_data.user_id)
        span.set_attribute("question_length", len(input_data.question))

        # Create graph
        graph = create_document_qa_graph(
            vector_store=vector_store,
            embedding_service=embedding_service,
            llm_gateway=llm_gateway,
        )

        # Create initial state
        initial_state = DocumentQAState.from_input(input_data)

        # Run the graph
        final_state_dict = graph.invoke(initial_state.model_dump())

        # Calculate processing time
        processing_time = (time.time() - start_time) * 1000
        final_state_dict["processing_time_ms"] = processing_time

        # Create final state
        final_state = DocumentQAState(**final_state_dict)

        # Create result
        result = DocumentQAResult.from_state(final_state)

        span.set_attribute("success", result.success)
        span.set_attribute("confidence", result.confidence.value)
        span.set_attribute("chunks_retrieved", result.chunks_retrieved)
        span.set_attribute("processing_time_ms", processing_time)

        logger.info(
            "document_qa_completed",
            question=input_data.question[:100],
            success=result.success,
            confidence=result.confidence.value,
            chunks=result.chunks_retrieved,
            latency_ms=round(processing_time, 2),
        )

        return result


async def run_document_qa_async(
    input_data: DocumentQAInput,
    vector_store: VectorStore | None = None,
    embedding_service: EmbeddingService | None = None,
    llm_gateway: LLMGateway | None = None,
) -> DocumentQAResult:
    """
    Async version of run_document_qa.

    For async workflows, wraps the sync implementation.
    Future versions may use fully async nodes.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_document_qa(
            input_data=input_data,
            vector_store=vector_store,
            embedding_service=embedding_service,
            llm_gateway=llm_gateway,
        ),
    )
