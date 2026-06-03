from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from time import sleep
from typing import Any

from app.db.models import ModelConfig
from app.llm import LLMClient, LLMError
from app.skills.llm_limits import skill_model_config
from app.skills.skill_schema import SkillDistillRequest, SkillDistillResponse, SkillCard, SkillStep, ToolSuggestion
from app.skills.step_ids import ensure_unique_step_ids, skill_card_with_unique_step_ids


PROMPT_PATH = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "skill_distiller_prompt.md"
STREAM_INTERVAL_SECONDS = 0.035
CLOSED_LOOP_RESPONSE_RULE = (
    "流程必须形成闭环：不得把“请稍候/正在处理/稍后反馈”作为最终回复；"
    "需要外部事实、外部状态或外部副作用时必须调用已配置工具或转人工，并向用户给出明确结果。"
)
ADAPTIVE_FLOW_RESPONSE_RULE = (
    "步骤是可自适应推进的目标，不是固定问答脚本；已由当前用户消息、历史信息或路由意图满足的内容"
    "不得重复追问，应直接推进到下一缺失信息、工具调用或最终回复。"
)
CONFIRMATION_FLOW_RESPONSE_RULE = (
    "涉及外部系统写入、用户资产变更、不可逆操作或明确需要确认的处理时，"
    "调用工具或执行处理前必须先让用户确认关键对象、范围和操作内容。"
)
TOOL_STEP_INSTRUCTION_SUFFIX = (
    "工具参数满足时直接调用工具；工具成功后必须基于工具结果进入最终回复，"
    "不要停留在“请稍候”或“正在处理”。"
)
ADAPTIVE_STEP_INSTRUCTION_SUFFIX = (
    "将本步骤作为目标而不是固定话术；如果用户当前消息、历史 slots 或路由意图已满足本步骤，"
    "直接写入对应 slot 并继续到下一缺失信息、工具调用或最终回复，不要重复确认。"
)
class SkillDistiller:
    def distill(self, request: SkillDistillRequest, model_config: ModelConfig) -> SkillDistillResponse:
        payload = self._payload(request)
        raw = LLMClient(skill_model_config(model_config)).generate_json(PROMPT_PATH.read_text(encoding="utf-8"), payload)
        return self._normalize_response(raw, request)

    def distill_stream(self, request: SkillDistillRequest, model_config: ModelConfig) -> SkillDistillResponse:
        payload = {
            "title": request.title,
            "business_domain": request.business_domain,
            "raw_content": request.raw_content,
            "available_tools": request.available_tools,
        }
        text = "".join(
            LLMClient(skill_model_config(model_config)).generate_text_stream(
                PROMPT_PATH.read_text(encoding="utf-8"), payload
            )
        )
        return self._normalize_response(json.loads(_extract_json(text)), request)

    def stream_text(self, request: SkillDistillRequest, model_config: ModelConfig):
        payload = self._payload(request)
        chunks: list[str] = []
        try:
            yield {"event": "status", "data": {"text": "模型正在规划技能结构"}}
            for chunk in LLMClient(skill_model_config(model_config)).generate_text_stream(
                PROMPT_PATH.read_text(encoding="utf-8"), payload
            ):
                chunks.append(chunk)
                yield {"event": "chunk", "data": {"content": chunk}}
            yield {"event": "status", "data": {"text": "正在校验模型输出结构"}}
            response = self._normalize_response(json.loads(_extract_json("".join(chunks))), request)
        except (LLMError, json.JSONDecodeError, ValueError) as exc:
            yield {"event": "status", "data": {"text": "模型输出需修复，正在生成可用草稿"}}
            response = self._fallback_response(request, f"模型输出未能直接解析，已使用规则兜底生成：{exc}")
            for chunk in _chunk_text(json.dumps(response.draft_skill.model_dump(), ensure_ascii=False, indent=2)):
                yield {"event": "chunk", "data": {"content": chunk}}
                sleep(STREAM_INTERVAL_SECONDS)
        yield {"event": "status", "data": {"text": "已完成 Skill Card 结构化"}}
        yield {"event": "complete", "data": response.model_dump(mode="json")}

    def _payload(self, request: SkillDistillRequest) -> dict[str, Any]:
        return {
            "title": request.title,
            "business_domain": request.business_domain,
            "raw_content": request.raw_content,
            "available_tools": request.available_tools,
        }

    def _normalize_response(self, raw: dict[str, Any], request: SkillDistillRequest) -> SkillDistillResponse:
        draft = raw.get("draft_skill") if isinstance(raw.get("draft_skill"), dict) else raw
        warnings = list(raw.get("warnings") or [])
        fallback = self._fallback_card(request)

        required_info = _string_list(draft.get("required_info"), fallback.required_info)
        steps = self._normalize_steps(draft.get("steps"), fallback.steps)
        steps, step_warnings = self._ensure_closed_loop_steps(steps, request)
        warnings.extend(step_warnings)
        steps, unique_step_warnings = ensure_unique_step_ids(steps)
        warnings.extend(unique_step_warnings)
        steps, missing_tool_names = _remove_unknown_tool_actions(steps, request.available_tools)
        for tool_name in missing_tool_names:
            warnings.append(f"技能草稿引用了未配置工具 {tool_name}，已移出 allowed_actions 并生成新增工具建议。")
        response_rules = _string_list(draft.get("response_rules"), fallback.response_rules)
        if CLOSED_LOOP_RESPONSE_RULE not in response_rules:
            response_rules.append(CLOSED_LOOP_RESPONSE_RULE)
        if ADAPTIVE_FLOW_RESPONSE_RULE not in response_rules:
            response_rules.append(ADAPTIVE_FLOW_RESPONSE_RULE)
        if _steps_declare_confirmation(steps) and CONFIRMATION_FLOW_RESPONSE_RULE not in response_rules:
            response_rules.append(CONFIRMATION_FLOW_RESPONSE_RULE)
        normalized = {
            "skill_id": _string(draft.get("skill_id"), fallback.skill_id),
            "name": _string(draft.get("name"), fallback.name),
            "version": _string(draft.get("version"), "1.0.0"),
            "business_domain": _string(draft.get("business_domain"), fallback.business_domain or "general"),
            "description": _string(draft.get("description"), fallback.description),
            "trigger_intents": _string_list(draft.get("trigger_intents"), fallback.trigger_intents),
            "user_utterance_examples": _string_list(
                draft.get("user_utterance_examples"), fallback.user_utterance_examples
            ),
            "goal": _string_list(draft.get("goal"), fallback.goal),
            "required_info": required_info,
            "slot_filling_policy": _slot_filling_policy(
                draft.get("slot_filling_policy"),
                required_info,
                steps,
                fallback.slot_filling_policy,
            ),
            "response_rules": response_rules,
            "steps": steps,
            "interruption_policy": _string_dict(draft.get("interruption_policy"), fallback.interruption_policy),
        }
        draft_skill, card_warnings = skill_card_with_unique_step_ids(SkillCard.model_validate(normalized))
        warnings.extend(card_warnings)
        tool_suggestions = _normalize_tool_suggestions(raw.get("tool_suggestions"), request, missing_tool_names)
        response = SkillDistillResponse(
            draft_skill=draft_skill,
            warnings=_compact_warnings(warnings),
            tool_suggestions=tool_suggestions,
        )
        if not response.draft_skill.steps:
            response.draft_skill.steps = fallback.steps
            response.warnings = _compact_warnings([*response.warnings, "模型未生成步骤，已使用规则生成默认步骤。"])
        return response

    def _ensure_closed_loop_steps(
        self, steps: list[dict[str, Any]], request: SkillDistillRequest
    ) -> tuple[list[dict[str, Any]], list[str]]:
        normalized_steps = [dict(step) for step in steps]
        warnings: list[str] = []
        _attach_declared_confirmation_to_tool_steps(normalized_steps)

        for step in normalized_steps:
            _ensure_adaptive_step_instruction(step)
            actions = [str(action) for action in step.get("allowed_actions", [])]
            if not any(action.startswith("call_tool:") for action in actions):
                continue
            if "continue_flow" not in actions:
                actions.append("continue_flow")
                step["allowed_actions"] = actions
            instruction = str(step.get("instruction") or "")
            if "工具成功后" not in instruction:
                step["instruction"] = f"{instruction}{TOOL_STEP_INSTRUCTION_SUFFIX}"

        if not _last_step_allows_answer(normalized_steps):
            normalized_steps.append(
                {
                    "step_id": _unique_step_id(normalized_steps, "reply_final_result"),
                    "name": "反馈最终结果",
                    "instruction": (
                        "基于已收集信息和工具结果给用户明确最终回复；"
                        "信息不足时追问缺失信息，无法闭环时转人工，不要只说请稍候；"
                        f"{ADAPTIVE_STEP_INSTRUCTION_SUFFIX}"
                    ),
                    "expected_user_info": [],
                    "allowed_actions": ["answer_user", "handoff_human"],
                }
            )
            warnings.append("原始改写缺少最终回复步骤，已补充闭环反馈步骤。")
        else:
            last_step = normalized_steps[-1]
            instruction = str(last_step.get("instruction") or "")
            if "明确" not in instruction or "请稍候" in instruction:
                last_step["instruction"] = (
                    f"{instruction}给用户明确最终回复；无法闭环时转人工，不要只说请稍候。"
                )

        return normalized_steps, warnings

    def _normalize_steps(self, value: Any, fallback_steps: list[SkillStep]) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return [step.model_dump() for step in fallback_steps]
        steps: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            fallback = fallback_steps[min(index, len(fallback_steps) - 1)]
            steps.append(
                {
                    "step_id": _string(item.get("step_id"), fallback.step_id),
                    "name": _string(item.get("name"), fallback.name),
                    "instruction": _string(item.get("instruction"), fallback.instruction),
                    "expected_user_info": _string_list(
                        item.get("expected_user_info"), fallback.expected_user_info
                    ),
                    "allowed_actions": _normalize_actions(
                        _string_list(item.get("allowed_actions"), fallback.allowed_actions)
                    ),
                }
            )
        return steps or [step.model_dump() for step in fallback_steps]

    def _fallback_response(self, request: SkillDistillRequest, warning: str) -> SkillDistillResponse:
        return SkillDistillResponse(draft_skill=self._fallback_card(request), warnings=_compact_warnings([warning]))

    def _fallback_card(self, request: SkillDistillRequest) -> SkillCard:
        title = request.title.strip() or "新技能"
        raw = request.raw_content
        required_info: list[str] = []
        steps: list[SkillStep] = []
        steps.append(
            SkillStep(
                step_id="understand_request",
                name="理解原始流程",
                instruction=(
                    "根据原始流程文档理解用户目标、缺失信息和下一步处理方式；"
                    "不要基于固定话术推进，信息不足时追问，涉及外部事实或外部副作用时转人工或等待人工补充工具配置；"
                    f"{ADAPTIVE_STEP_INSTRUCTION_SUFFIX}"
                ),
                expected_user_info=[],
                allowed_actions=["ask_user", "continue_flow", "handoff_human"],
            )
        )
        steps.append(
            SkillStep(
                step_id="reply_result",
                name="反馈结果",
                instruction=(
                    "根据已收集的信息和工具结果给用户明确回复；信息不足时继续追问，不要编造事实；"
                    f"{ADAPTIVE_STEP_INSTRUCTION_SUFFIX}"
                ),
                expected_user_info=[],
                allowed_actions=["answer_user", "handoff_human"],
            )
        )
        return SkillCard(
            skill_id=_slugify(title, raw),
            name=title,
            version="1.0.0",
            business_domain=request.business_domain or "general",
            description=raw[:120] or "根据原始技能文本生成的流程。",
            trigger_intents=[title],
            user_utterance_examples=[title],
            goal=_infer_goals(raw),
            required_info=required_info,
            slot_filling_policy=_default_slot_filling_policy(required_info),
            response_rules=[
                "信息不足时先追问，不要编造事实。",
                ADAPTIVE_FLOW_RESPONSE_RULE,
            ],
            steps=steps,
            interruption_policy={
                "related_question": "回答相关问题后回到当前流程。",
                "unrelated_business": "可切换新流程并保留当前进度。",
                "chitchat": "简短回应后引导用户继续当前流程。",
                "user_wants_human": "直接转人工。",
            },
        )


def _steps_have_tool_action(steps: list[dict[str, Any]]) -> bool:
    for step in steps:
        actions = step.get("allowed_actions", [])
        if isinstance(actions, list) and any(str(action).startswith("call_tool:") for action in actions):
            return True
    return False


def _ensure_adaptive_step_instruction(step: dict[str, Any]) -> None:
    instruction = str(step.get("instruction") or "")
    if "目标而不是固定话术" in instruction or "不是固定问答脚本" in instruction:
        return
    step["instruction"] = f"{instruction}{ADAPTIVE_STEP_INSTRUCTION_SUFFIX}"


def _confirmation_fields(steps: list[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    for step in steps:
        expected = [str(field) for field in step.get("expected_user_info", [])]
        for field in expected:
            if field.endswith("_confirmed") and field not in fields:
                fields.append(field)
    return fields


def _steps_declare_confirmation(steps: list[dict[str, Any]]) -> bool:
    return bool(_confirmation_fields(steps))


def _attach_declared_confirmation_to_tool_steps(steps: list[dict[str, Any]]) -> None:
    confirmed_fields: list[str] = []
    for step in steps:
        if any(str(action).startswith("call_tool:") for action in step.get("allowed_actions", [])):
            _append_tool_confirmation_instruction(step, confirmed_fields)
        for field in _confirmation_fields([step]):
            if field not in confirmed_fields:
                confirmed_fields.append(field)


def _append_tool_confirmation_instruction(step: dict[str, Any], confirmation_fields: list[str]) -> None:
    if not confirmation_fields:
        return
    instruction = str(step.get("instruction") or "")
    if "确认字段" in instruction or "confirmed=true" in instruction:
        return
    field_text = "、".join(f"{field}=true" for field in confirmation_fields)
    step["instruction"] = f"{instruction}调用工具前必须确认字段已满足：{field_text}。"


def _last_step_allows_answer(steps: list[dict[str, Any]]) -> bool:
    if not steps:
        return False
    actions = [str(action) for action in steps[-1].get("allowed_actions", [])]
    return "answer_user" in actions or "reply" in actions


def _unique_step_id(steps: list[dict[str, Any]], base: str) -> str:
    existing = {str(step.get("step_id") or "") for step in steps}
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _unique_warnings(warnings: list[str]) -> list[str]:
    deduped: list[str] = []
    for warning in warnings:
        text = str(warning).strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _compact_warnings(warnings: list[str]) -> list[str]:
    return _unique_warnings([_compact_warning(str(warning)) for warning in warnings if str(warning).strip()])


def _compact_warning(warning: str) -> str:
    text = warning.strip()
    tool_name = _warning_tool_name(text)
    if tool_name and (
        "未配置工具" in text
        or "available_tools" in text
        or "tool_suggestions" in text
        or "allowed_actions" in text
    ):
        return f"未配置工具 {tool_name}，已生成新增建议。"
    if "没有任何工具支持" in text or ("available_tools" in text and "工具" in text):
        return "缺少可用工具，需先新增工具后再执行该流程。"
    replacements = (
        ("原始改写未包含工具步骤，已按可用工具补充闭环执行步骤。", "已补充工具执行步骤。"),
        ("原始改写缺少执行前确认步骤，已补充确认步骤。", "已补充执行前确认步骤。"),
        ("原始改写缺少最终回复步骤，已补充闭环反馈步骤。", "已补充最终回复步骤。"),
        ("模型未生成步骤，已使用规则生成默认步骤。", "已生成默认步骤。"),
    )
    for source, target in replacements:
        if text == source:
            return target
    return text


def _warning_tool_name(text: str) -> str:
    patterns = (
        r"未配置工具\s+`?([A-Za-z0-9_.:-]+)`?",
        r"工具\s+`?([A-Za-z0-9_.:-]+)`?\s+不在",
        r"引用了未配置工具\s+`?([A-Za-z0-9_.:-]+)`?",
        r"提到了工具\s+`?([A-Za-z0-9_.:-]+)`?",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip("`，。,. ")
    return ""


def _request_text(request: Any) -> str:
    return f"{_request_title(request)}\n{_request_raw_content(request)}"


def _request_title(request: Any) -> str:
    title = getattr(request, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()
    current_skill = getattr(request, "current_skill", None)
    name = getattr(current_skill, "name", None)
    return str(name or "新技能").strip()


def _request_raw_content(request: Any) -> str:
    raw_content = getattr(request, "raw_content", None)
    if isinstance(raw_content, str) and raw_content.strip():
        return raw_content
    instruction = getattr(request, "instruction", None)
    return str(instruction or "")


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


def _chunk_text(text: str, size: int = 18):
    for index in range(0, len(text), size):
        yield text[index : index + size]


def _string(value: Any, fallback: str | None = "") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback or ""


def _string_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return items
    return fallback


def _string_dict(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if isinstance(value, dict):
        items = {str(key): str(item) for key, item in value.items() if str(key)}
        if items:
            return items
    return fallback


def _slot_filling_policy(
    value: Any,
    required_info: list[str],
    steps: list[dict[str, Any]],
    fallback_policy: dict[str, Any],
) -> dict[str, Any]:
    has_explicit_policy = isinstance(value, dict)
    if has_explicit_policy:
        policy = dict(value)
    else:
        policy = dict(fallback_policy or {})
    expected_infos = set(required_info)
    for step in steps:
        expected_infos.update(str(field) for field in step.get("expected_user_info", []))
    if has_explicit_policy and isinstance(policy.get("target_info"), list):
        expected_infos.update(str(field) for field in policy["target_info"] if str(field).strip())
    default_policy = _default_slot_filling_policy(sorted(expected_infos))
    return {
        **default_policy,
        **policy,
        "enabled": True,
        "multi_slot_per_turn": True,
        "extract_scope": "all_skill_expected_user_info",
        "skip_satisfied_steps": True,
        "target_info": sorted(expected_infos),
    }


def _default_slot_filling_policy(expected_infos: list[str]) -> dict[str, Any]:
    return {
        "enabled": True,
        "multi_slot_per_turn": True,
        "extract_scope": "all_skill_expected_user_info",
        "skip_satisfied_steps": True,
        "description": "每轮用户消息都应同时抽取所有可识别的信息；如果用户一次提供多个字段，必须一次性写入 slot_updates，不要按步骤重复追问。",
        "target_info": expected_infos,
    }


def _normalize_actions(actions: list[str]) -> list[str]:
    aliases = {
        "ask_for_info": "ask_user",
        "ask": "ask_user",
        "reply": "answer_user",
        "respond": "answer_user",
    }
    normalized: list[str] = []
    for action in actions:
        value = aliases.get(action, action)
        if value not in normalized:
            normalized.append(value)
    return normalized


def _available_tool_names(available_tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in available_tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def _remove_unknown_tool_actions(
    steps: list[dict[str, Any]], available_tools: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    available_names = _available_tool_names(available_tools)
    missing_names: list[str] = []
    if not available_names:
        available_names = set()
    normalized_steps: list[dict[str, Any]] = []
    for step in steps:
        next_step = dict(step)
        actions = []
        for action in next_step.get("allowed_actions", []):
            action_text = str(action)
            if not action_text.startswith("call_tool:"):
                actions.append(action_text)
                continue
            tool_name = action_text.replace("call_tool:", "", 1).strip()
            if tool_name in available_names:
                actions.append(action_text)
                continue
            if tool_name and tool_name not in missing_names:
                missing_names.append(tool_name)
        next_step["allowed_actions"] = actions
        normalized_steps.append(next_step)
    return normalized_steps, missing_names


def _normalize_tool_suggestions(
    value: Any, request: Any, missing_tool_names: list[str]
) -> list[ToolSuggestion]:
    suggestions: list[ToolSuggestion] = []
    seen = set(_available_tool_names(request.available_tools))

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            suggestion = _tool_suggestion_from_dict(item, request)
            if suggestion.name in seen:
                continue
            suggestions.append(suggestion)
            seen.add(suggestion.name)

    for name in missing_tool_names:
        if name in seen:
            continue
        suggestion = _default_tool_suggestion(name, request, f"模型草稿引用了未配置工具 {name}。")
        suggestions.append(suggestion)
        seen.add(name)

    for name in _mentioned_tool_names(_request_text(request)):
        if name in seen:
            continue
        suggestion = _default_tool_suggestion(name, request, f"原始输入提到了工具 {name}，但当前工具配置中不存在。")
        suggestions.append(suggestion)
        seen.add(name)

    return suggestions


def _tool_suggestion_from_dict(item: dict[str, Any], request: Any) -> ToolSuggestion:
    name = _string(item.get("name"), "")
    if not name:
        name = f"{_slugify(_request_title(request), _request_raw_content(request))}.execute"
    default = _default_tool_suggestion(name, request, _string(item.get("reason"), "模型建议新增该工具。"))
    return ToolSuggestion(
        name=name,
        display_name=_string(item.get("display_name"), default.display_name or name),
        description=_string(item.get("description"), default.description or ""),
        method=_tool_method(item.get("method"), default.method),
        url=_string(item.get("url"), default.url),
        input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else default.input_schema,
        output_schema=item.get("output_schema") if isinstance(item.get("output_schema"), dict) else default.output_schema,
        reason=_string(item.get("reason"), default.reason),
    )


def _default_tool_suggestion(name: str, request: Any, reason: str) -> ToolSuggestion:
    title = _request_title(request)
    properties = {"query": {"type": "string", "description": "用户请求或业务对象"}}
    return ToolSuggestion(
        name=name,
        display_name=f"{title or name}工具",
        description=f"用于支撑「{title or name}」流程中的外部查询、核实、创建或处理动作。",
        method="POST",
        url=f"/api/mock/{name.replace('.', '/')}",
        input_schema={"type": "object", "properties": properties, "required": list(properties.keys())},
        output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "data": {"type": "object"}}},
        reason=reason,
    )


def _mentioned_tool_names(text: str) -> list[str]:
    names: list[str] = []
    patterns = [
        r"(?:call_tool:|工具[:：]\s*|调用\s*|使用\s*|tool\s*[:=]\s*)([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)",
        r"`([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)`",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            name = match.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names


def _tool_method(value: Any, fallback: str = "POST") -> str:
    method = str(value or fallback or "POST").upper()
    return method if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} else "POST"


def _infer_goals(raw: str) -> list[str]:
    clauses = [clause.strip() for clause in _split_clauses(raw) if clause.strip()]
    return clauses or ["理解用户诉求", "收集必要信息", "完成流程处理", "向用户反馈结果"]


def _split_clauses(text: str) -> list[str]:
    normalized = text.replace("\n", "，").replace("；", "，").replace(";", "，").replace(",", "，").replace("。", "，")
    return [part.strip() for part in normalized.split("，")]


def _slugify(title: str, raw: str) -> str:
    ascii_slug = "".join(char.lower() if char.isalnum() else "_" for char in title if ord(char) < 128)
    ascii_slug = "_".join(part for part in ascii_slug.split("_") if part)
    if ascii_slug:
        return ascii_slug[:48]
    digest = hashlib.md5(f"{title}:{raw}".encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"skill_{digest}"
