"""
Configuration Loader for Policy and PII Pattern Configs.

Loads YAML configuration files for:
- Policy configurations (RBAC, severity rules, approval actions)
- PII pattern configurations (regional pattern sets)

Supports inheritance via 'extends' field for regulation-specific overrides.
"""

import re
from pathlib import Path
from typing import Any

import yaml

from src.core.observability import get_logger

logger = get_logger()

# Default config directory
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
POLICIES_DIR = CONFIG_DIR / "policies"
PII_PATTERNS_DIR = CONFIG_DIR / "pii-patterns"


class ConfigLoadError(Exception):
    """Raised when configuration loading fails."""

    pass


def load_yaml_file(file_path: Path) -> dict[str, Any]:
    """
    Load a YAML file and return its contents.

    Args:
        file_path: Path to the YAML file

    Returns:
        Dictionary containing the YAML contents

    Raises:
        ConfigLoadError: If the file cannot be loaded or parsed
    """
    try:
        with file_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigLoadError(f"Configuration file not found: {file_path}")
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"Invalid YAML in {file_path}: {e}")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Deep merge two dictionaries, with override taking precedence.

    Args:
        base: Base dictionary
        override: Dictionary with values to override

    Returns:
        Merged dictionary
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # For lists, extend rather than replace (allows adding patterns)
            result[key] = result[key] + value
        else:
            result[key] = value

    return result


class PolicyConfigLoader:
    """
    Loads and manages policy configurations.

    Supports:
    - Loading from YAML files
    - Inheritance via 'extends' field
    - Runtime policy switching per tenant

    Example:
        loader = PolicyConfigLoader()
        config = loader.load("lgpd-br")

        # Get role permissions
        permissions = config.get_role_permissions()

        # Get approval-required actions
        approval_actions = config.get_approval_required_actions()
    """

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize the policy config loader.

        Args:
            config_dir: Directory containing policy YAML files
        """
        self.config_dir = config_dir or POLICIES_DIR
        self._cache: dict[str, PolicyConfig] = {}

    def load(self, policy_name: str = "default") -> "PolicyConfig":
        """
        Load a policy configuration by name.

        Args:
            policy_name: Name of the policy (e.g., "default", "lgpd-br", "gdpr-eu")

        Returns:
            PolicyConfig object with loaded configuration

        Raises:
            ConfigLoadError: If the policy cannot be loaded
        """
        if policy_name in self._cache:
            return self._cache[policy_name]

        config_data = self._load_with_inheritance(policy_name)
        config = PolicyConfig(policy_name, config_data)

        self._cache[policy_name] = config
        logger.info("policy_config_loaded", policy_name=policy_name)

        return config

    def _load_with_inheritance(self, policy_name: str) -> dict[str, Any]:
        """Load a policy config, resolving any inheritance."""
        file_path = self.config_dir / f"{policy_name}.yaml"
        config_data = load_yaml_file(file_path)

        # Check for inheritance
        extends = config_data.pop("extends", None)
        if extends:
            base_config = self._load_with_inheritance(extends)
            config_data = deep_merge(base_config, config_data)

        return config_data

    def list_available(self) -> list[str]:
        """List available policy configurations."""
        if not self.config_dir.exists():
            return []
        return [f.stem for f in self.config_dir.glob("*.yaml")]

    def clear_cache(self) -> None:
        """Clear the configuration cache."""
        self._cache.clear()


class PolicyConfig:
    """
    Parsed policy configuration with typed accessors.

    Provides easy access to:
    - Role permissions
    - Severity rules
    - Approval-required actions
    - Compliance settings
    """

    def __init__(self, name: str, config_data: dict[str, Any]):
        """
        Initialize with parsed configuration data.

        Args:
            name: Policy configuration name
            config_data: Parsed YAML configuration
        """
        self.name = name
        self._data = config_data

    @property
    def metadata(self) -> dict[str, Any]:
        """Get policy metadata."""
        return self._data.get("metadata", {})

    @property
    def version(self) -> str:
        """Get policy version."""
        return self.metadata.get("version", "1.0.0")

    @property
    def jurisdiction(self) -> str | None:
        """Get policy jurisdiction."""
        return self.metadata.get("jurisdiction")

    @property
    def regulation(self) -> str | None:
        """Get regulation name (e.g., LGPD, GDPR)."""
        return self.metadata.get("regulation")

    def get_role_permissions(self) -> dict[str, set[str]]:
        """
        Get role-to-actions permission mapping.

        Returns:
            Dictionary mapping role names to sets of allowed actions
        """
        roles_config = self._data.get("roles", {})
        permissions: dict[str, set[str]] = {}

        for role_name, role_data in roles_config.items():
            if isinstance(role_data, dict):
                actions = role_data.get("allowed_actions", [])
            else:
                actions = role_data if isinstance(role_data, list) else []
            permissions[role_name] = set(actions)

        return permissions

    def get_approval_required_actions(self) -> set[str]:
        """
        Get set of actions that always require approval.

        Returns:
            Set of action names requiring approval
        """
        actions = self._data.get("approval_required_actions", [])
        return set(actions)

    def get_severity_rules(self) -> dict[str, dict[str, Any]]:
        """
        Get severity-based approval rules.

        Returns:
            Dictionary mapping severity levels to rule configurations
        """
        return self._data.get("severity_rules", {})

    def get_compliance_settings(self) -> dict[str, Any]:
        """
        Get compliance-specific settings.

        Returns:
            Dictionary with compliance settings (retention, audit fields, etc.)
        """
        return self._data.get("compliance", {})

    def get_action_metadata(self, action_name: str) -> dict[str, Any]:
        """
        Get metadata for a specific action.

        Args:
            action_name: Name of the action

        Returns:
            Dictionary with action metadata (category, risk_level, description)
        """
        actions = self._data.get("actions", {})
        return actions.get(action_name, {})

    def to_dict(self) -> dict[str, Any]:
        """Return the full configuration as a dictionary."""
        return self._data.copy()


class PIIPatternConfigLoader:
    """
    Loads and manages PII pattern configurations.

    Supports:
    - Loading from YAML files
    - Regional pattern sets (Brazil, Ecuador, Europe, etc.)
    - Pattern inheritance and combination
    """

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize the PII pattern config loader.

        Args:
            config_dir: Directory containing PII pattern YAML files
        """
        self.config_dir = config_dir or PII_PATTERNS_DIR
        self._cache: dict[str, PIIPatternConfig] = {}

    def load(self, pattern_set: str = "default") -> "PIIPatternConfig":
        """
        Load a PII pattern configuration by name.

        Args:
            pattern_set: Name of the pattern set (e.g., "default", "brazil", "europe")

        Returns:
            PIIPatternConfig object with loaded patterns

        Raises:
            ConfigLoadError: If the pattern set cannot be loaded
        """
        if pattern_set in self._cache:
            return self._cache[pattern_set]

        config_data = self._load_with_inheritance(pattern_set)
        config = PIIPatternConfig(pattern_set, config_data)

        self._cache[pattern_set] = config
        logger.info("pii_pattern_config_loaded", pattern_set=pattern_set)

        return config

    def _load_with_inheritance(self, pattern_set: str) -> dict[str, Any]:
        """Load a pattern config, resolving any inheritance."""
        file_path = self.config_dir / f"{pattern_set}.yaml"
        config_data = load_yaml_file(file_path)

        # Check for inheritance
        extends = config_data.pop("extends", None)
        if extends:
            base_config = self._load_with_inheritance(extends)
            config_data = deep_merge(base_config, config_data)

        return config_data

    def load_multiple(self, pattern_sets: list[str]) -> "PIIPatternConfig":
        """
        Load and merge multiple pattern sets.

        Args:
            pattern_sets: List of pattern set names to load and merge

        Returns:
            Merged PIIPatternConfig object
        """
        if not pattern_sets:
            return self.load("default")

        merged_data: dict[str, Any] = {}
        for pattern_set in pattern_sets:
            config_data = self._load_with_inheritance(pattern_set)
            merged_data = deep_merge(merged_data, config_data)

        return PIIPatternConfig("+".join(pattern_sets), merged_data)

    def list_available(self) -> list[str]:
        """List available pattern configurations."""
        if not self.config_dir.exists():
            return []
        return [f.stem for f in self.config_dir.glob("*.yaml")]

    def clear_cache(self) -> None:
        """Clear the configuration cache."""
        self._cache.clear()


class PIIPatternConfig:
    """
    Parsed PII pattern configuration with typed accessors.

    Provides compiled regex patterns ready for use with PIIRedactor.
    """

    def __init__(self, name: str, config_data: dict[str, Any]):
        """
        Initialize with parsed configuration data.

        Args:
            name: Pattern configuration name
            config_data: Parsed YAML configuration
        """
        self.name = name
        self._data = config_data
        self._compiled_patterns: list[dict[str, Any]] | None = None

    @property
    def metadata(self) -> dict[str, Any]:
        """Get pattern set metadata."""
        return self._data.get("metadata", {})

    @property
    def jurisdiction(self) -> str | None:
        """Get jurisdiction for this pattern set."""
        return self.metadata.get("jurisdiction")

    def get_patterns(self) -> list[dict[str, Any]]:
        """
        Get pattern definitions with compiled regex.

        Returns:
            List of pattern dictionaries with compiled 'regex' field
        """
        if self._compiled_patterns is not None:
            return self._compiled_patterns

        patterns_config = self._data.get("patterns", [])
        compiled: list[dict[str, Any]] = []

        for pattern_def in patterns_config:
            if not pattern_def.get("enabled", True):
                continue

            try:
                compiled_pattern = {
                    "name": pattern_def["name"],
                    "description": pattern_def.get("description", ""),
                    "token_prefix": pattern_def["token_prefix"],
                    "regex": re.compile(pattern_def["pattern"]),
                    "priority": pattern_def.get("priority", 100),
                }
                compiled.append(compiled_pattern)
            except re.error as e:
                logger.warning(
                    "invalid_pii_pattern",
                    pattern_name=pattern_def.get("name"),
                    error=str(e),
                )

        # Sort by priority (lower = higher priority)
        compiled.sort(key=lambda p: p["priority"])
        self._compiled_patterns = compiled

        return compiled

    def get_validation_settings(self) -> dict[str, Any]:
        """Get validation settings for PII detection."""
        return self._data.get("validation", {})

    def to_dict(self) -> dict[str, Any]:
        """Return the full configuration as a dictionary."""
        return self._data.copy()


# Module-level singleton instances
_policy_loader: PolicyConfigLoader | None = None
_pii_pattern_loader: PIIPatternConfigLoader | None = None


def get_policy_loader() -> PolicyConfigLoader:
    """Get or create the policy config loader singleton."""
    global _policy_loader
    if _policy_loader is None:
        _policy_loader = PolicyConfigLoader()
    return _policy_loader


def get_pii_pattern_loader() -> PIIPatternConfigLoader:
    """Get or create the PII pattern config loader singleton."""
    global _pii_pattern_loader
    if _pii_pattern_loader is None:
        _pii_pattern_loader = PIIPatternConfigLoader()
    return _pii_pattern_loader
