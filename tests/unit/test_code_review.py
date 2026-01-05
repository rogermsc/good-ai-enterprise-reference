"""Tests for Code Review agent."""

import pytest

from src.agents.code_review import (
    CodeReviewInput,
    CodeReviewResult,
    CodeReviewState,
    create_code_review_graph,
    run_code_review,
)
from src.agents.code_review.models import (
    CodeIssue,
    FileAnalysis,
    IssueCategory,
    IssueSeverity,
    ReviewDecision,
)
from src.agents.code_review.nodes import CodeReviewNodes


class TestCodeReviewInput:
    """Tests for CodeReviewInput model."""

    def test_default_values(self) -> None:
        input_data = CodeReviewInput(code="def foo(): pass")
        assert input_data.code == "def foo(): pass"
        assert input_data.language == "python"
        assert input_data.check_security is True

    def test_custom_values(self) -> None:
        input_data = CodeReviewInput(
            code="function foo() {}",
            file_path="src/utils.js",
            language="javascript",
            check_security=True,
            check_style=False,
        )
        assert input_data.language == "javascript"
        assert input_data.check_style is False


class TestCodeReviewState:
    """Tests for CodeReviewState model."""

    def test_from_input(self) -> None:
        input_data = CodeReviewInput(
            code="print('hello')",
            file_path="main.py",
        )
        state = CodeReviewState.from_input(input_data)

        assert state.code == "print('hello')"
        assert state.file_path == "main.py"
        assert state.decision is None


class TestCodeReviewResult:
    """Tests for CodeReviewResult model."""

    def test_from_state(self) -> None:
        state = CodeReviewState(
            code="def foo(): pass",
            file_path="test.py",
            language="python",
            decision=ReviewDecision.APPROVE,
            quality_score=95.0,
            issues=[{"severity": "low", "message": "Minor issue"}],
        )
        result = CodeReviewResult.from_state(state)

        assert result.decision == ReviewDecision.APPROVE
        assert result.quality_score == 95.0
        assert result.issue_counts["low"] == 1

    def test_success_property(self) -> None:
        state = CodeReviewState(
            code="code",
            decision=ReviewDecision.APPROVE,
        )
        result = CodeReviewResult.from_state(state)
        assert result.success is True

    def test_has_critical_issues(self) -> None:
        state = CodeReviewState(
            code="code",
            decision=ReviewDecision.REQUEST_CHANGES,
            issues=[{"severity": "critical", "message": "Security issue"}],
        )
        result = CodeReviewResult.from_state(state)
        assert result.has_critical_issues is True


class TestCodeIssue:
    """Tests for CodeIssue model."""

    def test_create_issue(self) -> None:
        issue = CodeIssue(
            category=IssueCategory.SECURITY,
            severity=IssueSeverity.CRITICAL,
            message="SQL injection detected",
            file_path="db.py",
            line_start=10,
        )
        assert issue.category == IssueCategory.SECURITY
        assert issue.severity == IssueSeverity.CRITICAL

    def test_serialization(self) -> None:
        issue = CodeIssue(
            category=IssueCategory.BUG,
            severity=IssueSeverity.HIGH,
            message="Null pointer",
            suggestion="Add null check",
        )
        data = issue.to_dict()
        assert data["category"] == "bug"
        assert data["suggestion"] == "Add null check"


class TestFileAnalysis:
    """Tests for FileAnalysis model."""

    def test_create_analysis(self) -> None:
        analysis = FileAnalysis(
            path="main.py",
            language="python",
            lines_added=50,
            lines_removed=10,
        )
        assert analysis.path == "main.py"
        assert analysis.score == 100.0


class TestCodeReviewNodes:
    """Tests for CodeReviewNodes."""

    @pytest.fixture
    def nodes(self) -> CodeReviewNodes:
        return CodeReviewNodes()

    def test_analyze_file(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="line1\nline2\nline3",
            file_path="test.py",
            language="python",
        )
        result = nodes.analyze_file(state)

        assert result["file_analysis"]["path"] == "test.py"
        assert result["file_analysis"]["lines_added"] == 3

    def test_check_security_eval(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="result = eval(user_input)",
            file_path="test.py",
        )
        result = nodes.check_security(state)

        assert len(result["issues"]) > 0
        assert result["issues"][0]["category"] == "security"
        assert result["issues"][0]["severity"] == "critical"

    def test_check_security_exec(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="exec(code_string)",
            file_path="test.py",
        )
        result = nodes.check_security(state)
        assert any(i["message"] for i in result["issues"] if "exec" in i["message"].lower())

    def test_check_security_hardcoded_password(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code='password = "secret123"',
            file_path="config.py",
        )
        result = nodes.check_security(state)
        assert any("password" in i["message"].lower() for i in result["issues"])

    def test_check_security_disabled(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="eval(x)",
            file_path="test.py",
            check_security=False,
        )
        result = nodes.check_security(state)
        assert "issues" not in result or len(result.get("issues", [])) == 0

    def test_check_style_print(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="print('debug')",
            file_path="main.py",
            issues=[],
        )
        result = nodes.check_style(state)
        assert any("print" in i["message"].lower() for i in result["issues"])

    def test_check_style_todo(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="# TODO: fix this later",
            file_path="main.py",
            issues=[],
        )
        result = nodes.check_style(state)
        assert any("TODO" in i["message"] for i in result["issues"])

    def test_check_style_bare_except(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="try:\n    x = 1\nexcept:\n    pass",
            file_path="main.py",
            issues=[],
        )
        result = nodes.check_style(state)
        assert any("except" in i["message"].lower() for i in result["issues"])

    def test_check_style_long_line(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="x = " + "a" * 150,
            file_path="main.py",
            issues=[],
        )
        result = nodes.check_style(state)
        assert any("line" in i["message"].lower() for i in result["issues"])

    def test_check_performance_range_len(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="for i in range(len(items)):",
            file_path="main.py",
            issues=[],
        )
        result = nodes.check_performance(state)
        assert any("enumerate" in i["message"].lower() for i in result["issues"])

    def test_check_performance_disabled(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="for i in range(len(x)):",
            file_path="main.py",
            check_performance=False,
            issues=[],
        )
        result = nodes.check_performance(state)
        assert len(result.get("issues", [])) == 0

    def test_check_testing_no_assertions(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="def test_something():\n    x = 1\n    return x",
            file_path="test_main.py",
            issues=[],
        )
        result = nodes.check_testing(state)
        assert any("assertion" in i["message"].lower() for i in result["issues"])

    def test_calculate_score_no_issues(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(code="x = 1", issues=[])
        result = nodes.calculate_score(state)
        assert result["quality_score"] == 100.0

    def test_calculate_score_critical_issue(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="x = 1",
            issues=[{"severity": "critical", "message": "Bad"}],
        )
        result = nodes.calculate_score(state)
        assert result["quality_score"] == 75.0

    def test_calculate_score_multiple_issues(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="x = 1",
            issues=[
                {"severity": "critical", "message": "Bad"},
                {"severity": "high", "message": "Also bad"},
                {"severity": "medium", "message": "Not great"},
            ],
        )
        result = nodes.calculate_score(state)
        assert result["quality_score"] == 55.0  # 100 - 25 - 15 - 5

    def test_make_decision_approve(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="x = 1",
            issues=[],
            quality_score=95.0,
        )
        result = nodes.make_decision(state)
        assert result["decision"] == ReviewDecision.APPROVE

    def test_make_decision_request_changes_critical(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="eval(x)",
            issues=[{"severity": "critical", "message": "Security"}],
            quality_score=75.0,
        )
        result = nodes.make_decision(state)
        assert result["decision"] == ReviewDecision.REQUEST_CHANGES

    def test_make_decision_comment(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="x = 1",
            issues=[{"severity": "medium", "message": "Style"}],
            quality_score=70.0,
        )
        result = nodes.make_decision(state)
        assert result["decision"] == ReviewDecision.COMMENT

    def test_generate_summary_no_issues(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="x = 1",
            issues=[],
            decision=ReviewDecision.APPROVE,
        )
        result = nodes.generate_summary(state)
        assert "good" in result["summary"].lower()
        assert len(result["suggestions"]) == 0

    def test_generate_summary_with_issues(self, nodes: CodeReviewNodes) -> None:
        state = CodeReviewState(
            code="eval(x)",
            issues=[
                {"category": "security", "severity": "critical", "message": "Bad"},
                {"category": "style", "severity": "low", "message": "Minor"},
            ],
            decision=ReviewDecision.REQUEST_CHANGES,
        )
        result = nodes.generate_summary(state)
        assert "2 issue" in result["summary"]
        assert len(result["suggestions"]) > 0


class TestCodeReviewGraph:
    """Tests for Code Review graph."""

    def test_create_graph(self) -> None:
        graph = create_code_review_graph()
        assert graph is not None

    def test_run_clean_code(self) -> None:
        input_data = CodeReviewInput(
            code="def add(a: int, b: int) -> int:\n    return a + b",
            file_path="math_utils.py",
        )

        result = run_code_review(input_data)

        assert isinstance(result, CodeReviewResult)
        assert result.success is True
        assert result.decision == ReviewDecision.APPROVE
        assert result.quality_score >= 80

    def test_run_with_security_issue(self) -> None:
        input_data = CodeReviewInput(
            code='password = "secret123"\nresult = eval(user_input)',
            file_path="unsafe.py",
        )

        result = run_code_review(input_data)

        assert result.success is True
        assert result.decision == ReviewDecision.REQUEST_CHANGES
        assert result.has_critical_issues is True
        assert "critical" in result.issue_counts

    def test_run_with_style_issues(self) -> None:
        input_data = CodeReviewInput(
            code='print("debug")\n# TODO: fix this',
            file_path="debug.py",
            check_security=False,
        )

        result = run_code_review(input_data)

        assert result.success is True
        assert len(result.issues) > 0

    def test_run_processing_time(self) -> None:
        input_data = CodeReviewInput(code="x = 1")

        result = run_code_review(input_data)

        assert result.processing_time_ms > 0
