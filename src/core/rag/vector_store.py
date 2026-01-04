"""
Vector store using PostgreSQL with pgvector extension.

Provides document storage and semantic search capabilities.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
from pgvector.asyncpg import register_vector

from src.core.observability import get_logger, get_tracer
from src.core.rag.embeddings import EmbeddingService

# Pattern for safe metadata keys (alphanumeric and underscores only)
SAFE_KEY_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

logger = get_logger()
tracer = get_tracer()


@dataclass
class Document:
    """A document stored in the vector store."""

    id: str
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tenant_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        content: str,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> "Document":
        """Create a new document with generated ID."""
        return cls(
            id=str(uuid4()),
            content=content,
            metadata=metadata or {},
            tenant_id=tenant_id,
        )


@dataclass
class SearchResult:
    """Result from vector similarity search."""

    document: Document
    score: float
    distance: float


class VectorStore:
    """
    Vector store backed by PostgreSQL with pgvector.

    Provides:
    - Document storage with embeddings
    - Semantic similarity search
    - Tenant isolation
    - Metadata filtering

    Example:
        store = VectorStore(embedding_service)
        await store.initialize(conn)

        # Add documents
        doc = Document.create("Hello world", metadata={"source": "test"})
        await store.add(conn, doc)

        # Search
        results = await store.search(conn, "greeting", limit=5)
    """

    # SQL for creating the documents table
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS documents (
        id UUID PRIMARY KEY,
        content TEXT NOT NULL,
        embedding vector({dimensions}),
        metadata JSONB DEFAULT '{}',
        tenant_id VARCHAR(255),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS documents_tenant_idx ON documents(tenant_id);
    CREATE INDEX IF NOT EXISTS documents_created_idx ON documents(created_at);
    CREATE INDEX IF NOT EXISTS documents_embedding_idx ON documents
        USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        table_name: str = "documents",
        dimensions: int = 1536,
    ):
        """
        Initialize vector store.

        Args:
            embedding_service: Service for generating embeddings
            table_name: Name of the documents table
            dimensions: Embedding dimensions
        """
        self.embedding_service = embedding_service or EmbeddingService()
        self.table_name = table_name
        self.dimensions = dimensions

    async def initialize(self, conn: asyncpg.Connection) -> None:
        """
        Initialize the vector store schema.

        Creates the documents table and required indexes.
        """
        with tracer.start_as_current_span("vector_store.initialize"):
            # Register pgvector type
            await register_vector(conn)

            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Create table
            await conn.execute(self.CREATE_TABLE_SQL.format(dimensions=self.dimensions))

            logger.info("vector_store_initialized", table=self.table_name)

    async def add(
        self,
        conn: asyncpg.Connection,
        document: Document,
        generate_embedding: bool = True,
    ) -> Document:
        """
        Add a document to the store.

        Args:
            conn: Database connection
            document: Document to add
            generate_embedding: Whether to generate embedding if missing

        Returns:
            Document with embedding populated
        """
        with tracer.start_as_current_span("vector_store.add") as span:
            span.set_attribute("document.id", document.id)

            # Generate embedding if needed
            if generate_embedding and document.embedding is None:
                result = await self.embedding_service.embed(document.content)
                document.embedding = result.embedding

            # Insert document
            await conn.execute(
                """
                INSERT INTO documents (id, content, embedding, metadata, tenant_id, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                document.id,
                document.content,
                document.embedding,
                document.metadata,
                document.tenant_id,
                document.created_at,
            )

            logger.info(
                "document_added",
                document_id=document.id,
                tenant_id=document.tenant_id,
            )

            return document

    async def add_batch(
        self,
        conn: asyncpg.Connection,
        documents: list[Document],
        generate_embeddings: bool = True,
    ) -> list[Document]:
        """
        Add multiple documents to the store.

        Args:
            conn: Database connection
            documents: Documents to add
            generate_embeddings: Whether to generate embeddings

        Returns:
            Documents with embeddings populated
        """
        with tracer.start_as_current_span("vector_store.add_batch") as span:
            span.set_attribute("batch_size", len(documents))

            # Generate embeddings for documents that need them
            if generate_embeddings:
                texts_to_embed = []
                indices_to_embed = []

                for i, doc in enumerate(documents):
                    if doc.embedding is None:
                        texts_to_embed.append(doc.content)
                        indices_to_embed.append(i)

                if texts_to_embed:
                    results = await self.embedding_service.embed_batch(texts_to_embed)
                    for idx, result in zip(indices_to_embed, results, strict=True):
                        documents[idx].embedding = result.embedding

            # Batch insert
            await conn.executemany(
                """
                INSERT INTO documents (id, content, embedding, metadata, tenant_id, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                [
                    (
                        doc.id,
                        doc.content,
                        doc.embedding,
                        doc.metadata,
                        doc.tenant_id,
                        doc.created_at,
                    )
                    for doc in documents
                ],
            )

            logger.info("documents_batch_added", count=len(documents))

            return documents

    async def search(
        self,
        conn: asyncpg.Connection,
        query: str,
        limit: int = 10,
        tenant_id: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """
        Search for similar documents.

        Args:
            conn: Database connection
            query: Search query text
            limit: Maximum results to return
            tenant_id: Filter by tenant
            metadata_filter: Filter by metadata fields
            min_score: Minimum similarity score (0-1)

        Returns:
            List of SearchResult ordered by similarity
        """
        with tracer.start_as_current_span("vector_store.search") as span:
            span.set_attribute("query_length", len(query))
            span.set_attribute("limit", limit)

            # Generate query embedding
            query_result = await self.embedding_service.embed(query)
            query_embedding = query_result.embedding

            # Build query with filters
            conditions = []
            params: list[Any] = [query_embedding, limit]
            param_idx = 3

            if tenant_id:
                conditions.append(f"tenant_id = ${param_idx}")
                params.append(tenant_id)
                param_idx += 1

            if metadata_filter:
                for key, value in metadata_filter.items():
                    # Validate key to prevent SQL injection
                    if not SAFE_KEY_PATTERN.match(key):
                        logger.warning(
                            "invalid_metadata_key",
                            key=key,
                            reason="Key must be alphanumeric with underscores",
                        )
                        continue
                    conditions.append(f"metadata->>'{key}' = ${param_idx}")
                    params.append(str(value))
                    param_idx += 1

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            # Execute similarity search
            rows = await conn.fetch(
                f"""
                SELECT
                    id,
                    content,
                    embedding,
                    metadata,
                    tenant_id,
                    created_at,
                    1 - (embedding <=> $1) as score,
                    embedding <=> $1 as distance
                FROM documents
                {where_clause}
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                *params,
            )

            results = []
            for row in rows:
                score = float(row["score"])
                if score >= min_score:
                    doc = Document(
                        id=str(row["id"]),
                        content=row["content"],
                        embedding=list(row["embedding"]) if row["embedding"] else None,
                        metadata=dict(row["metadata"]) if row["metadata"] else {},
                        tenant_id=row["tenant_id"],
                        created_at=row["created_at"],
                    )
                    results.append(
                        SearchResult(
                            document=doc,
                            score=score,
                            distance=float(row["distance"]),
                        )
                    )

            span.set_attribute("results_count", len(results))

            logger.info(
                "vector_search_completed",
                results=len(results),
                tenant_id=tenant_id,
            )

            return results

    async def get(
        self,
        conn: asyncpg.Connection,
        document_id: str,
    ) -> Document | None:
        """Get a document by ID."""
        row = await conn.fetchrow(
            """
            SELECT id, content, embedding, metadata, tenant_id, created_at
            FROM documents
            WHERE id = $1
            """,
            document_id,
        )

        if not row:
            return None

        return Document(
            id=str(row["id"]),
            content=row["content"],
            embedding=list(row["embedding"]) if row["embedding"] else None,
            metadata=dict(row["metadata"]) if row["metadata"] else {},
            tenant_id=row["tenant_id"],
            created_at=row["created_at"],
        )

    async def delete(
        self,
        conn: asyncpg.Connection,
        document_id: str,
    ) -> bool:
        """Delete a document by ID."""
        result = await conn.execute(
            "DELETE FROM documents WHERE id = $1",
            document_id,
        )
        return result == "DELETE 1"

    async def delete_by_tenant(
        self,
        conn: asyncpg.Connection,
        tenant_id: str,
    ) -> int:
        """Delete all documents for a tenant."""
        result = await conn.execute(
            "DELETE FROM documents WHERE tenant_id = $1",
            tenant_id,
        )
        count = int(result.split()[-1])
        logger.info("documents_deleted_by_tenant", tenant_id=tenant_id, count=count)
        return count

    async def count(
        self,
        conn: asyncpg.Connection,
        tenant_id: str | None = None,
    ) -> int:
        """Count documents, optionally filtered by tenant."""
        if tenant_id:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as count FROM documents WHERE tenant_id = $1",
                tenant_id,
            )
        else:
            row = await conn.fetchrow("SELECT COUNT(*) as count FROM documents")

        return int(row["count"]) if row else 0
