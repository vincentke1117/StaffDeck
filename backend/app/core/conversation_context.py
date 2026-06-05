from __future__ import annotations

from typing import Any


DEFAULT_CONTEXT_TOKEN_BUDGET = 16_000
SUMMARY_TOKEN_BUDGET = 1_200
ALLOWED_CONTEXT_ROLES = {"system", "user", "assistant"}


def build_conversation_context(
    messages: list[dict[str, Any]],
    token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
) -> dict[str, object]:
    normalized = _normalize_messages(messages)
    if _messages_tokens(normalized) <= token_budget:
        return _context_payload(normalized, normalized, [], "", token_budget)

    summary_budget = min(SUMMARY_TOKEN_BUDGET, max(1, token_budget // 4))
    recent_budget = max(1, token_budget - summary_budget)
    recent = _fit_recent_messages(normalized, recent_budget)
    omitted_count = len(normalized) - len(recent)
    omitted = normalized[:omitted_count]
    summary = _compact_messages(omitted, summary_budget)
    projected = [{"role": "system", "content": f"Compacted earlier conversation:\n{summary}"}, *recent]

    while len(projected) > 1 and _messages_tokens(projected) > token_budget:
        projected.pop(1)
    if _messages_tokens(projected) > token_budget:
        projected = [_trim_message(projected[0], token_budget)]

    return _context_payload(projected, normalized, omitted, summary, token_budget)


def _context_payload(
    projected: list[dict[str, str]],
    original: list[dict[str, str]],
    omitted: list[dict[str, str]],
    summary: str,
    token_budget: int,
) -> dict[str, object]:
    return {
        "messages": projected,
        "compacted_summary": summary,
        "metadata": {
            "token_budget": token_budget,
            "estimated_tokens": _messages_tokens(projected),
            "total_messages": len(original),
            "included_messages": len(projected),
            "omitted_messages": len(omitted),
            "compacted": bool(omitted),
        },
    }


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if role not in ALLOWED_CONTEXT_ROLES or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _fit_recent_messages(messages: list[dict[str, str]], token_budget: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    used = 0
    for message in reversed(messages):
        cost = _message_tokens(message)
        if selected and used + cost > token_budget:
            break
        if cost > token_budget:
            selected.append(_trim_message(message, token_budget))
            break
        selected.append(message)
        used += cost
    selected.reverse()
    return selected


def _compact_messages(messages: list[dict[str, str]], token_budget: int) -> str:
    if not messages:
        return ""
    lines: list[str] = []
    used = 0
    for index, message in enumerate(messages, start=1):
        line = f"{index}. {message['role']}: {_compact_content(message['content'])}"
        cost = _estimate_tokens(line)
        if lines and used + cost > token_budget:
            break
        if cost > token_budget:
            available_chars = max(24, token_budget - used)
            line = line[:available_chars].rstrip() + "..."
            lines.append(line)
            break
        lines.append(line)
        used += cost
    remaining = len(messages) - len(lines)
    if remaining > 0:
        lines.append(f"... {remaining} earlier messages omitted after compaction.")
    return "\n".join(lines)


def _compact_content(content: str, max_chars: int = 320) -> str:
    single_line = " ".join(content.split())
    if len(single_line) <= max_chars:
        return single_line
    return single_line[:max_chars].rstrip() + "..."


def _trim_message(message: dict[str, str], token_budget: int) -> dict[str, str]:
    content_budget = max(1, token_budget - _estimate_tokens(message["role"]) - 4)
    content = message["content"]
    if _estimate_tokens(content) <= content_budget:
        return message
    return {"role": message["role"], "content": content[:content_budget].rstrip() + "..."}


def _messages_tokens(messages: list[dict[str, str]]) -> int:
    return sum(_message_tokens(message) for message in messages)


def _message_tokens(message: dict[str, str]) -> int:
    return _estimate_tokens(message["role"]) + _estimate_tokens(message["content"]) + 6


def _estimate_tokens(text: str) -> int:
    return max(1, len(text))
