"""Tests for Data Analyst agent."""

import pytest

from src.agents.data_analyst import (
    DataAnalystInput,
    DataAnalystResult,
    DataAnalystState,
    create_data_analyst_graph,
    run_data_analyst,
)
from src.agents.data_analyst.models import QueryIntent, QueryRisk, QueryValidation, TableSchema
from src.agents.data_analyst.nodes import DataAnalystNodes


class TestDataAnalystInput:
    """Tests for DataAnalystInput model."""

    def test_default_values(self) -> None:
        input_data = DataAnalystInput(question="How many customers do we have?")
        assert input_data.question == "How many customers do we have?"
        assert input_data.database == "default"
        assert input_data.max_rows == 100
        assert input_data.execute is False

    def test_custom_values(self) -> None:
        input_data = DataAnalystInput(
            question="Show top 10 orders",
            database="analytics",
            tables=["orders"],
            max_rows=50,
            execute=True,
        )
        assert input_data.database == "analytics"
        assert input_data.tables == ["orders"]
        assert input_data.execute is True


class TestDataAnalystState:
    """Tests for DataAnalystState model."""

    def test_from_input(self) -> None:
        input_data = DataAnalystInput(
            question="What is the total revenue?",
            database="sales",
            execute=True,
        )
        state = DataAnalystState.from_input(input_data)

        assert state.question == "What is the total revenue?"
        assert state.database == "sales"
        assert state.execute is True
        assert state.generated_sql is None


class TestDataAnalystResult:
    """Tests for DataAnalystResult model."""

    def test_from_state(self) -> None:
        state = DataAnalystState(
            question="Count customers",
            intent=QueryIntent.AGGREGATE,
            generated_sql="SELECT COUNT(*) FROM customers",
            row_count=1,
            results=[{"count": 1000}],
        )
        result = DataAnalystResult.from_state(state)

        assert result.question == "Count customers"
        assert result.intent == QueryIntent.AGGREGATE
        assert result.success is True

    def test_success_no_sql(self) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql=None,
        )
        result = DataAnalystResult.from_state(state)
        assert result.success is False


class TestQueryValidation:
    """Tests for QueryValidation model."""

    def test_valid_query(self) -> None:
        validation = QueryValidation(
            is_valid=True,
            is_safe=True,
            risk_level=QueryRisk.LOW,
        )
        assert validation.is_valid is True
        assert validation.risk_level == QueryRisk.LOW

    def test_serialization(self) -> None:
        validation = QueryValidation(
            is_valid=False,
            is_safe=False,
            risk_level=QueryRisk.BLOCKED,
            issues=["Dangerous keyword"],
        )
        data = validation.to_dict()
        assert data["risk_level"] == "blocked"
        assert len(data["issues"]) == 1


class TestTableSchema:
    """Tests for TableSchema model."""

    def test_create_schema(self) -> None:
        schema = TableSchema(
            name="users",
            columns=[
                {"name": "id", "type": "integer", "description": "PK"},
                {"name": "email", "type": "varchar", "description": "Email"},
            ],
            row_count=1000,
        )
        assert schema.name == "users"
        assert len(schema.columns) == 2

    def test_serialization(self) -> None:
        schema = TableSchema(
            name="orders",
            columns=[{"name": "id", "type": "integer", "description": "PK"}],
            is_sensitive=True,
        )
        data = schema.to_dict()
        assert data["is_sensitive"] is True


class TestDataAnalystNodes:
    """Tests for DataAnalystNodes."""

    @pytest.fixture
    def nodes(self) -> DataAnalystNodes:
        return DataAnalystNodes()

    def test_classify_aggregate_intent(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="How many customers are there?")
        result = nodes.classify_intent(state)
        assert result["intent"] == QueryIntent.AGGREGATE

    def test_classify_count_intent(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="Count all orders")
        result = nodes.classify_intent(state)
        assert result["intent"] == QueryIntent.AGGREGATE

    def test_classify_sum_intent(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="What is the total revenue?")
        result = nodes.classify_intent(state)
        assert result["intent"] == QueryIntent.AGGREGATE

    def test_classify_top_n_intent(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="Show top 10 customers")
        result = nodes.classify_intent(state)
        assert result["intent"] == QueryIntent.TOP_N

    def test_classify_trend_intent(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="Orders by month over time")
        result = nodes.classify_intent(state)
        assert result["intent"] == QueryIntent.TREND

    def test_classify_comparison_intent(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="Compare sales vs last year")
        result = nodes.classify_intent(state)
        assert result["intent"] == QueryIntent.COMPARISON

    def test_classify_select_intent(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="Show me all products")
        result = nodes.classify_intent(state)
        assert result["intent"] == QueryIntent.SELECT

    def test_discover_schema(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(question="Show customers")
        result = nodes.discover_schema(state)

        assert len(result["available_tables"]) > 0
        assert "customers" in result["selected_tables"]

    def test_discover_schema_specific_tables(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Show data",
            tables=["orders", "products"],
        )
        result = nodes.discover_schema(state)
        assert len(result["available_tables"]) == 2

    def test_generate_sql_count(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="How many customers?",
            intent=QueryIntent.AGGREGATE,
            selected_tables=["customers"],
        )
        result = nodes.generate_sql(state)

        assert result["generated_sql"] is not None
        assert "COUNT" in result["generated_sql"].upper()

    def test_generate_sql_top_n(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Top 5 orders",
            intent=QueryIntent.TOP_N,
            selected_tables=["orders"],
        )
        result = nodes.generate_sql(state)

        assert "LIMIT 5" in result["generated_sql"]

    def test_generate_sql_no_tables(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Show data",
            intent=QueryIntent.SELECT,
            selected_tables=[],
        )
        result = nodes.generate_sql(state)

        assert result["generated_sql"] is None
        assert len(result["errors"]) > 0

    def test_validate_safe_query(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="SELECT * FROM customers LIMIT 10",
        )
        result = nodes.validate_query(state)

        assert result["validation"]["is_valid"] is True
        assert result["validation"]["is_safe"] is True

    def test_validate_dangerous_query(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="DROP TABLE customers",
        )
        result = nodes.validate_query(state)

        assert result["validation"]["is_safe"] is False
        assert result["validation"]["risk_level"] == "blocked"

    def test_validate_delete_blocked(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="DELETE FROM customers WHERE id = 1",
        )
        result = nodes.validate_query(state)
        assert result["validation"]["is_safe"] is False

    def test_validate_no_limit_warning(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="SELECT * FROM customers",
        )
        result = nodes.validate_query(state)

        assert len(result["validation"]["suggestions"]) > 0
        assert any("LIMIT" in s for s in result["validation"]["suggestions"])

    def test_execute_query_disabled(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="SELECT * FROM customers",
            execute=False,
        )
        result = nodes.execute_query(state)
        assert result["query_executed"] is False

    def test_execute_query_count(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Count",
            generated_sql="SELECT COUNT(*) FROM customers",
            validation={"is_safe": True},
            execute=True,
        )
        result = nodes.execute_query(state)

        assert result["query_executed"] is True
        assert result["row_count"] == 1
        assert "count" in result["results"][0]

    def test_execute_unsafe_blocked(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="SELECT * FROM customers",
            validation={"is_safe": False},
            execute=True,
        )
        result = nodes.execute_query(state)
        assert result["query_executed"] is False

    def test_generate_explanation(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="SELECT * FROM customers ORDER BY id DESC LIMIT 10",
            include_explanation=True,
        )
        result = nodes.generate_explanation(state)

        assert result["explanation"] is not None
        assert "customers" in result["explanation"].lower()
        assert "descending" in result["explanation"].lower()

    def test_generate_explanation_disabled(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            generated_sql="SELECT * FROM customers",
            include_explanation=False,
        )
        result = nodes.generate_explanation(state)
        assert result["explanation"] is None

    def test_summarize_count_result(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            query_executed=True,
            results=[{"count": 1234}],
            row_count=1,
        )
        result = nodes.summarize_results(state)
        assert "1,234" in result["summary"]

    def test_summarize_multiple_results(self, nodes: DataAnalystNodes) -> None:
        state = DataAnalystState(
            question="Test",
            query_executed=True,
            results=[{"id": 1}, {"id": 2}],
            row_count=2,
            execution_time_ms=50.0,
        )
        result = nodes.summarize_results(state)
        assert "2 row" in result["summary"]


class TestDataAnalystGraph:
    """Tests for Data Analyst graph."""

    def test_create_graph(self) -> None:
        graph = create_data_analyst_graph()
        assert graph is not None

    def test_run_count_query(self) -> None:
        input_data = DataAnalystInput(
            question="How many customers do we have?",
            tenant_id="test-tenant",
        )

        result = run_data_analyst(input_data)

        assert isinstance(result, DataAnalystResult)
        assert result.success is True
        assert result.intent == QueryIntent.AGGREGATE
        assert result.generated_sql is not None
        assert "COUNT" in result.generated_sql.upper()

    def test_run_select_query(self) -> None:
        input_data = DataAnalystInput(
            question="Show me all products",
            max_rows=50,
        )

        result = run_data_analyst(input_data)

        assert result.success is True
        assert "LIMIT 50" in result.generated_sql

    def test_run_with_execution(self) -> None:
        input_data = DataAnalystInput(
            question="Count all orders",
            execute=True,
        )

        result = run_data_analyst(input_data)

        assert result.success is True
        assert result.row_count > 0
        assert result.execution_time_ms > 0

    def test_run_with_explanation(self) -> None:
        input_data = DataAnalystInput(
            question="Top 5 customers",
            include_explanation=True,
        )

        result = run_data_analyst(input_data)

        assert result.success is True
        assert result.explanation is not None
