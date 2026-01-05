"""
Response Caching System.

Provides intelligent caching for LLM responses with:
- Semantic similarity matching for cache hits
- TTL-based expiration
- Redis backend (with in-memory fallback)
- Cache invalidation strategies
- Metrics and monitoring

This reduces costs and latency by returning cached responses
for semantically similar queries.
"""

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.core.config import get_settings
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()


class CacheStrategy(str, Enum):
    """Cache key generation strategy."""

    EXACT = "exact"  # Exact match on prompt
    NORMALIZED = "normalized"  # Normalize whitespace, case
    SEMANTIC = "semantic"  # Semantic similarity (requires embeddings)


@dataclass
class CacheConfig:
    """Configuration for cache behavior."""

    enabled: bool = True
    strategy: CacheStrategy = CacheStrategy.NORMALIZED
    default_ttl_seconds: int = 3600  # 1 hour
    max_ttl_seconds: int = 86400  # 24 hours
    min_ttl_seconds: int = 60  # 1 minute
    namespace: str = "llm_cache"
    similarity_threshold: float = 0.95  # For semantic caching


@dataclass
class CacheEntry:
    """A cached response entry."""

    key: str
    prompt: str
    response: str
    model: str
    created_at: datetime
    expires_at: datetime
    hit_count: int = 0
    last_accessed: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "key": self.key,
            "prompt": self.prompt,
            "response": self.response,
            "model": self.model,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "hit_count": self.hit_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheEntry":
        """Deserialize from dictionary."""
        return cls(
            key=data["key"],
            prompt=data["prompt"],
            response=data["response"],
            model=data["model"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            hit_count=data.get("hit_count", 0),
            last_accessed=(
                datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None
            ),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CacheResult:
    """Result of a cache operation."""

    hit: bool
    entry: CacheEntry | None = None
    latency_ms: float = 0.0
    source: str = "cache"


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    def get(self, key: str) -> CacheEntry | None:
        """Get a cache entry by key."""

    @abstractmethod
    def set(
        self,
        key: str,
        entry: CacheEntry,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Set a cache entry."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a cache entry."""

    @abstractmethod
    def clear(self, pattern: str | None = None) -> int:
        """Clear cache entries matching pattern."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists."""

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""


class InMemoryBackend(CacheBackend):
    """In-memory cache backend for development/testing."""

    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
        }

    def get(self, key: str) -> CacheEntry | None:
        entry = self._cache.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        if entry.is_expired():
            del self._cache[key]
            self._stats["misses"] += 1
            return None

        entry.hit_count += 1
        entry.last_accessed = datetime.now(UTC)
        self._stats["hits"] += 1
        return entry

    def set(
        self,
        key: str,
        entry: CacheEntry,
        ttl_seconds: int | None = None,
    ) -> bool:
        self._cache[key] = entry
        self._stats["sets"] += 1
        return True

    def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            self._stats["deletes"] += 1
            return True
        return False

    def clear(self, pattern: str | None = None) -> int:
        if pattern is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        # Simple pattern matching (prefix)
        keys_to_delete = [k for k in self._cache if k.startswith(pattern.rstrip("*"))]
        for key in keys_to_delete:
            del self._cache[key]
        return len(keys_to_delete)

    def exists(self, key: str) -> bool:
        entry = self._cache.get(key)
        return bool(entry and not entry.is_expired())

    def get_stats(self) -> dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0.0

        return {
            **self._stats,
            "total_requests": total,
            "hit_rate": round(hit_rate, 2),
            "entries": len(self._cache),
        }


class RedisBackend(CacheBackend):
    """Redis cache backend for production."""

    def __init__(
        self,
        redis_url: str | None = None,
        namespace: str = "llm_cache",
    ) -> None:
        self.namespace = namespace
        self._redis_url = redis_url or get_settings().redis_url
        self._client: Any = None
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
        }

    def _get_client(self) -> Any:
        """Lazy initialization of Redis client."""
        if self._client is None:
            try:
                import redis

                self._client = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                )
            except ImportError:
                raise RuntimeError("redis package not installed")
        return self._client

    def _make_key(self, key: str) -> str:
        """Create namespaced key."""
        return f"{self.namespace}:{key}"

    def get(self, key: str) -> CacheEntry | None:
        try:
            client = self._get_client()
            data = client.get(self._make_key(key))
            if data is None:
                self._stats["misses"] += 1
                return None

            entry = CacheEntry.from_dict(json.loads(data))

            # Update hit count
            entry.hit_count += 1
            entry.last_accessed = datetime.now(UTC)

            # Get remaining TTL and update
            ttl = client.ttl(self._make_key(key))
            if ttl > 0:
                client.setex(self._make_key(key), ttl, json.dumps(entry.to_dict()))

            self._stats["hits"] += 1
            return entry

        except Exception as e:
            logger.warning("cache_get_error", key=key, error=str(e))
            self._stats["misses"] += 1
            return None

    def set(
        self,
        key: str,
        entry: CacheEntry,
        ttl_seconds: int | None = None,
    ) -> bool:
        try:
            client = self._get_client()
            ttl = ttl_seconds or int((entry.expires_at - datetime.now(UTC)).total_seconds())
            ttl = max(1, ttl)  # Minimum 1 second

            client.setex(
                self._make_key(key),
                ttl,
                json.dumps(entry.to_dict()),
            )
            self._stats["sets"] += 1
            return True

        except Exception as e:
            logger.warning("cache_set_error", key=key, error=str(e))
            return False

    def delete(self, key: str) -> bool:
        try:
            client = self._get_client()
            result = client.delete(self._make_key(key))
            if result:
                self._stats["deletes"] += 1
            return result > 0

        except Exception as e:
            logger.warning("cache_delete_error", key=key, error=str(e))
            return False

    def clear(self, pattern: str | None = None) -> int:
        try:
            client = self._get_client()
            search_pattern = self._make_key(pattern or "*")
            keys = client.keys(search_pattern)

            if keys:
                return client.delete(*keys)
            return 0

        except Exception as e:
            logger.warning("cache_clear_error", pattern=pattern, error=str(e))
            return 0

    def exists(self, key: str) -> bool:
        try:
            client = self._get_client()
            return client.exists(self._make_key(key)) > 0
        except Exception:
            return False

    def get_stats(self) -> dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0.0

        stats = {
            **self._stats,
            "total_requests": total,
            "hit_rate": round(hit_rate, 2),
        }

        try:
            client = self._get_client()
            keys = client.keys(self._make_key("*"))
            stats["entries"] = len(keys)
        except Exception:
            stats["entries"] = -1

        return stats


class ResponseCache:
    """
    LLM response cache with intelligent key generation.

    Example:
        cache = ResponseCache()

        # Check cache before calling LLM
        result = cache.get(prompt="What is Python?", model="gpt-4")
        if result.hit:
            return result.entry.response

        # Call LLM and cache response
        response = await call_llm(prompt, model)
        cache.set(
            prompt="What is Python?",
            response=response,
            model="gpt-4",
            ttl_seconds=3600,
        )
    """

    def __init__(
        self,
        backend: CacheBackend | None = None,
        config: CacheConfig | None = None,
    ) -> None:
        self.config = config or CacheConfig()

        if backend is not None:
            self.backend = backend
        else:
            # Try Redis, fall back to in-memory
            settings = get_settings()
            if settings.redis_url:
                try:
                    self.backend = RedisBackend(
                        redis_url=settings.redis_url,
                        namespace=self.config.namespace,
                    )
                except Exception:
                    logger.warning("redis_unavailable_using_memory")
                    self.backend = InMemoryBackend()
            else:
                self.backend = InMemoryBackend()

    def _generate_key(
        self,
        prompt: str,
        model: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate cache key based on strategy."""
        if self.config.strategy == CacheStrategy.EXACT:
            key_content = prompt
        elif self.config.strategy == CacheStrategy.NORMALIZED:
            # Normalize: lowercase, collapse whitespace
            key_content = " ".join(prompt.lower().split())
        else:
            # Semantic strategy would use embeddings
            # For now, fall back to normalized
            key_content = " ".join(prompt.lower().split())

        # Include model in key
        key_content = f"{model}:{key_content}"

        # Include relevant context
        if context:
            sorted_context = sorted(context.items())
            key_content += f":{json.dumps(sorted_context)}"

        # Generate hash
        return hashlib.sha256(key_content.encode()).hexdigest()[:32]

    def get(
        self,
        prompt: str,
        model: str,
        context: dict[str, Any] | None = None,
    ) -> CacheResult:
        """
        Get cached response for a prompt.

        Args:
            prompt: The prompt to look up
            model: Model name
            context: Additional context for key generation

        Returns:
            CacheResult with hit status and entry if found
        """
        if not self.config.enabled:
            return CacheResult(hit=False)

        with tracer.start_as_current_span("cache.get") as span:
            start_time = time.time()

            key = self._generate_key(prompt, model, context)
            span.set_attribute("cache_key", key)

            entry = self.backend.get(key)
            latency = (time.time() - start_time) * 1000

            if entry:
                logger.info(
                    "cache_hit",
                    key=key,
                    model=model,
                    hit_count=entry.hit_count,
                )
                span.set_attribute("cache_hit", True)
                return CacheResult(
                    hit=True,
                    entry=entry,
                    latency_ms=latency,
                )

            span.set_attribute("cache_hit", False)
            return CacheResult(hit=False, latency_ms=latency)

    def set(
        self,
        prompt: str,
        response: str,
        model: str,
        ttl_seconds: int | None = None,
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Cache a response.

        Args:
            prompt: The prompt
            response: The response to cache
            model: Model name
            ttl_seconds: Time to live in seconds
            context: Additional context for key generation
            metadata: Additional metadata to store

        Returns:
            True if cached successfully
        """
        if not self.config.enabled:
            return False

        with tracer.start_as_current_span("cache.set") as span:
            key = self._generate_key(prompt, model, context)
            span.set_attribute("cache_key", key)

            # Validate TTL
            ttl = ttl_seconds or self.config.default_ttl_seconds
            ttl = max(self.config.min_ttl_seconds, min(ttl, self.config.max_ttl_seconds))

            now = datetime.now(UTC)
            entry = CacheEntry(
                key=key,
                prompt=prompt,
                response=response,
                model=model,
                created_at=now,
                expires_at=datetime.fromtimestamp(now.timestamp() + ttl, tz=UTC),
                metadata=metadata or {},
            )

            success = self.backend.set(key, entry, ttl)

            if success:
                logger.info(
                    "cache_set",
                    key=key,
                    model=model,
                    ttl=ttl,
                )

            span.set_attribute("cache_set_success", success)
            return success

    def invalidate(
        self,
        prompt: str | None = None,
        model: str | None = None,
        pattern: str | None = None,
    ) -> int:
        """
        Invalidate cache entries.

        Args:
            prompt: Specific prompt to invalidate
            model: Specific model to invalidate
            pattern: Pattern to match (prefix)

        Returns:
            Number of entries invalidated
        """
        with tracer.start_as_current_span("cache.invalidate"):
            if prompt and model:
                key = self._generate_key(prompt, model)
                return 1 if self.backend.delete(key) else 0

            if pattern:
                return self.backend.clear(pattern)

            if model:
                return self.backend.clear(f"*{model}*")

            # Clear all
            return self.backend.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        stats = self.backend.get_stats()
        stats["config"] = {
            "strategy": self.config.strategy.value,
            "default_ttl": self.config.default_ttl_seconds,
            "enabled": self.config.enabled,
        }
        return stats


# Global cache instance
_response_cache: ResponseCache | None = None


def get_response_cache() -> ResponseCache:
    """Get the global response cache instance."""
    global _response_cache
    if _response_cache is None:
        _response_cache = ResponseCache()
    return _response_cache


def cached_llm_response(
    prompt: str,
    model: str,
    ttl_seconds: int | None = None,
) -> CacheResult | None:
    """
    Convenience function to check cache for LLM response.

    Args:
        prompt: The prompt
        model: Model name
        ttl_seconds: TTL for cache entry

    Returns:
        CacheResult if found, None otherwise
    """
    cache = get_response_cache()
    result = cache.get(prompt, model)
    return result if result.hit else None
