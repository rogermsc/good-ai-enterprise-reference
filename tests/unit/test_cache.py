"""Tests for response caching system."""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.cache import (
    CacheConfig,
    CacheEntry,
    CacheResult,
    CacheStrategy,
    InMemoryBackend,
    ResponseCache,
    cached_llm_response,
    get_response_cache,
)


class TestCacheEntry:
    """Tests for cache entry."""

    def test_create_entry(self) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="test-key",
            prompt="What is Python?",
            response="Python is a programming language.",
            model="gpt-4",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert entry.key == "test-key"
        assert entry.hit_count == 0
        assert not entry.is_expired()

    def test_expired_entry(self) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="test-key",
            prompt="test",
            response="test",
            model="gpt-4",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        assert entry.is_expired()

    def test_serialization(self) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="test-key",
            prompt="test prompt",
            response="test response",
            model="gpt-4",
            created_at=now,
            expires_at=now + timedelta(hours=1),
            hit_count=5,
            metadata={"source": "test"},
        )

        data = entry.to_dict()
        restored = CacheEntry.from_dict(data)

        assert restored.key == entry.key
        assert restored.prompt == entry.prompt
        assert restored.response == entry.response
        assert restored.model == entry.model
        assert restored.hit_count == entry.hit_count
        assert restored.metadata == entry.metadata


class TestCacheResult:
    """Tests for cache result."""

    def test_hit_result(self) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="test",
            prompt="test",
            response="test",
            model="gpt-4",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        result = CacheResult(hit=True, entry=entry, latency_ms=5.0)
        assert result.hit is True
        assert result.entry is not None
        assert result.latency_ms == 5.0

    def test_miss_result(self) -> None:
        result = CacheResult(hit=False)
        assert result.hit is False
        assert result.entry is None


class TestInMemoryBackend:
    """Tests for in-memory cache backend."""

    @pytest.fixture
    def backend(self) -> InMemoryBackend:
        return InMemoryBackend()

    def test_set_and_get(self, backend: InMemoryBackend) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="test-key",
            prompt="test",
            response="response",
            model="gpt-4",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        assert backend.set("test-key", entry)
        retrieved = backend.get("test-key")

        assert retrieved is not None
        assert retrieved.response == "response"
        assert retrieved.hit_count == 1

    def test_get_nonexistent(self, backend: InMemoryBackend) -> None:
        assert backend.get("nonexistent") is None

    def test_get_expired(self, backend: InMemoryBackend) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="expired",
            prompt="test",
            response="response",
            model="gpt-4",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )

        backend.set("expired", entry)
        assert backend.get("expired") is None

    def test_delete(self, backend: InMemoryBackend) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="to-delete",
            prompt="test",
            response="response",
            model="gpt-4",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        backend.set("to-delete", entry)
        assert backend.delete("to-delete") is True
        assert backend.get("to-delete") is None
        assert backend.delete("nonexistent") is False

    def test_exists(self, backend: InMemoryBackend) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="exists",
            prompt="test",
            response="response",
            model="gpt-4",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        assert backend.exists("exists") is False
        backend.set("exists", entry)
        assert backend.exists("exists") is True

    def test_clear_all(self, backend: InMemoryBackend) -> None:
        now = datetime.now(UTC)
        for i in range(5):
            entry = CacheEntry(
                key=f"key-{i}",
                prompt="test",
                response="response",
                model="gpt-4",
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
            backend.set(f"key-{i}", entry)

        cleared = backend.clear()
        assert cleared == 5
        assert backend.get("key-0") is None

    def test_clear_pattern(self, backend: InMemoryBackend) -> None:
        now = datetime.now(UTC)
        for prefix in ["alpha", "beta"]:
            for i in range(3):
                entry = CacheEntry(
                    key=f"{prefix}-{i}",
                    prompt="test",
                    response="response",
                    model="gpt-4",
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                )
                backend.set(f"{prefix}-{i}", entry)

        cleared = backend.clear("alpha*")
        assert cleared == 3
        assert backend.get("alpha-0") is None
        assert backend.get("beta-0") is not None

    def test_stats(self, backend: InMemoryBackend) -> None:
        now = datetime.now(UTC)
        entry = CacheEntry(
            key="stats-test",
            prompt="test",
            response="response",
            model="gpt-4",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        # Generate some activity
        backend.set("stats-test", entry)
        backend.get("stats-test")  # Hit
        backend.get("nonexistent")  # Miss

        stats = backend.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["sets"] == 1
        assert stats["hit_rate"] == 50.0
        assert stats["entries"] == 1


class TestCacheConfig:
    """Tests for cache configuration."""

    def test_default_config(self) -> None:
        config = CacheConfig()
        assert config.enabled is True
        assert config.strategy == CacheStrategy.NORMALIZED
        assert config.default_ttl_seconds == 3600

    def test_custom_config(self) -> None:
        config = CacheConfig(
            enabled=False,
            strategy=CacheStrategy.EXACT,
            default_ttl_seconds=7200,
            namespace="custom_cache",
        )
        assert config.enabled is False
        assert config.strategy == CacheStrategy.EXACT
        assert config.default_ttl_seconds == 7200
        assert config.namespace == "custom_cache"


class TestResponseCache:
    """Tests for response cache."""

    @pytest.fixture
    def cache(self) -> ResponseCache:
        backend = InMemoryBackend()
        return ResponseCache(backend=backend)

    def test_get_miss(self, cache: ResponseCache) -> None:
        result = cache.get(prompt="What is Python?", model="gpt-4")
        assert result.hit is False
        assert result.entry is None

    def test_set_and_get(self, cache: ResponseCache) -> None:
        prompt = "What is Python?"
        response = "Python is a programming language."
        model = "gpt-4"

        cache.set(prompt=prompt, response=response, model=model)
        result = cache.get(prompt=prompt, model=model)

        assert result.hit is True
        assert result.entry is not None
        assert result.entry.response == response

    def test_normalized_matching(self, cache: ResponseCache) -> None:
        prompt1 = "What is Python?"
        prompt2 = "what   is   python?"  # Different case and whitespace
        response = "Python is a programming language."

        cache.set(prompt=prompt1, response=response, model="gpt-4")
        result = cache.get(prompt=prompt2, model="gpt-4")

        assert result.hit is True

    def test_different_models_different_keys(self, cache: ResponseCache) -> None:
        prompt = "What is Python?"

        cache.set(prompt=prompt, response="GPT-4 response", model="gpt-4")
        cache.set(prompt=prompt, response="GPT-3.5 response", model="gpt-3.5")

        result_gpt4 = cache.get(prompt=prompt, model="gpt-4")
        result_gpt35 = cache.get(prompt=prompt, model="gpt-3.5")

        assert result_gpt4.entry.response == "GPT-4 response"
        assert result_gpt35.entry.response == "GPT-3.5 response"

    def test_context_affects_key(self, cache: ResponseCache) -> None:
        prompt = "Summarize this document"

        cache.set(
            prompt=prompt,
            response="Summary of doc A",
            model="gpt-4",
            context={"doc_id": "A"},
        )

        # Different context should be a miss
        result = cache.get(
            prompt=prompt,
            model="gpt-4",
            context={"doc_id": "B"},
        )
        assert result.hit is False

        # Same context should be a hit
        result = cache.get(
            prompt=prompt,
            model="gpt-4",
            context={"doc_id": "A"},
        )
        assert result.hit is True

    def test_ttl_enforcement(self, cache: ResponseCache) -> None:
        # Set with minimum TTL
        cache.set(
            prompt="test",
            response="response",
            model="gpt-4",
            ttl_seconds=1,  # Will be adjusted to min_ttl
        )

        # Should hit immediately
        result = cache.get(prompt="test", model="gpt-4")
        assert result.hit is True

    def test_disabled_cache(self) -> None:
        config = CacheConfig(enabled=False)
        cache = ResponseCache(backend=InMemoryBackend(), config=config)

        cache.set(prompt="test", response="response", model="gpt-4")
        result = cache.get(prompt="test", model="gpt-4")

        assert result.hit is False

    def test_invalidate_specific(self, cache: ResponseCache) -> None:
        cache.set(prompt="test1", response="response1", model="gpt-4")
        cache.set(prompt="test2", response="response2", model="gpt-4")

        count = cache.invalidate(prompt="test1", model="gpt-4")
        assert count == 1

        assert cache.get(prompt="test1", model="gpt-4").hit is False
        assert cache.get(prompt="test2", model="gpt-4").hit is True

    def test_invalidate_all(self, cache: ResponseCache) -> None:
        cache.set(prompt="test1", response="response1", model="gpt-4")
        cache.set(prompt="test2", response="response2", model="gpt-4")

        count = cache.invalidate()
        assert count == 2

    def test_get_stats(self, cache: ResponseCache) -> None:
        cache.set(prompt="test", response="response", model="gpt-4")
        cache.get(prompt="test", model="gpt-4")
        cache.get(prompt="nonexistent", model="gpt-4")

        stats = cache.get_stats()
        assert "hits" in stats
        assert "misses" in stats
        assert "config" in stats
        assert stats["config"]["strategy"] == "normalized"

    def test_metadata_preserved(self, cache: ResponseCache) -> None:
        cache.set(
            prompt="test",
            response="response",
            model="gpt-4",
            metadata={"source": "api", "user": "test-user"},
        )

        result = cache.get(prompt="test", model="gpt-4")
        assert result.entry.metadata["source"] == "api"
        assert result.entry.metadata["user"] == "test-user"


class TestExactCacheStrategy:
    """Tests for exact matching strategy."""

    def test_exact_match_required(self) -> None:
        config = CacheConfig(strategy=CacheStrategy.EXACT)
        cache = ResponseCache(backend=InMemoryBackend(), config=config)

        cache.set(prompt="What is Python?", response="response", model="gpt-4")

        # Exact match hits
        result = cache.get(prompt="What is Python?", model="gpt-4")
        assert result.hit is True

        # Different case misses with exact strategy
        result = cache.get(prompt="what is python?", model="gpt-4")
        assert result.hit is False


class TestGlobalCache:
    """Tests for global cache functions."""

    @pytest.fixture(autouse=True)
    def reset_global_cache(self) -> None:
        """Reset global cache before each test."""
        import src.core.cache as cache_module

        # Reset global cache to None so it gets recreated with in-memory backend
        cache_module._response_cache = None
        # Create a new cache with in-memory backend for testing
        cache_module._response_cache = ResponseCache(backend=InMemoryBackend())

    def test_get_response_cache_singleton(self) -> None:
        cache1 = get_response_cache()
        cache2 = get_response_cache()
        assert cache1 is cache2

    def test_cached_llm_response_miss(self) -> None:
        result = cached_llm_response(
            prompt="unique prompt for test",
            model="test-model",
        )
        assert result is None

    def test_cached_llm_response_hit(self) -> None:
        cache = get_response_cache()
        cache.set(
            prompt="cached test prompt",
            response="cached response",
            model="cache-test-model",
        )

        result = cached_llm_response(
            prompt="cached test prompt",
            model="cache-test-model",
        )
        assert result is not None
        assert result.hit is True
