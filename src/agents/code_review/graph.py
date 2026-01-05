"""LangGraph workflow for Code Review agent."""

import time

from langgraph.graph import END, StateGraph

from src.agents.code_review.models import (
    CodeReviewInput,
    CodeReviewResult,
    CodeReviewState,
)
from src.agents.code_review.nodes import CodeReviewNodes
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()


def create_code_review_graph() -> StateGraph:
    """
    Create the Code Review workflow graph.

    The workflow follows these steps:
    1. analyze_file: Gather file metadata
    2. check_security: Check for security vulnerabilities
    3. check_style: Check code style issues
    4. check_performance: Check performance concerns
    5. check_testing: Check testing patterns
    6. calculate_score: Calculate quality score
    7. make_decision: Make approve/reject decision
    8. generate_summary: Generate review summary
    9. finalize: Complete processing

    Returns:
        Compiled LangGraph workflow
    """
    nodes = CodeReviewNodes()

    # Create the graph
    workflow = StateGraph(CodeReviewState)

    # Add nodes
    workflow.add_node("analyze_file", nodes.analyze_file)
    workflow.add_node("check_security", nodes.check_security)
    workflow.add_node("check_style", nodes.check_style)
    workflow.add_node("check_performance", nodes.check_performance)
    workflow.add_node("check_testing", nodes.check_testing)
    workflow.add_node("calculate_score", nodes.calculate_score)
    workflow.add_node("make_decision", nodes.make_decision)
    workflow.add_node("generate_summary", nodes.generate_summary)
    workflow.add_node("finalize", nodes.finalize)

    # Define edges
    workflow.set_entry_point("analyze_file")
    workflow.add_edge("analyze_file", "check_security")
    workflow.add_edge("check_security", "check_style")
    workflow.add_edge("check_style", "check_performance")
    workflow.add_edge("check_performance", "check_testing")
    workflow.add_edge("check_testing", "calculate_score")
    workflow.add_edge("calculate_score", "make_decision")
    workflow.add_edge("make_decision", "generate_summary")
    workflow.add_edge("generate_summary", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()


def run_code_review(input_data: CodeReviewInput) -> CodeReviewResult:
    """
    Run the Code Review workflow.

    Args:
        input_data: Input containing code to review

    Returns:
        CodeReviewResult with issues and decision

    Example:
        result = run_code_review(
            CodeReviewInput(
                code=\"\"\"
                def process_input(user_input):
                    return eval(user_input)
                \"\"\",
                file_path="utils.py",
                language="python",
            )
        )
        print(result.decision)
        print(result.issues)
    """
    with tracer.start_as_current_span("code_review.run") as span:
        start_time = time.time()

        span.set_attribute("tenant_id", input_data.tenant_id)
        span.set_attribute("user_id", input_data.user_id)
        span.set_attribute("file_path", input_data.file_path)
        span.set_attribute("language", input_data.language)

        # Create graph
        graph = create_code_review_graph()

        # Create initial state
        initial_state = CodeReviewState.from_input(input_data)

        # Run the graph
        final_state_dict = graph.invoke(initial_state.model_dump())

        # Calculate processing time
        processing_time = (time.time() - start_time) * 1000
        final_state_dict["processing_time_ms"] = processing_time

        # Create final state
        final_state = CodeReviewState(**final_state_dict)

        # Create result
        result = CodeReviewResult.from_state(final_state)

        span.set_attribute("success", result.success)
        span.set_attribute("decision", result.decision.value if result.decision else "none")
        span.set_attribute("issue_count", len(result.issues))
        span.set_attribute("processing_time_ms", processing_time)

        logger.info(
            "code_review_completed",
            file_path=input_data.file_path,
            success=result.success,
            decision=result.decision.value if result.decision else None,
            issues=len(result.issues),
            latency_ms=round(processing_time, 2),
        )

        return result
