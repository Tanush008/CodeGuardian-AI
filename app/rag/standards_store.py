"""RAG store over the repo's coding-standards document.

Chunks the standards doc, embeds with a local sentence-transformers model
(no API cost, no network dependency for embeddings), and stores in a
persistent ChromaDB collection. The Quality Agent queries this with the
diff's content to ground its review in the team's actual stated conventions
rather than generic style opinions.
"""
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from app.core.config import settings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_COLLECTION_NAME = "coding_standards"
_CHUNK_SIZE = 800  # chars
_CHUNK_OVERLAP = 150


def _chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunks.append(text[start:end])
        start = end - _CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


class StandardsStore:
    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self._embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME, embedding_function=self._embed_fn
        )

    def index_standards_doc(self, path: str | None = None, force: bool = False) -> int:
        """Idempotent indexing: skips if already populated unless force=True.
        Returns the number of chunks indexed."""
        if self._collection.count() > 0 and not force:
            logger.info("standards_already_indexed", count=self._collection.count())
            return self._collection.count()

        doc_path = Path(path or settings.coding_standards_path)
        text = doc_path.read_text(encoding="utf-8")
        chunks = _chunk_text(text)

        if force and self._collection.count() > 0:
            self._client.delete_collection(_COLLECTION_NAME)
            self._collection = self._client.get_or_create_collection(
                name=_COLLECTION_NAME, embedding_function=self._embed_fn
            )

        self._collection.add(
            documents=chunks,
            ids=[f"standards-{i}" for i in range(len(chunks))],
        )
        logger.info("standards_indexed", chunk_count=len(chunks))
        return len(chunks)

    def query(self, text: str, top_k: int = 3) -> list[str]:
        """Return the top_k most relevant standards chunks for a given piece
        of diff/code text. Used to ground the Quality Agent's review."""
        if self._collection.count() == 0:
            return []
        results = self._collection.query(query_texts=[text], n_results=top_k)
        return results.get("documents", [[]])[0]


standards_store = StandardsStore()
