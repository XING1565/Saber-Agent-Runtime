from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal


MemoryKind = Literal["history", "summary", "preference"]


@dataclass(frozen=True)
class MemoryContext:
    kind: MemoryKind
    source: str
    content: str
    metadata: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionMemory:
    session_id: str
    messages: list[dict] = field(default_factory=list)
    summary: str = ""
    preferences: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: _now_iso())


class MemoryStore:
    def __init__(self, max_history: int = 6):
        self._sessions: dict[str, SessionMemory] = {}
        self._max_history = max_history

    def context_for(self, session_id: str) -> list[MemoryContext]:
        session = self._sessions.get(session_id)
        if session is None:
            return []

        contexts: list[MemoryContext] = []
        recent_messages = session.messages[-self._max_history :]
        if recent_messages:
            history = "\n".join(f"{item['role']}: {item['content']}" for item in recent_messages)
            contexts.append(
                MemoryContext(
                    kind="history",
                    source="session_history",
                    content=history,
                    metadata={"message_count": len(recent_messages), "session_id": session_id},
                )
            )
        if session.summary:
            contexts.append(
                MemoryContext(
                    kind="summary",
                    source="rolling_summary",
                    content=session.summary,
                    metadata={"session_id": session_id},
                )
            )
        if session.preferences:
            contexts.append(
                MemoryContext(
                    kind="preference",
                    source="simple_preference",
                    content="；".join(session.preferences[-3:]),
                    metadata={"session_id": session_id, "preference_count": len(session.preferences)},
                )
            )
        return contexts

    def append_turn(self, session_id: str, user_message: str, assistant_answer: str) -> SessionMemory:
        session = self._sessions.setdefault(session_id, SessionMemory(session_id=session_id))
        session.messages.extend(
            [
                {"role": "user", "content": user_message, "created_at": _now_iso()},
                {"role": "assistant", "content": assistant_answer, "created_at": _now_iso()},
            ]
        )
        session.messages = session.messages[-self._max_history :]
        session.summary = _summarize(session.messages)
        preference = _extract_preference(user_message)
        if preference and preference not in session.preferences:
            session.preferences.append(preference)
        session.updated_at = _now_iso()
        return session

    def get_session(self, session_id: str) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            return {"session_id": session_id, "messages": [], "summary": "", "preferences": []}
        return {
            "session_id": session.session_id,
            "messages": list(session.messages),
            "summary": session.summary,
            "preferences": list(session.preferences),
            "updated_at": session.updated_at,
        }


def _summarize(messages: list[dict]) -> str:
    user_messages = [item["content"] for item in messages if item["role"] == "user"]
    if not user_messages:
        return ""
    latest = user_messages[-2:]
    return "；".join(f"用户提到：{message[:48]}" for message in latest)


def _extract_preference(message: str) -> str:
    markers = ("偏好", "喜欢", "希望", "优先")
    if any(marker in message for marker in markers):
        return message[:80]
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
