from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from re import findall
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    document_id: str
    source: str
    content: str
    metadata: dict[str, Any]

    def to_dict(self, score: float | None = None) -> dict:
        payload = asdict(self)
        if score is not None:
            payload["score"] = score
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DocumentChunk":
        return cls(
            id=str(payload["id"]),
            document_id=str(payload["document_id"]),
            source=str(payload["source"]),
            content=str(payload["content"]),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    title: str
    source: str
    metadata: dict[str, Any]
    chunks: list[DocumentChunk] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "metadata": self.metadata,
            "chunk_count": len(self.chunks),
            "created_at": self.created_at,
        }

    def to_storage_dict(self) -> dict:
        return {
            **self.to_dict(),
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }

    @classmethod
    def from_storage_dict(cls, payload: dict[str, Any]) -> "DocumentRecord":
        return cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            source=str(payload["source"]),
            metadata=dict(payload.get("metadata") or {}),
            chunks=[DocumentChunk.from_dict(chunk) for chunk in payload.get("chunks") or []],
            created_at=str(payload.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )


class DocumentStore:
    def __init__(self, records: list[DocumentRecord] | None = None):
        self._records: dict[str, DocumentRecord] = {}
        for record in records or []:
            self._records[record.id] = record

    def add_document(self, title: str, content: str, metadata: dict[str, Any] | None = None) -> DocumentRecord:
        doc_id = f"doc-{uuid4().hex[:10]}"
        source = str((metadata or {}).get("source") or title)
        chunks = [
            DocumentChunk(
                id=f"{doc_id}-chunk-{index + 1}",
                document_id=doc_id,
                source=source,
                content=chunk,
                metadata={**(metadata or {}), "title": title, "chunk_index": index + 1},
            )
            for index, chunk in enumerate(_split_chunks(content))
        ]
        record = DocumentRecord(
            id=doc_id,
            title=title,
            source=source,
            metadata=metadata or {},
            chunks=chunks,
        )
        self._records[record.id] = record
        return record

    def list_documents(self) -> list[dict]:
        return [record.to_dict() for record in self._records.values()]

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        terms = _terms(query)
        scored = []
        for record in self._records.values():
            for chunk in record.chunks:
                score = _score_chunk(chunk, terms)
                if score > 0:
                    scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk.to_dict(score=round(score, 2)) for score, chunk in scored[:top_k]]


class SQLiteDocumentStore(DocumentStore):
    def __init__(self, db_path: str | Path, seed_defaults: bool = True):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        records = self._load_records()
        super().__init__(records)
        if seed_defaults and not records:
            _seed_default_documents(self)

    def add_document(self, title: str, content: str, metadata: dict[str, Any] | None = None) -> DocumentRecord:
        record = super().add_document(title, content, metadata)
        self._save_record(record)
        return record

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _load_records(self) -> list[DocumentRecord]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT payload FROM documents ORDER BY created_at ASC").fetchall()
        return [DocumentRecord.from_storage_dict(json.loads(payload)) for (payload,) in rows]

    def _save_record(self, record: DocumentRecord) -> None:
        payload = json.dumps(record.to_storage_dict(), ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO documents (id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (record.id, payload, record.created_at, datetime.now(timezone.utc).isoformat()),
            )


def default_document_store() -> DocumentStore:
    store = DocumentStore()
    _seed_default_documents(store)
    return store


def sqlite_document_store(db_path: str | Path) -> SQLiteDocumentStore:
    return SQLiteDocumentStore(db_path)


def _seed_default_documents(store: DocumentStore) -> None:
    store.add_document(
        "Agent Runtime 架构说明",
        "Router -> Planner -> Executor -> Generator 是主链路。Trace 负责记录每一步输入、输出、耗时和失败原因。",
        {"source": "docs/agent-runtime.md", "kind": "architecture"},
    )
    store.add_document(
        "Tool Registry 规范",
        "工具声明 description 和 parameters，并返回结构化调用摘要。Tool Call 结果会写入 Trace。",
        {"source": "docs/tool-registry.md", "kind": "tooling"},
    )
    store.add_document(
        "RAG 证据展示",
        "RAG 检索结果进入 Prompt Context。Generator 明确基于检索上下文回答，Trace 展示 retrieved chunks。",
        {"source": "docs/rag.md", "kind": "retrieval"},
    )


def _split_chunks(content: str) -> list[str]:
    chunks = [part.strip() for part in content.split("\n\n") if part.strip()]
    return chunks or [content.strip()]


def _terms(query: str) -> list[str]:
    return [term.lower() for term in findall(r"[\w\u4e00-\u9fff]+", query) if term.strip()]


def _score_chunk(chunk: DocumentChunk, terms: list[str]) -> float:
    haystack = f"{chunk.source} {chunk.content} {chunk.metadata}".lower()
    hits = sum(1 for term in terms if term in haystack)
    if hits == 0:
        return 0
    return min(0.99, 0.55 + hits * 0.12)
