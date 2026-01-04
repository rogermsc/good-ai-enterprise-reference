"""
LangGraph workflow for Ticket Triage Agent.

This module defines the agent graph structure with:
- Sequential processing nodes
- Conditional branching based on policy decisions
- State management

The workflow:
1. ingest_ticket - Validate input
2. pii_redact - Tokenize sensitive data
3. classify_severity - LLM severity classification
4. recommend_actions - LLM action recommendations
5. policy_check - Policy engine evaluation
6. generate_response - LLM response (if approved)
7. write_audit_log - Record operation
"""

import asyncpg
from langgraph.graph import END, StateGraph

from src.agents.ticket_triage.models import TicketInput, TicketState, TriageResult
from src.agents.ticket_triage.nodes import TriageNodes, should_generate_response
from src.core.security import SecurityContext


def create_triage_graph(
    security_context: SecurityContext,
    db_conn: asyncpg.Connection | None = None,
) -> StateGraph:
    """
    Create the ticket triage LangGraph workflow.

    Args:
        security_context: User authentication context
        db_conn: Optional database connection for audit logging

    Returns:
        Compiled StateGraph ready for execution
    """
    # Initialize nodes with dependencies
    nodes = TriageNodes(security_context=security_context, db_conn=db_conn)

    # Create the graph with TicketState schema
    workflow = StateGraph(TicketState)

    # Add nodes
    workflow.add_node("ingest_ticket", nodes.ingest_ticket)
    workflow.add_node("pii_redact", nodes.pii_redact)
    workflow.add_node("classify_severity", nodes.classify_severity)
    workflow.add_node("recommend_actions", nodes.recommend_actions)
    workflow.add_node("policy_check", nodes.policy_check)
    workflow.add_node("generate_response", nodes.generate_response)
    workflow.add_node("write_audit_log", nodes.write_audit_log)

    # Define edges (workflow sequence)
    workflow.set_entry_point("ingest_ticket")

    workflow.add_edge("ingest_ticket", "pii_redact")
    workflow.add_edge("pii_redact", "classify_severity")
    workflow.add_edge("classify_severity", "recommend_actions")
    workflow.add_edge("recommend_actions", "policy_check")

    # Conditional edge based on policy decision
    workflow.add_conditional_edges(
        "policy_check",
        should_generate_response,
        {
            "generate_response": "generate_response",
            "write_audit_log": "write_audit_log",
        },
    )

    workflow.add_edge("generate_response", "write_audit_log")
    workflow.add_edge("write_audit_log", END)

    return workflow.compile()


async def run_triage(
    ticket: TicketInput,
    security_context: SecurityContext,
    db_conn: asyncpg.Connection | None = None,
) -> TriageResult:
    """
    Run the ticket triage workflow.

    Args:
        ticket: Input ticket to triage
        security_context: User authentication context
        db_conn: Optional database connection for audit logging

    Returns:
        TriageResult with classification, actions, and response

    Example:
        result = await run_triage(
            ticket=TicketInput(
                ticket_id="TKT-001",
                subject="Password reset needed",
                body="I forgot my password",
            ),
            security_context=SecurityContext(
                user_id="agent-1",
                tenant_id="acme",
                roles=("support_agent",),
            ),
        )
    """
    # Create initial state from ticket input
    initial_state = TicketState(
        ticket_id=ticket.ticket_id,
        subject=ticket.subject,
        body=ticket.body,
        customer_email=ticket.customer_email,
        source=ticket.source,
        metadata=ticket.metadata,
    )

    # Create and run the graph
    graph = create_triage_graph(
        security_context=security_context,
        db_conn=db_conn,
    )

    # Execute workflow
    final_state_dict = await graph.ainvoke(initial_state.model_dump())

    # Convert back to TicketState
    final_state = TicketState(**final_state_dict)

    # Return result
    return TriageResult.from_state(final_state)


async def run_triage_with_state(
    ticket: TicketInput,
    security_context: SecurityContext,
    db_conn: asyncpg.Connection | None = None,
) -> tuple[TriageResult, TicketState]:
    """
    Run triage and return both result and full state.

    Useful for debugging and detailed inspection.
    """
    initial_state = TicketState(
        ticket_id=ticket.ticket_id,
        subject=ticket.subject,
        body=ticket.body,
        customer_email=ticket.customer_email,
        source=ticket.source,
        metadata=ticket.metadata,
    )

    graph = create_triage_graph(
        security_context=security_context,
        db_conn=db_conn,
    )

    final_state_dict = await graph.ainvoke(initial_state.model_dump())
    final_state = TicketState(**final_state_dict)

    return TriageResult.from_state(final_state), final_state
