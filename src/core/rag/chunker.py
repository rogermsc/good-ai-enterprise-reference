"""
Document chunking utilities for RAG pipeline.

Splits documents into chunks suitable for embedding and retrieval.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import tiktoken


class ChunkingStrategy(str, Enum):
    """Available chunking strategies."""

    FIXED_SIZE = "fixed_size"
    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"
    RECURSIVE = "recursive"


@dataclass
class Chunk:
    """A chunk of text from a document."""

    content: str
    index: int
    metadata: dict[str, Any]
    token_count: int


class Chunker:
    """
    Document chunking service.

    Splits documents into overlapping chunks for embedding.

    Example:
        chunker = Chunker(chunk_size=512, overlap=50)
        chunks = chunker.chunk("Long document text...", metadata={"source": "doc.pdf"})
    """

    def __init__(
        self,
        chunk_size: int = 512,
        overlap: int = 50,
        strategy: ChunkingStrategy = ChunkingStrategy.RECURSIVE,
        model: str = "gpt-4",
    ):
        """
        Initialize chunker.

        Args:
            chunk_size: Target chunk size in tokens
            overlap: Number of overlapping tokens between chunks
            strategy: Chunking strategy to use
            model: Model for token counting (tiktoken encoding)
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.strategy = strategy

        # Initialize tokenizer for accurate token counting
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))

    def chunk(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """
        Split text into chunks.

        Args:
            text: Text to chunk
            metadata: Metadata to attach to each chunk

        Returns:
            List of Chunk objects
        """
        if self.strategy == ChunkingStrategy.FIXED_SIZE:
            return self._chunk_fixed_size(text, metadata or {})
        elif self.strategy == ChunkingStrategy.SENTENCE:
            return self._chunk_by_sentence(text, metadata or {})
        elif self.strategy == ChunkingStrategy.PARAGRAPH:
            return self._chunk_by_paragraph(text, metadata or {})
        else:
            return self._chunk_recursive(text, metadata or {})

    def _chunk_fixed_size(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Split text into fixed-size token chunks with overlap."""
        tokens = self.encoding.encode(text)
        chunks = []

        start = 0
        index = 0

        while start < len(tokens):
            end = min(start + self.chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunk_text = self.encoding.decode(chunk_tokens)

            chunks.append(
                Chunk(
                    content=chunk_text,
                    index=index,
                    metadata={**metadata, "chunk_index": index},
                    token_count=len(chunk_tokens),
                )
            )

            start = end - self.overlap if end < len(tokens) else end
            index += 1

        return chunks

    def _chunk_by_sentence(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Split text by sentences, grouping into target size."""
        # Simple sentence splitting (production would use spaCy or similar)
        sentences = []
        current = ""

        for char in text:
            current += char
            if char in ".!?" and len(current.strip()) > 0:
                sentences.append(current.strip())
                current = ""

        if current.strip():
            sentences.append(current.strip())

        return self._group_into_chunks(sentences, metadata)

    def _chunk_by_paragraph(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Split text by paragraphs, grouping into target size."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return self._group_into_chunks(paragraphs, metadata)

    def _chunk_recursive(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """
        Recursively split text using hierarchy of separators.

        Tries to maintain semantic coherence by splitting on:
        1. Paragraphs (\\n\\n)
        2. Sentences (. ! ?)
        3. Words (space)
        4. Characters (fallback)
        """
        separators = ["\n\n", "\n", ". ", "! ", "? ", " ", ""]

        return self._recursive_split(text, separators, metadata)

    def _recursive_split(
        self,
        text: str,
        separators: list[str],
        metadata: dict[str, Any],
        depth: int = 0,
    ) -> list[Chunk]:
        """Recursively split text using separators."""
        if not text.strip():
            return []

        token_count = self.count_tokens(text)

        # Base case: text fits in one chunk
        if token_count <= self.chunk_size:
            return [
                Chunk(
                    content=text,
                    index=0,
                    metadata={**metadata, "chunk_index": 0},
                    token_count=token_count,
                )
            ]

        # Find appropriate separator
        separator = separators[0] if separators else ""
        remaining_separators = separators[1:] if len(separators) > 1 else [""]

        # Character-level split as fallback when no separator
        parts = text.split(separator) if separator else list(text)

        # Group parts into chunks
        chunks = []
        current_parts: list[str] = []
        current_tokens = 0
        index = 0

        for part in parts:
            part_with_sep = part + separator if separator else part
            part_tokens = self.count_tokens(part_with_sep)

            if current_tokens + part_tokens > self.chunk_size and current_parts:
                # Finalize current chunk
                chunk_text = separator.join(current_parts) if separator else "".join(current_parts)

                if self.count_tokens(chunk_text) > self.chunk_size and remaining_separators:
                    # Recursively split if still too large
                    sub_chunks = self._recursive_split(
                        chunk_text,
                        remaining_separators,
                        metadata,
                        depth + 1,
                    )
                    for sub_chunk in sub_chunks:
                        sub_chunk.index = index
                        sub_chunk.metadata["chunk_index"] = index
                        chunks.append(sub_chunk)
                        index += 1
                else:
                    chunks.append(
                        Chunk(
                            content=chunk_text,
                            index=index,
                            metadata={**metadata, "chunk_index": index},
                            token_count=self.count_tokens(chunk_text),
                        )
                    )
                    index += 1

                # Start new chunk with overlap
                overlap_parts = current_parts[-2:] if len(current_parts) > 2 else []
                current_parts = [*overlap_parts, part]
                current_tokens = sum(self.count_tokens(p + separator) for p in current_parts)
            else:
                current_parts.append(part)
                current_tokens += part_tokens

        # Handle remaining parts
        if current_parts:
            chunk_text = separator.join(current_parts) if separator else "".join(current_parts)
            chunks.append(
                Chunk(
                    content=chunk_text,
                    index=index,
                    metadata={**metadata, "chunk_index": index},
                    token_count=self.count_tokens(chunk_text),
                )
            )

        return chunks

    def _group_into_chunks(
        self,
        segments: list[str],
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Group segments into target-sized chunks."""
        chunks = []
        current_segments: list[str] = []
        current_tokens = 0
        index = 0

        for segment in segments:
            segment_tokens = self.count_tokens(segment)

            if current_tokens + segment_tokens > self.chunk_size and current_segments:
                # Finalize current chunk
                chunk_text = " ".join(current_segments)
                chunks.append(
                    Chunk(
                        content=chunk_text,
                        index=index,
                        metadata={**metadata, "chunk_index": index},
                        token_count=current_tokens,
                    )
                )
                index += 1

                # Start new chunk with last segment as overlap
                current_segments = (
                    [current_segments[-1], segment] if current_segments else [segment]
                )
                current_tokens = sum(self.count_tokens(s) for s in current_segments)
            else:
                current_segments.append(segment)
                current_tokens += segment_tokens

        # Handle remaining segments
        if current_segments:
            chunk_text = " ".join(current_segments)
            chunks.append(
                Chunk(
                    content=chunk_text,
                    index=index,
                    metadata={**metadata, "chunk_index": index},
                    token_count=self.count_tokens(chunk_text),
                )
            )

        return chunks
