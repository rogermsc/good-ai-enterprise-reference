"""
Embedding service for generating vector representations of text.

Supports OpenAI embeddings API and mock mode for testing.
"""

import hashlib
from dataclasses import dataclass

import httpx
import numpy as np

from src.core.config import Settings, get_settings
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()

# Embedding dimensions for common models
EMBEDDING_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""

    embedding: list[float]
    model: str
    dimensions: int
    token_count: int
    is_mock: bool = False


class EmbeddingService:
    """
    Service for generating text embeddings.

    Supports OpenAI embeddings API with fallback to mock mode.

    Example:
        service = EmbeddingService()

        # Single embedding
        result = await service.embed("Hello world")

        # Batch embeddings
        results = await service.embed_batch(["Hello", "World"])
    """

    def __init__(
        self,
        settings: Settings | None = None,
        model: str = "text-embedding-3-small",
    ):
        """
        Initialize embedding service.

        Args:
            settings: Application settings
            model: Embedding model to use
        """
        self.settings = settings or get_settings()
        self.model = model
        self.dimensions = EMBEDDING_DIMENSIONS.get(model, 1536)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def embed(self, text: str) -> EmbeddingResult:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            EmbeddingResult with embedding vector
        """
        with tracer.start_as_current_span("embedding.generate") as span:
            span.set_attribute("embedding.model", self.model)
            span.set_attribute("embedding.text_length", len(text))

            if self.settings.is_mock_mode:
                return self._mock_embed(text)

            client = await self._get_client()

            response = await client.post(
                f"{self.settings.openai_base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": text,
                },
            )
            response.raise_for_status()

            data = response.json()
            embedding = data["data"][0]["embedding"]
            token_count = data["usage"]["total_tokens"]

            span.set_attribute("embedding.token_count", token_count)

            logger.info(
                "embedding_generated",
                model=self.model,
                token_count=token_count,
            )

            return EmbeddingResult(
                embedding=embedding,
                model=self.model,
                dimensions=len(embedding),
                token_count=token_count,
            )

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 100,
    ) -> list[EmbeddingResult]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            batch_size: Maximum texts per API call

        Returns:
            List of EmbeddingResult objects
        """
        with tracer.start_as_current_span("embedding.batch") as span:
            span.set_attribute("embedding.batch_size", len(texts))

            if self.settings.is_mock_mode:
                return [self._mock_embed(text) for text in texts]

            results: list[EmbeddingResult] = []

            # Process in batches
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]

                client = await self._get_client()

                response = await client.post(
                    f"{self.settings.openai_base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "input": batch,
                    },
                )
                response.raise_for_status()

                data = response.json()
                token_count = data["usage"]["total_tokens"]

                for item in data["data"]:
                    results.append(
                        EmbeddingResult(
                            embedding=item["embedding"],
                            model=self.model,
                            dimensions=len(item["embedding"]),
                            token_count=token_count // len(batch),
                        )
                    )

            logger.info(
                "batch_embeddings_generated",
                model=self.model,
                count=len(results),
            )

            return results

    def _mock_embed(self, text: str) -> EmbeddingResult:
        """
        Generate deterministic mock embedding for testing.

        Uses hash of text to generate reproducible embeddings.
        """
        # Create deterministic embedding from text hash
        hash_bytes = hashlib.sha256(text.encode()).digest()

        # Use hash to seed random generator for reproducibility
        seed = int.from_bytes(hash_bytes[:4], "big")
        rng = np.random.default_rng(seed)

        # Generate normalized embedding
        embedding = rng.standard_normal(self.dimensions).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        return EmbeddingResult(
            embedding=embedding.tolist(),
            model="mock",
            dimensions=self.dimensions,
            token_count=len(text.split()),
            is_mock=True,
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)

    dot_product = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot_product / (norm_a * norm_b))
