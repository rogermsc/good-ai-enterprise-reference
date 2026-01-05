"""Node implementations for Code Review agent."""

import re
from typing import Any, ClassVar

from src.agents.code_review.models import (
    CodeIssue,
    CodeReviewState,
    FileAnalysis,
    IssueCategory,
    IssueSeverity,
    ReviewDecision,
)
from src.core.config import get_settings
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()


class CodeReviewNodes:
    """Node implementations for Code Review workflow."""

    # Security patterns to detect
    SECURITY_PATTERNS: ClassVar[list[tuple[str, str, IssueSeverity]]] = [
        (r"eval\s*\(", "Use of eval() is dangerous", IssueSeverity.CRITICAL),
        (r"exec\s*\(", "Use of exec() is dangerous", IssueSeverity.CRITICAL),
        (r"__import__\s*\(", "Dynamic import can be dangerous", IssueSeverity.HIGH),
        (r"pickle\.loads?", "Pickle can execute arbitrary code", IssueSeverity.HIGH),
        (r"subprocess\.call.*shell\s*=\s*True", "Shell injection risk", IssueSeverity.CRITICAL),
        (r"os\.system\s*\(", "Command injection risk", IssueSeverity.CRITICAL),
        (r"password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded password", IssueSeverity.CRITICAL),
        (r"api_key\s*=\s*['\"][^'\"]+['\"]", "Hardcoded API key", IssueSeverity.CRITICAL),
        (r"secret\s*=\s*['\"][^'\"]+['\"]", "Hardcoded secret", IssueSeverity.CRITICAL),
        (r"SELECT.*\+.*input|input.*\+.*SELECT", "Possible SQL injection", IssueSeverity.CRITICAL),
        (r"innerHTML\s*=", "XSS risk with innerHTML", IssueSeverity.HIGH),
        (r"dangerouslySetInnerHTML", "XSS risk with dangerouslySetInnerHTML", IssueSeverity.MEDIUM),
    ]

    # Style patterns to detect
    STYLE_PATTERNS: ClassVar[list[tuple[str, str, IssueSeverity]]] = [
        (r"^\s{0,3}[a-z]", "Use consistent indentation", IssueSeverity.LOW),
        (r"print\s*\(", "Remove print statements before production", IssueSeverity.LOW),
        (r"# TODO", "TODO comment found", IssueSeverity.INFO),
        (r"# FIXME", "FIXME comment found", IssueSeverity.MEDIUM),
        (r"# HACK", "HACK comment found", IssueSeverity.MEDIUM),
        (r"except:\s*$", "Bare except clause is too broad", IssueSeverity.MEDIUM),
        (r"except Exception:", "Catching Exception is too broad", IssueSeverity.LOW),
        (r"from .* import \*", "Wildcard import is discouraged", IssueSeverity.LOW),
        (r"\.{100,}", "Line too long (100+ chars)", IssueSeverity.INFO),
    ]

    # Performance patterns to detect
    PERFORMANCE_PATTERNS: ClassVar[list[tuple[str, str, IssueSeverity]]] = [
        (r"for.*in.*range.*len", "Use enumerate instead of range(len())", IssueSeverity.LOW),
        (r"\+\s*=.*\+\s*str", "String concatenation in loop is slow", IssueSeverity.MEDIUM),
        (r"time\.sleep\s*\(\s*\d{2,}", "Long sleep detected", IssueSeverity.MEDIUM),
        (r"while\s+True:", "Infinite loop detected", IssueSeverity.INFO),
        (r"\.read\(\).*\.read\(\)", "Multiple file reads", IssueSeverity.LOW),
        (r"SELECT \*", "SELECT * can be slow", IssueSeverity.LOW),
    ]

    def __init__(self) -> None:
        self.settings = get_settings()

    def analyze_file(self, state: CodeReviewState) -> dict[str, Any]:
        """Analyze the file and gather metadata."""
        with tracer.start_as_current_span("code_review.analyze_file"):
            code = state.code
            lines = code.split("\n")

            # Count added/removed lines (simplified - for diffs)
            lines_added = sum(1 for line in lines if line.startswith("+"))
            lines_removed = sum(1 for line in lines if line.startswith("-"))

            # If not a diff, count all non-empty lines as added
            if lines_added == 0:
                lines_added = sum(1 for line in lines if line.strip())

            analysis = FileAnalysis(
                path=state.file_path,
                language=state.language,
                lines_added=lines_added,
                lines_removed=lines_removed,
            )

            logger.info(
                "file_analyzed",
                path=state.file_path,
                language=state.language,
                lines_added=lines_added,
                lines_removed=lines_removed,
            )

            return {"file_analysis": analysis.to_dict()}

    def check_security(self, state: CodeReviewState) -> dict[str, Any]:
        """Check for security vulnerabilities."""
        with tracer.start_as_current_span("code_review.check_security"):
            if not state.check_security:
                return {}

            issues = []
            lines = state.code.split("\n")

            for pattern, message, severity in self.SECURITY_PATTERNS:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append(
                            CodeIssue(
                                category=IssueCategory.SECURITY,
                                severity=severity,
                                message=message,
                                file_path=state.file_path,
                                line_start=line_num,
                                suggestion="Review and fix this security concern",
                                rule_id=f"SEC-{len(issues) + 1:03d}",
                            ).to_dict()
                        )

            logger.info(
                "security_check_complete",
                issue_count=len(issues),
            )

            return {"issues": [*state.issues, *issues]}

    def check_style(self, state: CodeReviewState) -> dict[str, Any]:
        """Check for code style issues."""
        with tracer.start_as_current_span("code_review.check_style"):
            if not state.check_style:
                return {}

            issues = []
            lines = state.code.split("\n")

            for pattern, message, severity in self.STYLE_PATTERNS:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        issues.append(
                            CodeIssue(
                                category=IssueCategory.STYLE,
                                severity=severity,
                                message=message,
                                file_path=state.file_path,
                                line_start=line_num,
                                rule_id=f"STY-{len(issues) + 1:03d}",
                            ).to_dict()
                        )

            # Check line length
            for line_num, line in enumerate(lines, 1):
                if len(line) > 120:
                    issues.append(
                        CodeIssue(
                            category=IssueCategory.STYLE,
                            severity=IssueSeverity.LOW,
                            message=f"Line too long ({len(line)} characters)",
                            file_path=state.file_path,
                            line_start=line_num,
                            suggestion="Consider breaking this line",
                            rule_id="STY-LINE-LENGTH",
                        ).to_dict()
                    )

            logger.info(
                "style_check_complete",
                issue_count=len(issues),
            )

            return {"issues": [*state.issues, *issues]}

    def check_performance(self, state: CodeReviewState) -> dict[str, Any]:
        """Check for performance issues."""
        with tracer.start_as_current_span("code_review.check_performance"):
            if not state.check_performance:
                return {}

            issues = []
            lines = state.code.split("\n")

            for pattern, message, severity in self.PERFORMANCE_PATTERNS:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append(
                            CodeIssue(
                                category=IssueCategory.PERFORMANCE,
                                severity=severity,
                                message=message,
                                file_path=state.file_path,
                                line_start=line_num,
                                rule_id=f"PERF-{len(issues) + 1:03d}",
                            ).to_dict()
                        )

            logger.info(
                "performance_check_complete",
                issue_count=len(issues),
            )

            return {"issues": [*state.issues, *issues]}

    def check_testing(self, state: CodeReviewState) -> dict[str, Any]:
        """Check for testing patterns and concerns."""
        with tracer.start_as_current_span("code_review.check_testing"):
            if not state.check_tests:
                return {}

            issues = []
            code = state.code

            # Check for test file without assertions
            is_test_file = "test" in state.file_path.lower()
            has_no_assertions = "assert" not in code and "expect" not in code
            if is_test_file and has_no_assertions:
                issues.append(
                    CodeIssue(
                        category=IssueCategory.TEST,
                        severity=IssueSeverity.MEDIUM,
                        message="Test file appears to have no assertions",
                        file_path=state.file_path,
                        suggestion="Add assertions to verify behavior",
                        rule_id="TEST-NO-ASSERT",
                    ).to_dict()
                )

            # Check for hardcoded test values that might be sensitive
            if re.search(r"password\s*=|api_key\s*=|secret\s*=", code, re.IGNORECASE):
                issues.append(
                    CodeIssue(
                        category=IssueCategory.TEST,
                        severity=IssueSeverity.MEDIUM,
                        message="Possible sensitive data in test code",
                        file_path=state.file_path,
                        suggestion="Use fixtures or environment variables for sensitive test data",
                        rule_id="TEST-SENSITIVE-DATA",
                    ).to_dict()
                )

            logger.info(
                "testing_check_complete",
                issue_count=len(issues),
            )

            return {"issues": [*state.issues, *issues]}

    def calculate_score(self, state: CodeReviewState) -> dict[str, Any]:
        """Calculate quality score based on issues."""
        with tracer.start_as_current_span("code_review.calculate_score"):
            # Start with perfect score
            score = 100.0

            # Deduct points based on issue severity
            severity_deductions = {
                "critical": 25,
                "high": 15,
                "medium": 5,
                "low": 2,
                "info": 0,
            }

            for issue in state.issues:
                severity = issue.get("severity", "info")
                score -= severity_deductions.get(severity, 0)

            # Don't go below 0
            score = max(0.0, score)

            logger.info(
                "score_calculated",
                score=round(score, 1),
                issue_count=len(state.issues),
            )

            return {"quality_score": round(score, 1)}

    def make_decision(self, state: CodeReviewState) -> dict[str, Any]:
        """Make review decision based on issues found."""
        with tracer.start_as_current_span("code_review.make_decision"):
            # Count issues by severity
            severity_counts: dict[str, int] = {}
            for issue in state.issues:
                severity = issue.get("severity", "info")
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

            critical_count = severity_counts.get("critical", 0)
            high_count = severity_counts.get("high", 0)

            # Make decision based on severity
            requires_changes = critical_count > 0 or high_count >= 3 or state.quality_score < 50
            if requires_changes:
                decision = ReviewDecision.REQUEST_CHANGES
            elif state.quality_score < 80:
                decision = ReviewDecision.COMMENT
            else:
                decision = ReviewDecision.APPROVE

            logger.info(
                "decision_made",
                decision=decision.value,
                critical=critical_count,
                high=high_count,
                score=state.quality_score,
            )

            return {"decision": decision}

    def generate_summary(self, state: CodeReviewState) -> dict[str, Any]:
        """Generate review summary and suggestions."""
        with tracer.start_as_current_span("code_review.generate_summary"):
            issues = state.issues
            decision = state.decision

            # Count by category
            category_counts: dict[str, int] = {}
            for issue in issues:
                category = issue.get("category", "unknown")
                category_counts[category] = category_counts.get(category, 0) + 1

            # Build summary
            if not issues:
                summary = "No issues found. Code looks good!"
            else:
                summary_parts = [f"Found {len(issues)} issue(s) in the review."]
                for category, count in category_counts.items():
                    summary_parts.append(f"- {category.title()}: {count}")

                if decision == ReviewDecision.APPROVE:
                    summary_parts.append("Overall the code is acceptable.")
                elif decision == ReviewDecision.COMMENT:
                    summary_parts.append("Please address the comments before merging.")
                else:
                    summary_parts.append("Please fix the critical issues before merging.")

                summary = "\n".join(summary_parts)

            # Generate suggestions
            suggestions = []
            if category_counts.get("security", 0) > 0:
                suggestions.append("Review and fix security vulnerabilities")
            if category_counts.get("performance", 0) > 0:
                suggestions.append("Consider optimizing performance hotspots")
            if category_counts.get("style", 0) > 0:
                suggestions.append("Run a linter to fix style issues")
            if category_counts.get("test", 0) > 0:
                suggestions.append("Improve test coverage and assertions")

            return {
                "summary": summary,
                "suggestions": suggestions,
            }

    def finalize(self, state: CodeReviewState) -> dict[str, Any]:
        """Finalize the review."""
        with tracer.start_as_current_span("code_review.finalize"):
            logger.info(
                "code_review_complete",
                file_path=state.file_path,
                decision=state.decision.value if state.decision else None,
                issue_count=len(state.issues),
                quality_score=state.quality_score,
            )

            return {}
