"""
Prompt Versioning and A/B Testing System.

Provides:
- Versioned prompt templates with metadata
- A/B testing with configurable traffic splits
- Performance metrics per variant
- Rollout controls and feature flags
- Audit logging for all prompt changes

This enables safe experimentation with prompts in production
while tracking which variants perform best.
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()


class PromptStatus(str, Enum):
    """Status of a prompt version."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class ExperimentStatus(str, Enum):
    """Status of an A/B experiment."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class PromptVersion:
    """A versioned prompt template."""

    id: str
    name: str
    template: str
    version: str
    status: PromptStatus = PromptStatus.DRAFT
    description: str = ""
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def render(self, variables: dict[str, Any] | None = None) -> str:
        """Render the template with variables."""
        if not variables:
            return self.template

        result = self.template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "template": self.template,
            "version": self.version,
            "status": self.status.value,
            "description": self.description,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class ExperimentVariant:
    """A variant in an A/B experiment."""

    name: str
    prompt_version_id: str
    weight: float = 0.5  # Traffic allocation (0.0 to 1.0)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "prompt_version_id": self.prompt_version_id,
            "weight": self.weight,
            "metrics": self.metrics,
        }


@dataclass
class ExperimentMetrics:
    """Aggregated metrics for an experiment variant."""

    impressions: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    user_ratings: list[float] = field(default_factory=list)
    custom_metrics: dict[str, float] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.successes + self.failures
        return (self.successes / total * 100) if total > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency."""
        return self.total_latency_ms / self.impressions if self.impressions > 0 else 0.0

    @property
    def avg_rating(self) -> float:
        """Calculate average user rating."""
        return sum(self.user_ratings) / len(self.user_ratings) if self.user_ratings else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "impressions": self.impressions,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 4),
            "avg_rating": round(self.avg_rating, 2),
            "custom_metrics": self.custom_metrics,
        }


@dataclass
class Experiment:
    """An A/B testing experiment."""

    id: str
    name: str
    prompt_name: str  # Base prompt being tested
    variants: list[ExperimentVariant]
    status: ExperimentStatus = ExperimentStatus.DRAFT
    description: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    winner: str | None = None
    target_impressions: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate experiment configuration."""
        if self.variants:
            total_weight = sum(v.weight for v in self.variants)
            if abs(total_weight - 1.0) > 0.01:
                raise ValueError(f"Variant weights must sum to 1.0, got {total_weight}")

    def select_variant(self, user_id: str | None = None) -> ExperimentVariant:
        """Select a variant based on weights (consistent for same user)."""
        if not self.variants:
            raise ValueError("Experiment has no variants")

        # Use user_id for consistent bucketing
        if user_id:
            hash_input = f"{self.id}:{user_id}"
            bucket = int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % 100 / 100
        else:
            bucket = random.random()

        cumulative = 0.0
        for variant in self.variants:
            cumulative += variant.weight
            if bucket < cumulative:
                return variant

        return self.variants[-1]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "prompt_name": self.prompt_name,
            "status": self.status.value,
            "description": self.description,
            "variants": [v.to_dict() for v in self.variants],
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "winner": self.winner,
            "target_impressions": self.target_impressions,
        }


class PromptRegistry:
    """
    Registry for managing prompt versions.

    Example:
        registry = PromptRegistry()

        # Register a prompt
        prompt = PromptVersion(
            id="ticket-triage-v1",
            name="ticket-triage",
            version="1.0.0",
            template="Classify this ticket: {{ticket_text}}",
            status=PromptStatus.ACTIVE,
        )
        registry.register(prompt)

        # Get active version
        active = registry.get_active("ticket-triage")
        rendered = active.render({"ticket_text": "My app crashes"})
    """

    def __init__(self) -> None:
        self._prompts: dict[str, PromptVersion] = {}
        self._by_name: dict[str, list[str]] = {}  # name -> [version_ids]

    def register(self, prompt: PromptVersion) -> None:
        """Register a prompt version."""
        self._prompts[prompt.id] = prompt

        if prompt.name not in self._by_name:
            self._by_name[prompt.name] = []
        if prompt.id not in self._by_name[prompt.name]:
            self._by_name[prompt.name].append(prompt.id)

        logger.info(
            "prompt_registered",
            id=prompt.id,
            name=prompt.name,
            version=prompt.version,
            status=prompt.status.value,
        )

    def get(self, prompt_id: str) -> PromptVersion | None:
        """Get a prompt by ID."""
        return self._prompts.get(prompt_id)

    def get_active(self, name: str) -> PromptVersion | None:
        """Get the active version of a prompt by name."""
        version_ids = self._by_name.get(name, [])
        for vid in version_ids:
            prompt = self._prompts.get(vid)
            if prompt and prompt.status == PromptStatus.ACTIVE:
                return prompt
        return None

    def get_versions(self, name: str) -> list[PromptVersion]:
        """Get all versions of a prompt."""
        version_ids = self._by_name.get(name, [])
        return [self._prompts[vid] for vid in version_ids if vid in self._prompts]

    def set_active(self, prompt_id: str) -> bool:
        """Set a prompt as the active version (deprecates others)."""
        prompt = self._prompts.get(prompt_id)
        if not prompt:
            return False

        # Deprecate other active versions of the same prompt
        for vid in self._by_name.get(prompt.name, []):
            other = self._prompts.get(vid)
            if other and other.id != prompt_id and other.status == PromptStatus.ACTIVE:
                other.status = PromptStatus.DEPRECATED
                other.updated_at = datetime.now(UTC)

        prompt.status = PromptStatus.ACTIVE
        prompt.updated_at = datetime.now(UTC)

        logger.info(
            "prompt_activated",
            id=prompt.id,
            name=prompt.name,
            version=prompt.version,
        )
        return True

    def list_prompts(self) -> list[str]:
        """List all prompt names."""
        return list(self._by_name.keys())

    def delete(self, prompt_id: str) -> bool:
        """Delete a prompt version."""
        prompt = self._prompts.get(prompt_id)
        if not prompt:
            return False

        del self._prompts[prompt_id]
        if prompt.name in self._by_name:
            self._by_name[prompt.name] = [
                vid for vid in self._by_name[prompt.name] if vid != prompt_id
            ]
        return True


class ExperimentManager:
    """
    Manages A/B testing experiments.

    Example:
        manager = ExperimentManager(prompt_registry)

        # Create experiment
        experiment = Experiment(
            id="exp-001",
            name="Ticket Triage Prompt Test",
            prompt_name="ticket-triage",
            variants=[
                ExperimentVariant("control", "ticket-triage-v1", 0.5),
                ExperimentVariant("treatment", "ticket-triage-v2", 0.5),
            ],
        )
        manager.register(experiment)
        manager.start("exp-001")

        # Get variant for user
        variant = manager.get_variant("exp-001", user_id="user-123")
        prompt = manager.get_prompt_for_variant("exp-001", variant.name)
    """

    def __init__(self, prompt_registry: PromptRegistry | None = None) -> None:
        self.prompt_registry = prompt_registry or PromptRegistry()
        self._experiments: dict[str, Experiment] = {}
        self._metrics: dict[
            str, dict[str, ExperimentMetrics]
        ] = {}  # exp_id -> {variant -> metrics}

    def register(self, experiment: Experiment) -> None:
        """Register an experiment."""
        self._experiments[experiment.id] = experiment
        self._metrics[experiment.id] = {v.name: ExperimentMetrics() for v in experiment.variants}

        logger.info(
            "experiment_registered",
            id=experiment.id,
            name=experiment.name,
            variants=[v.name for v in experiment.variants],
        )

    def get(self, experiment_id: str) -> Experiment | None:
        """Get an experiment by ID."""
        return self._experiments.get(experiment_id)

    def start(self, experiment_id: str) -> bool:
        """Start an experiment."""
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return False

        if experiment.status != ExperimentStatus.DRAFT:
            return False

        experiment.status = ExperimentStatus.RUNNING
        experiment.start_date = datetime.now(UTC)

        logger.info(
            "experiment_started",
            id=experiment_id,
            name=experiment.name,
        )
        return True

    def pause(self, experiment_id: str) -> bool:
        """Pause a running experiment."""
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return False

        experiment.status = ExperimentStatus.PAUSED
        logger.info("experiment_paused", id=experiment_id)
        return True

    def resume(self, experiment_id: str) -> bool:
        """Resume a paused experiment."""
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.PAUSED:
            return False

        experiment.status = ExperimentStatus.RUNNING
        logger.info("experiment_resumed", id=experiment_id)
        return True

    def complete(self, experiment_id: str, winner: str | None = None) -> bool:
        """Complete an experiment and optionally declare a winner."""
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return False

        experiment.status = ExperimentStatus.COMPLETED
        experiment.end_date = datetime.now(UTC)
        experiment.winner = winner

        logger.info(
            "experiment_completed",
            id=experiment_id,
            winner=winner,
        )
        return True

    def get_variant(
        self,
        experiment_id: str,
        user_id: str | None = None,
    ) -> ExperimentVariant | None:
        """Get the variant for a user in an experiment."""
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return None

        return experiment.select_variant(user_id)

    def get_prompt_for_variant(
        self,
        experiment_id: str,
        variant_name: str,
    ) -> PromptVersion | None:
        """Get the prompt for a variant."""
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return None

        for variant in experiment.variants:
            if variant.name == variant_name:
                return self.prompt_registry.get(variant.prompt_version_id)

        return None

    def record_impression(
        self,
        experiment_id: str,
        variant_name: str,
        success: bool = True,
        latency_ms: float = 0.0,
        tokens: int = 0,
        cost: float = 0.0,
        rating: float | None = None,
        custom_metrics: dict[str, float] | None = None,
    ) -> None:
        """Record an impression for a variant."""
        if experiment_id not in self._metrics:
            return

        metrics = self._metrics[experiment_id].get(variant_name)
        if not metrics:
            return

        metrics.impressions += 1
        if success:
            metrics.successes += 1
        else:
            metrics.failures += 1

        metrics.total_latency_ms += latency_ms
        metrics.total_tokens += tokens
        metrics.total_cost += cost

        if rating is not None:
            metrics.user_ratings.append(rating)

        if custom_metrics:
            for key, value in custom_metrics.items():
                current = metrics.custom_metrics.get(key, 0.0)
                metrics.custom_metrics[key] = current + value

        logger.debug(
            "experiment_impression",
            experiment_id=experiment_id,
            variant=variant_name,
            success=success,
        )

    def get_metrics(self, experiment_id: str) -> dict[str, ExperimentMetrics] | None:
        """Get metrics for all variants in an experiment."""
        return self._metrics.get(experiment_id)

    def get_results(self, experiment_id: str) -> dict[str, Any] | None:
        """Get experiment results with analysis."""
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return None

        metrics = self._metrics.get(experiment_id, {})

        return {
            "experiment": experiment.to_dict(),
            "metrics": {name: m.to_dict() for name, m in metrics.items()},
            "recommendation": self._get_recommendation(metrics),
        }

    def _get_recommendation(
        self,
        metrics: dict[str, ExperimentMetrics],
    ) -> dict[str, Any]:
        """Generate a recommendation based on metrics."""
        if not metrics:
            return {"winner": None, "confidence": 0, "reason": "No data"}

        # Find best performer by success rate
        best_variant = None
        best_rate = -1.0

        for name, m in metrics.items():
            if m.impressions >= 10 and m.success_rate > best_rate:
                best_rate = m.success_rate
                best_variant = name

        if not best_variant:
            return {"winner": None, "confidence": 0, "reason": "Insufficient data"}

        # Simple confidence based on sample size
        total_impressions = sum(m.impressions for m in metrics.values())
        confidence = min(100, total_impressions // 10)

        return {
            "winner": best_variant,
            "confidence": confidence,
            "reason": f"Highest success rate ({best_rate:.1f}%)",
        }

    def list_experiments(
        self,
        status: ExperimentStatus | None = None,
    ) -> list[Experiment]:
        """List experiments, optionally filtered by status."""
        experiments = list(self._experiments.values())
        if status:
            experiments = [e for e in experiments if e.status == status]
        return experiments


class PromptManager:
    """
    High-level manager for prompts and experiments.

    Combines prompt registry and experiment manager for easy usage.

    Example:
        manager = PromptManager()

        # Get prompt (checks experiments first)
        prompt = manager.get_prompt(
            name="ticket-triage",
            user_id="user-123",
        )

        # Render with variables
        text = prompt.render({"ticket": "My app crashes"})
    """

    def __init__(self) -> None:
        self.prompts = PromptRegistry()
        self.experiments = ExperimentManager(self.prompts)

    def get_prompt(
        self,
        name: str,
        user_id: str | None = None,
        experiment_id: str | None = None,
    ) -> PromptVersion | None:
        """
        Get a prompt, considering any active experiments.

        If an experiment is running for this prompt, returns the
        appropriate variant based on user bucketing.
        """
        with tracer.start_as_current_span("prompt_manager.get_prompt") as span:
            span.set_attribute("prompt_name", name)

            # Check for specific experiment
            if experiment_id:
                variant = self.experiments.get_variant(experiment_id, user_id)
                if variant:
                    prompt = self.experiments.get_prompt_for_variant(experiment_id, variant.name)
                    if prompt:
                        span.set_attribute("source", "experiment")
                        span.set_attribute("experiment_id", experiment_id)
                        span.set_attribute("variant", variant.name)
                        return prompt

            # Check for any running experiment on this prompt
            for exp in self.experiments.list_experiments(ExperimentStatus.RUNNING):
                if exp.prompt_name == name:
                    variant = exp.select_variant(user_id)
                    prompt = self.experiments.get_prompt_for_variant(exp.id, variant.name)
                    if prompt:
                        span.set_attribute("source", "experiment")
                        span.set_attribute("experiment_id", exp.id)
                        span.set_attribute("variant", variant.name)
                        return prompt

            # Return active version
            prompt = self.prompts.get_active(name)
            if prompt:
                span.set_attribute("source", "registry")
            return prompt


# Global prompt manager instance
_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """Get the global prompt manager instance."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
