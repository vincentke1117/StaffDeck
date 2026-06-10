from __future__ import annotations

from collections.abc import Iterator
import copy
import json
from typing import Any

from openai import OpenAI

from app.db.models import ModelConfig
from app.security.encryption import decrypt_secret


class LLMError(Exception):
    """Raised when an LLM provider request or response normalization fails."""


JSON_REPAIR_ATTEMPTS = 3


class LLMClient:
    def __init__(self, model_config: ModelConfig):
        api_key = decrypt_secret(model_config.api_key_encrypted)
        if not api_key:
            raise LLMError("Model API key is not configured")
        self.client = OpenAI(api_key=api_key, base_url=model_config.base_url)
        self.model = model_config.model
        self.temperature = model_config.temperature
        self.max_output_tokens = model_config.max_output_tokens

    def generate_text(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_format: dict[str, str] | None = None,
    ) -> str:
        context_messages, serialized_payload = _project_context_messages(user_payload)
        serialized = json.dumps(serialized_payload, ensure_ascii=False)
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    *context_messages,
                    {"role": "user", "content": serialized},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_output_tokens,
            }
            if response_format:
                request["response_format"] = response_format
            completion = self.client.chat.completions.create(
                **request,
            )
            content = completion.choices[0].message.content
            if not content:
                raise LLMError("Model returned an empty response")
            return content
        except Exception as exc:
            if isinstance(exc, LLMError):
                raise
            raise LLMError(str(exc)) from exc

    def generate_text_stream(self, system_prompt: str, user_payload: dict[str, Any]) -> Iterator[str]:
        context_messages, serialized_payload = _project_context_messages(user_payload)
        serialized = json.dumps(serialized_payload, ensure_ascii=False)
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *context_messages,
                    {"role": "user", "content": serialized},
                ],
                temperature=self.temperature,
                max_tokens=self.max_output_tokens,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    yield content
        except Exception as exc:
            raise LLMError(str(exc)) from exc

    def generate_json(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        outputs: list[str] = []
        next_payload = user_payload
        last_error: json.JSONDecodeError | None = None
        json_mode_supported = True
        for attempt in range(JSON_REPAIR_ATTEMPTS + 1):
            text = self._generate_json_candidate(system_prompt, next_payload, json_mode_supported)
            if json_mode_supported and _response_format_unsupported(text):
                json_mode_supported = False
                text = self.generate_text(system_prompt, next_payload)
            outputs.append(text)
            try:
                return json.loads(_extract_json(text))
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt >= JSON_REPAIR_ATTEMPTS:
                    break
                next_payload = copy.deepcopy(user_payload)
                next_payload["_json_repair"] = {
                    "attempt": attempt + 1,
                    "max_attempts": JSON_REPAIR_ATTEMPTS,
                    "previous_output": _preview(text),
                    "parser_error": str(exc),
                    "instruction": (
                        "上一轮输出不是合法 JSON。请基于原始任务上下文重新输出完整、可解析的 JSON object。"
                        "字符串内部的双引号必须转义；不要输出 Markdown、解释、代码块或额外文本。"
                    ),
                }
        previews = "; ".join(f"attempt_{index + 1}_preview={_preview(output)!r}" for index, output in enumerate(outputs))
        raise LLMError(
            f"Model did not return valid JSON after {JSON_REPAIR_ATTEMPTS} repair attempts; {previews}"
        ) from last_error

    def _generate_json_candidate(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        json_mode_supported: bool,
    ) -> str:
        if not json_mode_supported:
            return self.generate_text(system_prompt, user_payload)
        try:
            return self.generate_text(
                system_prompt,
                user_payload,
                response_format={"type": "json_object"},
            )
        except TypeError:
            return self.generate_text(system_prompt, user_payload)
        except LLMError as exc:
            message = str(exc)
            if _response_format_unsupported(message):
                return message
            raise


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        return stripped[start : end + 1]
    return stripped


def _preview(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"


def _response_format_unsupported(message: str) -> bool:
    lowered = message.lower()
    return "response_format" in lowered and any(
        phrase in lowered
        for phrase in (
            "unsupported",
            "not support",
            "not_supported",
            "unknown parameter",
            "unrecognized",
            "extra inputs are not permitted",
            "invalid parameter",
        )
    )


def _project_context_messages(user_payload: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    payload = copy.deepcopy(user_payload)
    context = payload.get("conversation_context")
    if not isinstance(context, dict):
        return [], payload
    messages = context.pop("messages", [])
    if not isinstance(messages, list):
        return [], payload
    projected: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if role not in {"system", "user", "assistant"} or not content:
            continue
        projected.append({"role": role, "content": content})
    return projected, payload
