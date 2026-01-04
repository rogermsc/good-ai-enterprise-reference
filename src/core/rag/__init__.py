"""
RAG (Retrieval-Augmented Generation) pipeline components.

Provides:
- Document chunking and preprocessing
- Embedding generation (OpenAI or mock)
- Vector storage with pgvector
- Semantic search and retrieval
"""

from src.core.rag.chunker import Chunker, ChunkingStrategy
from src.core.rag.embeddings import EmbeddingService
from src.core.rag.vector_store import Document, SearchResult, VectorStore

__all__ = [
    "Chunker",
    "ChunkingStrategy",
    "Document",
    "EmbeddingService",
    "SearchResult",
    "VectorStore",
]
