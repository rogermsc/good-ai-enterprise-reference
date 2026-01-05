"""Tests for prompt versioning and A/B testing system."""

import pytest

from src.core.prompt_management import (
    Experiment,
    ExperimentManager,
    ExperimentMetrics,
    ExperimentStatus,
    ExperimentVariant,
    PromptManager,
    PromptRegistry,
    PromptStatus,
    PromptVersion,
    get_prompt_manager,
)


class TestPromptVersion:
    """Tests for prompt version."""

    def test_create_prompt(self) -> None:
        prompt = PromptVersion(
            id="test-v1",
            name="test-prompt",
            version="1.0.0",
            template="Hello, {{name}}!",
        )
        assert prompt.id == "test-v1"
        assert prompt.status == PromptStatus.DRAFT
        assert prompt.temperature == 0.7

    def test_render_template(self) -> None:
        prompt = PromptVersion(
            id="test-v1",
            name="test",
            version="1.0.0",
            template="Hello, {{name}}! You have {{count}} messages.",
        )
        result = prompt.render({"name": "Alice", "count": "5"})
        assert result == "Hello, Alice! You have 5 messages."

    def test_render_no_variables(self) -> None:
        prompt = PromptVersion(
            id="test-v1",
            name="test",
            version="1.0.0",
            template="Static prompt with no variables.",
        )
        result = prompt.render()
        assert result == "Static prompt with no variables."

    def test_serialization(self) -> None:
        prompt = PromptVersion(
            id="test-v1",
            name="test",
            version="1.0.0",
            template="Hello",
            status=PromptStatus.ACTIVE,
            tags=["production", "v1"],
        )
        data = prompt.to_dict()
        assert data["id"] == "test-v1"
        assert data["status"] == "active"
        assert "production" in data["tags"]


class TestExperimentVariant:
    """Tests for experiment variant."""

    def test_create_variant(self) -> None:
        variant = ExperimentVariant(
            name="control",
            prompt_version_id="prompt-v1",
            weight=0.5,
        )
        assert variant.name == "control"
        assert variant.weight == 0.5

    def test_serialization(self) -> None:
        variant = ExperimentVariant(
            name="treatment",
            prompt_version_id="prompt-v2",
            weight=0.3,
            metrics={"conversion": 0.15},
        )
        data = variant.to_dict()
        assert data["name"] == "treatment"
        assert data["metrics"]["conversion"] == 0.15


class TestExperimentMetrics:
    """Tests for experiment metrics."""

    def test_initial_metrics(self) -> None:
        metrics = ExperimentMetrics()
        assert metrics.impressions == 0
        assert metrics.success_rate == 0.0

    def test_success_rate(self) -> None:
        metrics = ExperimentMetrics(impressions=100, successes=80, failures=20)
        assert metrics.success_rate == 80.0

    def test_average_latency(self) -> None:
        metrics = ExperimentMetrics(impressions=10, total_latency_ms=500.0)
        assert metrics.avg_latency_ms == 50.0

    def test_average_rating(self) -> None:
        metrics = ExperimentMetrics(user_ratings=[4.0, 5.0, 3.0, 4.0])
        assert metrics.avg_rating == 4.0

    def test_serialization(self) -> None:
        metrics = ExperimentMetrics(
            impressions=100,
            successes=90,
            failures=10,
            total_tokens=50000,
        )
        data = metrics.to_dict()
        assert data["impressions"] == 100
        assert data["success_rate"] == 90.0


class TestExperiment:
    """Tests for experiment."""

    def test_create_experiment(self) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test Experiment",
            prompt_name="test-prompt",
            variants=[
                ExperimentVariant("control", "v1", 0.5),
                ExperimentVariant("treatment", "v2", 0.5),
            ],
        )
        assert experiment.id == "exp-001"
        assert experiment.status == ExperimentStatus.DRAFT
        assert len(experiment.variants) == 2

    def test_invalid_weights(self) -> None:
        with pytest.raises(ValueError, match=r"must sum to 1\.0"):
            Experiment(
                id="exp-001",
                name="Test",
                prompt_name="test",
                variants=[
                    ExperimentVariant("a", "v1", 0.3),
                    ExperimentVariant("b", "v2", 0.3),
                ],
            )

    def test_select_variant_consistent(self) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test",
            variants=[
                ExperimentVariant("control", "v1", 0.5),
                ExperimentVariant("treatment", "v2", 0.5),
            ],
        )

        # Same user should get same variant
        variant1 = experiment.select_variant("user-123")
        variant2 = experiment.select_variant("user-123")
        assert variant1.name == variant2.name

    def test_select_variant_distribution(self) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test",
            variants=[
                ExperimentVariant("control", "v1", 0.5),
                ExperimentVariant("treatment", "v2", 0.5),
            ],
        )

        # Test distribution across many users
        counts = {"control": 0, "treatment": 0}
        for i in range(1000):
            variant = experiment.select_variant(f"user-{i}")
            counts[variant.name] += 1

        # Should be roughly 50/50 with some tolerance
        assert 400 < counts["control"] < 600
        assert 400 < counts["treatment"] < 600


class TestPromptRegistry:
    """Tests for prompt registry."""

    @pytest.fixture
    def registry(self) -> PromptRegistry:
        return PromptRegistry()

    def test_register_and_get(self, registry: PromptRegistry) -> None:
        prompt = PromptVersion(
            id="test-v1",
            name="test",
            version="1.0.0",
            template="Hello",
        )
        registry.register(prompt)

        retrieved = registry.get("test-v1")
        assert retrieved is not None
        assert retrieved.template == "Hello"

    def test_get_active(self, registry: PromptRegistry) -> None:
        registry.register(
            PromptVersion(
                id="test-v1",
                name="test",
                version="1.0.0",
                template="V1",
                status=PromptStatus.DEPRECATED,
            )
        )
        registry.register(
            PromptVersion(
                id="test-v2",
                name="test",
                version="2.0.0",
                template="V2",
                status=PromptStatus.ACTIVE,
            )
        )

        active = registry.get_active("test")
        assert active is not None
        assert active.id == "test-v2"

    def test_set_active(self, registry: PromptRegistry) -> None:
        registry.register(
            PromptVersion(
                id="test-v1",
                name="test",
                version="1.0.0",
                template="V1",
                status=PromptStatus.ACTIVE,
            )
        )
        registry.register(
            PromptVersion(
                id="test-v2",
                name="test",
                version="2.0.0",
                template="V2",
                status=PromptStatus.DRAFT,
            )
        )

        registry.set_active("test-v2")

        # V2 should now be active
        assert registry.get("test-v2").status == PromptStatus.ACTIVE
        # V1 should be deprecated
        assert registry.get("test-v1").status == PromptStatus.DEPRECATED

    def test_get_versions(self, registry: PromptRegistry) -> None:
        registry.register(PromptVersion(id="test-v1", name="test", version="1.0", template="V1"))
        registry.register(PromptVersion(id="test-v2", name="test", version="2.0", template="V2"))
        registry.register(PromptVersion(id="other-v1", name="other", version="1.0", template="O"))

        versions = registry.get_versions("test")
        assert len(versions) == 2

    def test_delete(self, registry: PromptRegistry) -> None:
        registry.register(PromptVersion(id="test-v1", name="test", version="1.0", template="V1"))

        assert registry.delete("test-v1") is True
        assert registry.get("test-v1") is None
        assert registry.delete("nonexistent") is False

    def test_list_prompts(self, registry: PromptRegistry) -> None:
        registry.register(PromptVersion(id="a-v1", name="prompt-a", version="1.0", template="A"))
        registry.register(PromptVersion(id="b-v1", name="prompt-b", version="1.0", template="B"))

        names = registry.list_prompts()
        assert "prompt-a" in names
        assert "prompt-b" in names


class TestExperimentManager:
    """Tests for experiment manager."""

    @pytest.fixture
    def manager(self) -> ExperimentManager:
        registry = PromptRegistry()
        registry.register(
            PromptVersion(
                id="prompt-v1",
                name="test-prompt",
                version="1.0",
                template="Control template",
                status=PromptStatus.ACTIVE,
            )
        )
        registry.register(
            PromptVersion(
                id="prompt-v2",
                name="test-prompt",
                version="2.0",
                template="Treatment template",
            )
        )
        return ExperimentManager(registry)

    def test_register_experiment(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[
                ExperimentVariant("control", "prompt-v1", 0.5),
                ExperimentVariant("treatment", "prompt-v2", 0.5),
            ],
        )
        manager.register(experiment)

        retrieved = manager.get("exp-001")
        assert retrieved is not None
        assert retrieved.name == "Test"

    def test_start_experiment(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[
                ExperimentVariant("control", "prompt-v1", 0.5),
                ExperimentVariant("treatment", "prompt-v2", 0.5),
            ],
        )
        manager.register(experiment)

        assert manager.start("exp-001") is True
        assert manager.get("exp-001").status == ExperimentStatus.RUNNING
        assert manager.get("exp-001").start_date is not None

        # Can't start twice
        assert manager.start("exp-001") is False

    def test_pause_and_resume(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[ExperimentVariant("a", "prompt-v1", 1.0)],
        )
        manager.register(experiment)
        manager.start("exp-001")

        assert manager.pause("exp-001") is True
        assert manager.get("exp-001").status == ExperimentStatus.PAUSED

        assert manager.resume("exp-001") is True
        assert manager.get("exp-001").status == ExperimentStatus.RUNNING

    def test_complete_experiment(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[ExperimentVariant("a", "prompt-v1", 1.0)],
        )
        manager.register(experiment)
        manager.start("exp-001")

        assert manager.complete("exp-001", winner="a") is True
        assert manager.get("exp-001").status == ExperimentStatus.COMPLETED
        assert manager.get("exp-001").winner == "a"

    def test_get_variant_running_only(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[ExperimentVariant("a", "prompt-v1", 1.0)],
        )
        manager.register(experiment)

        # Not running yet
        assert manager.get_variant("exp-001", "user-1") is None

        manager.start("exp-001")
        assert manager.get_variant("exp-001", "user-1") is not None

    def test_get_prompt_for_variant(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[
                ExperimentVariant("control", "prompt-v1", 0.5),
                ExperimentVariant("treatment", "prompt-v2", 0.5),
            ],
        )
        manager.register(experiment)

        prompt = manager.get_prompt_for_variant("exp-001", "control")
        assert prompt is not None
        assert prompt.template == "Control template"

        prompt = manager.get_prompt_for_variant("exp-001", "treatment")
        assert prompt.template == "Treatment template"

    def test_record_impression(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[ExperimentVariant("a", "prompt-v1", 1.0)],
        )
        manager.register(experiment)
        manager.start("exp-001")

        manager.record_impression(
            "exp-001",
            "a",
            success=True,
            latency_ms=100.0,
            tokens=500,
            cost=0.01,
        )
        manager.record_impression(
            "exp-001",
            "a",
            success=False,
            latency_ms=50.0,
        )

        metrics = manager.get_metrics("exp-001")
        assert metrics["a"].impressions == 2
        assert metrics["a"].successes == 1
        assert metrics["a"].failures == 1
        assert metrics["a"].success_rate == 50.0

    def test_get_results(self, manager: ExperimentManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="test-prompt",
            variants=[
                ExperimentVariant("a", "prompt-v1", 0.5),
                ExperimentVariant("b", "prompt-v2", 0.5),
            ],
        )
        manager.register(experiment)
        manager.start("exp-001")

        # Record some impressions
        for _ in range(20):
            manager.record_impression("exp-001", "a", success=True)
        for _ in range(15):
            manager.record_impression("exp-001", "b", success=True)
        for _ in range(5):
            manager.record_impression("exp-001", "b", success=False)

        results = manager.get_results("exp-001")
        assert results is not None
        assert results["metrics"]["a"]["success_rate"] == 100.0
        assert results["metrics"]["b"]["success_rate"] == 75.0
        assert results["recommendation"]["winner"] == "a"

    def test_list_experiments(self, manager: ExperimentManager) -> None:
        for i in range(3):
            exp = Experiment(
                id=f"exp-{i}",
                name=f"Test {i}",
                prompt_name="test-prompt",
                variants=[ExperimentVariant("a", "prompt-v1", 1.0)],
            )
            manager.register(exp)

        manager.start("exp-0")
        manager.start("exp-1")

        all_exps = manager.list_experiments()
        assert len(all_exps) == 3

        running = manager.list_experiments(ExperimentStatus.RUNNING)
        assert len(running) == 2


class TestPromptManager:
    """Tests for high-level prompt manager."""

    @pytest.fixture
    def manager(self) -> PromptManager:
        pm = PromptManager()

        # Register prompts
        pm.prompts.register(
            PromptVersion(
                id="ticket-v1",
                name="ticket-triage",
                version="1.0",
                template="Classify: {{text}}",
                status=PromptStatus.ACTIVE,
            )
        )
        pm.prompts.register(
            PromptVersion(
                id="ticket-v2",
                name="ticket-triage",
                version="2.0",
                template="Please classify: {{text}}",
            )
        )
        return pm

    def test_get_prompt_no_experiment(self, manager: PromptManager) -> None:
        prompt = manager.get_prompt("ticket-triage")
        assert prompt is not None
        assert prompt.id == "ticket-v1"

    def test_get_prompt_with_experiment(self, manager: PromptManager) -> None:
        # Create and start experiment
        experiment = Experiment(
            id="exp-001",
            name="Ticket Test",
            prompt_name="ticket-triage",
            variants=[
                ExperimentVariant("control", "ticket-v1", 0.5),
                ExperimentVariant("treatment", "ticket-v2", 0.5),
            ],
        )
        manager.experiments.register(experiment)
        manager.experiments.start("exp-001")

        # Should get a variant from the experiment
        prompt = manager.get_prompt("ticket-triage", user_id="test-user")
        assert prompt is not None
        assert prompt.id in ["ticket-v1", "ticket-v2"]

    def test_get_prompt_specific_experiment(self, manager: PromptManager) -> None:
        experiment = Experiment(
            id="exp-001",
            name="Test",
            prompt_name="ticket-triage",
            variants=[ExperimentVariant("treatment", "ticket-v2", 1.0)],
        )
        manager.experiments.register(experiment)
        manager.experiments.start("exp-001")

        prompt = manager.get_prompt(
            "ticket-triage",
            user_id="test-user",
            experiment_id="exp-001",
        )
        assert prompt.id == "ticket-v2"

    def test_get_prompt_nonexistent(self, manager: PromptManager) -> None:
        prompt = manager.get_prompt("nonexistent-prompt")
        assert prompt is None


class TestGlobalPromptManager:
    """Tests for global prompt manager."""

    def test_singleton(self) -> None:
        pm1 = get_prompt_manager()
        pm2 = get_prompt_manager()
        assert pm1 is pm2
