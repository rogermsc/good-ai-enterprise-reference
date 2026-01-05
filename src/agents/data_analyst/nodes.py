"""Node implementations for Data Analyst agent."""

import re
import time
from typing import Any

from src.agents.data_analyst.models import (
    DataAnalystState,
    QueryIntent,
    QueryRisk,
    QueryValidation,
    TableSchema,
)
from src.core.config import get_settings
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()

# SQL keywords that indicate potentially dangerous operations
DANGEROUS_KEYWORDS = [
    "drop",
    "delete",
    "truncate",
    "update",
    "insert",
    "alter",
    "create",
    "grant",
    "revoke",
    "exec",
    "execute",
    "xp_",
    "sp_",
    "--",
    ";--",
    "/*",
    "*/",
]

# Mock schema for testing
MOCK_SCHEMA: dict[str, TableSchema] = {
    "customers": TableSchema(
        name="customers",
        columns=[
            {"name": "id", "type": "integer", "description": "Primary key"},
            {"name": "name", "type": "varchar", "description": "Customer name"},
            {"name": "email", "type": "varchar", "description": "Email address"},
            {"name": "created_at", "type": "timestamp", "description": "Creation date"},
            {"name": "region", "type": "varchar", "description": "Geographic region"},
        ],
        row_count=10000,
        description="Customer information",
    ),
    "orders": TableSchema(
        name="orders",
        columns=[
            {"name": "id", "type": "integer", "description": "Primary key"},
            {"name": "customer_id", "type": "integer", "description": "Foreign key to customers"},
            {"name": "total", "type": "decimal", "description": "Order total"},
            {"name": "status", "type": "varchar", "description": "Order status"},
            {"name": "created_at", "type": "timestamp", "description": "Order date"},
        ],
        row_count=50000,
        description="Customer orders",
    ),
    "products": TableSchema(
        name="products",
        columns=[
            {"name": "id", "type": "integer", "description": "Primary key"},
            {"name": "name", "type": "varchar", "description": "Product name"},
            {"name": "category", "type": "varchar", "description": "Product category"},
            {"name": "price", "type": "decimal", "description": "Unit price"},
            {"name": "stock", "type": "integer", "description": "Current stock"},
        ],
        row_count=1000,
        description="Product catalog",
    ),
}


class DataAnalystNodes:
    """Node implementations for Data Analyst workflow."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.schema = MOCK_SCHEMA

    def classify_intent(self, state: DataAnalystState) -> dict[str, Any]:
        """Classify the intent of the question."""
        with tracer.start_as_current_span("data_analyst.classify_intent"):
            question = state.question.lower()

            aggregate_keywords = [
                "count",
                "how many",
                "total number",
                "sum",
                "average",
                "avg",
                "total",
                "mean",
            ]
            if any(word in question for word in aggregate_keywords):
                intent = QueryIntent.AGGREGATE
            elif any(word in question for word in ["top", "best", "highest", "lowest", "rank"]):
                intent = QueryIntent.TOP_N
            elif any(word in question for word in ["trend", "over time", "by month", "by year"]):
                intent = QueryIntent.TREND
            elif any(word in question for word in ["compare", "versus", "vs", "difference"]):
                intent = QueryIntent.COMPARISON
            elif any(word in question for word in ["and", "with", "join", "related"]):
                intent = QueryIntent.JOIN
            else:
                intent = QueryIntent.SELECT

            logger.info(
                "intent_classified",
                question=state.question[:100],
                intent=intent.value,
            )

            return {"intent": intent}

    def discover_schema(self, state: DataAnalystState) -> dict[str, Any]:
        """Discover available tables and their schemas."""
        with tracer.start_as_current_span("data_analyst.discover_schema"):
            # Use specified tables or all available
            if state.tables:
                available = [self.schema[t].to_dict() for t in state.tables if t in self.schema]
            else:
                available = [t.to_dict() for t in self.schema.values()]

            # Select relevant tables based on question
            question_lower = state.question.lower()
            selected = []
            for table in available:
                table_name = table["name"]
                # Check if table or its columns are mentioned
                if table_name in question_lower:
                    selected.append(table_name)
                else:
                    for col in table["columns"]:
                        if col["name"] in question_lower:
                            selected.append(table_name)
                            break

            # If no specific tables detected, use all available
            if not selected:
                selected = [t["name"] for t in available]

            logger.info(
                "schema_discovered",
                available_tables=len(available),
                selected_tables=selected,
            )

            return {
                "available_tables": available,
                "selected_tables": selected,
            }

    def generate_sql(self, state: DataAnalystState) -> dict[str, Any]:
        """Generate SQL query from natural language."""
        with tracer.start_as_current_span("data_analyst.generate_sql") as span:
            question = state.question.lower()
            tables = state.selected_tables

            if not tables:
                return {
                    "generated_sql": None,
                    "errors": [*state.errors, "No tables available for query"],
                }

            # Build SQL based on intent (simplified mock generation)
            primary_table = tables[0]

            if state.intent == QueryIntent.AGGREGATE:
                if "count" in question:
                    sql = f"SELECT COUNT(*) as count FROM {primary_table}"
                elif "sum" in question or "total" in question:
                    # Find numeric column
                    table_schema = self.schema.get(primary_table)
                    numeric_col = "id"
                    if table_schema:
                        for col in table_schema.columns:
                            if col["type"] in ["decimal", "integer", "float"]:
                                numeric_col = col["name"]
                                break
                    sql = f"SELECT SUM({numeric_col}) as total FROM {primary_table}"
                else:
                    sql = f"SELECT COUNT(*) as count FROM {primary_table}"

            elif state.intent == QueryIntent.TOP_N:
                limit = 10  # Default top N
                for word in question.split():
                    if word.isdigit():
                        limit = int(word)
                        break
                sql = f"SELECT * FROM {primary_table} ORDER BY id DESC LIMIT {limit}"

            elif state.intent == QueryIntent.TREND:
                sql = f"SELECT DATE_TRUNC('month', created_at) as period, COUNT(*) as count FROM {primary_table} GROUP BY 1 ORDER BY 1"

            elif state.intent == QueryIntent.JOIN and len(tables) > 1:
                t1, t2 = tables[0], tables[1]
                sql = f"SELECT * FROM {t1} JOIN {t2} ON {t1}.id = {t2}.{t1[:-1]}_id LIMIT {state.max_rows}"

            else:
                # Default SELECT
                sql = f"SELECT * FROM {primary_table} LIMIT {state.max_rows}"

            span.set_attribute("generated_sql_length", len(sql))

            logger.info(
                "sql_generated",
                intent=state.intent.value if state.intent else "unknown",
                sql_preview=sql[:100],
            )

            return {"generated_sql": sql}

    def validate_query(self, state: DataAnalystState) -> dict[str, Any]:
        """Validate the generated SQL for safety and correctness."""
        with tracer.start_as_current_span("data_analyst.validate_query"):
            if not state.generated_sql:
                return {
                    "validation": QueryValidation(
                        is_valid=False,
                        is_safe=False,
                        risk_level=QueryRisk.BLOCKED,
                        issues=["No SQL query to validate"],
                    ).to_dict()
                }

            sql_lower = state.generated_sql.lower()
            issues = []
            suggestions = []
            is_safe = True
            risk_level = QueryRisk.LOW

            # Check for dangerous keywords
            for keyword in DANGEROUS_KEYWORDS:
                if keyword in sql_lower:
                    issues.append(f"Potentially dangerous keyword detected: {keyword}")
                    is_safe = False
                    risk_level = QueryRisk.BLOCKED

            # Check for SELECT-only
            if not sql_lower.strip().startswith("select"):
                issues.append("Only SELECT queries are allowed")
                is_safe = False
                risk_level = QueryRisk.BLOCKED

            # Check for LIMIT clause
            if "limit" not in sql_lower:
                suggestions.append("Consider adding LIMIT to prevent large result sets")
                if risk_level == QueryRisk.LOW:
                    risk_level = QueryRisk.MEDIUM

            # Check for full table scans
            if "*" in state.generated_sql and "where" not in sql_lower:
                suggestions.append("Consider adding WHERE clause to limit data")
                if risk_level == QueryRisk.LOW:
                    risk_level = QueryRisk.MEDIUM

            # Check for joins without conditions
            if "join" in sql_lower and "on" not in sql_lower:
                issues.append("JOIN without ON condition detected")
                risk_level = QueryRisk.HIGH

            validation = QueryValidation(
                is_valid=len(issues) == 0 or (is_safe and risk_level != QueryRisk.BLOCKED),
                is_safe=is_safe,
                risk_level=risk_level,
                issues=issues,
                suggestions=suggestions,
            )

            logger.info(
                "query_validated",
                is_valid=validation.is_valid,
                is_safe=validation.is_safe,
                risk_level=risk_level.value,
                issue_count=len(issues),
            )

            return {"validation": validation.to_dict()}

    def execute_query(self, state: DataAnalystState) -> dict[str, Any]:
        """Execute the query (mock implementation)."""
        with tracer.start_as_current_span("data_analyst.execute_query") as span:
            if not state.execute:
                return {"query_executed": False}

            validation = state.validation or {}
            if not validation.get("is_safe", False):
                return {
                    "query_executed": False,
                    "errors": [*state.errors, "Query failed safety validation"],
                }

            start_time = time.time()

            # Mock execution - generate sample results
            results = []
            row_count = 0

            if state.generated_sql:
                sql_lower = state.generated_sql.lower()

                if "count" in sql_lower:
                    results = [{"count": 1234}]
                    row_count = 1
                elif "sum" in sql_lower:
                    results = [{"total": 98765.43}]
                    row_count = 1
                else:
                    # Generate mock rows
                    for i in range(min(5, state.max_rows)):
                        results.append(
                            {
                                "id": i + 1,
                                "name": f"Item {i + 1}",
                                "value": (i + 1) * 100,
                            }
                        )
                    row_count = len(results)

            execution_time = (time.time() - start_time) * 1000
            span.set_attribute("row_count", row_count)
            span.set_attribute("execution_time_ms", execution_time)

            logger.info(
                "query_executed",
                row_count=row_count,
                execution_time_ms=round(execution_time, 2),
            )

            return {
                "query_executed": True,
                "results": results,
                "row_count": row_count,
                "execution_time_ms": execution_time,
            }

    def generate_explanation(self, state: DataAnalystState) -> dict[str, Any]:
        """Generate explanation of the query."""
        with tracer.start_as_current_span("data_analyst.generate_explanation"):
            if not state.include_explanation or not state.generated_sql:
                return {"explanation": None}

            sql = state.generated_sql

            # Generate simple explanation based on SQL structure
            explanation_parts = []

            if "SELECT *" in sql:
                explanation_parts.append("This query retrieves all columns")
            elif "SELECT COUNT" in sql.upper():
                explanation_parts.append("This query counts the number of records")
            elif "SELECT SUM" in sql.upper():
                explanation_parts.append("This query calculates a total sum")

            # Identify tables
            tables = re.findall(r"FROM\s+(\w+)", sql, re.IGNORECASE)
            if tables:
                explanation_parts.append(f"from the {', '.join(tables)} table(s)")

            # Check for filters
            if "WHERE" in sql.upper():
                explanation_parts.append("with specific filter conditions")

            # Check for grouping
            if "GROUP BY" in sql.upper():
                explanation_parts.append("grouped by specified columns")

            # Check for ordering
            if "ORDER BY" in sql.upper():
                if "DESC" in sql.upper():
                    explanation_parts.append("sorted in descending order")
                else:
                    explanation_parts.append("sorted in ascending order")

            # Check for limit
            limit_match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
            if limit_match:
                explanation_parts.append(f"limited to {limit_match.group(1)} results")

            explanation = ". ".join(explanation_parts) + "." if explanation_parts else None

            return {"explanation": explanation}

    def summarize_results(self, state: DataAnalystState) -> dict[str, Any]:
        """Summarize query results."""
        with tracer.start_as_current_span("data_analyst.summarize_results"):
            if not state.query_executed or not state.results:
                return {"summary": None}

            # Generate summary based on results
            if state.row_count == 1 and len(state.results) == 1:
                # Single value result
                result = state.results[0]
                if "count" in result:
                    summary = f"The query returned a count of {result['count']:,}."
                elif "total" in result:
                    summary = f"The calculated total is {result['total']:,.2f}."
                else:
                    summary = f"Query returned: {result}"
            else:
                summary = f"The query returned {state.row_count} row(s) in {state.execution_time_ms:.2f}ms."

            return {"summary": summary}

    def finalize(self, state: DataAnalystState) -> dict[str, Any]:
        """Finalize the response."""
        with tracer.start_as_current_span("data_analyst.finalize"):
            logger.info(
                "data_analyst_complete",
                question=state.question[:100],
                has_sql=state.generated_sql is not None,
                executed=state.query_executed,
                error_count=len(state.errors),
            )

            return {}
