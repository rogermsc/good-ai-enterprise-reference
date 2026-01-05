"""LangGraph workflow for Data Analyst agent."""

import time

from langgraph.graph import END, StateGraph

from src.agents.data_analyst.models import (
    DataAnalystInput,
    DataAnalystResult,
    DataAnalystState,
)
from src.agents.data_analyst.nodes import DataAnalystNodes
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()


def create_data_analyst_graph() -> StateGraph:
    """
    Create the Data Analyst workflow graph.

    The workflow follows these steps:
    1. classify_intent: Determine what the user wants to know
    2. discover_schema: Find available tables and columns
    3. generate_sql: Create SQL query from natural language
    4. validate_query: Check query safety and correctness
    5. execute_query: Optionally execute the query
    6. generate_explanation: Explain what the query does
    7. summarize_results: Summarize the findings
    8. finalize: Complete processing

    Returns:
        Compiled LangGraph workflow
    """
    nodes = DataAnalystNodes()

    # Create the graph
    workflow = StateGraph(DataAnalystState)

    # Add nodes
    workflow.add_node("classify_intent", nodes.classify_intent)
    workflow.add_node("discover_schema", nodes.discover_schema)
    workflow.add_node("generate_sql", nodes.generate_sql)
    workflow.add_node("validate_query", nodes.validate_query)
    workflow.add_node("execute_query", nodes.execute_query)
    workflow.add_node("generate_explanation", nodes.generate_explanation)
    workflow.add_node("summarize_results", nodes.summarize_results)
    workflow.add_node("finalize", nodes.finalize)

    # Define edges
    workflow.set_entry_point("classify_intent")
    workflow.add_edge("classify_intent", "discover_schema")
    workflow.add_edge("discover_schema", "generate_sql")
    workflow.add_edge("generate_sql", "validate_query")
    workflow.add_edge("validate_query", "execute_query")
    workflow.add_edge("execute_query", "generate_explanation")
    workflow.add_edge("generate_explanation", "summarize_results")
    workflow.add_edge("summarize_results", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()


def run_data_analyst(input_data: DataAnalystInput) -> DataAnalystResult:
    """
    Run the Data Analyst workflow.

    Args:
        input_data: Input containing question and options

    Returns:
        DataAnalystResult with SQL and optional results

    Example:
        result = run_data_analyst(
            DataAnalystInput(
                question="How many orders were placed last month?",
                database="analytics",
                execute=True,
            )
        )
        print(result.generated_sql)
        print(result.results)
    """
    with tracer.start_as_current_span("data_analyst.run") as span:
        start_time = time.time()

        span.set_attribute("tenant_id", input_data.tenant_id)
        span.set_attribute("user_id", input_data.user_id)
        span.set_attribute("question_length", len(input_data.question))
        span.set_attribute("execute", input_data.execute)

        # Create graph
        graph = create_data_analyst_graph()

        # Create initial state
        initial_state = DataAnalystState.from_input(input_data)

        # Run the graph
        final_state_dict = graph.invoke(initial_state.model_dump())

        # Calculate processing time
        processing_time = (time.time() - start_time) * 1000
        final_state_dict["processing_time_ms"] = processing_time

        # Create final state
        final_state = DataAnalystState(**final_state_dict)

        # Create result
        result = DataAnalystResult.from_state(final_state)

        span.set_attribute("success", result.success)
        span.set_attribute("has_sql", result.generated_sql is not None)
        span.set_attribute("processing_time_ms", processing_time)

        logger.info(
            "data_analyst_completed",
            question=input_data.question[:100],
            success=result.success,
            has_sql=result.generated_sql is not None,
            latency_ms=round(processing_time, 2),
        )

        return result
