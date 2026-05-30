from __future__ import annotations

from typing import Any

from app.skills.skill_schema import SkillCard


def skill_card_with_unique_step_ids(card: SkillCard) -> tuple[SkillCard, list[str]]:
    content = card.model_dump(mode="json")
    steps, warnings = ensure_unique_step_ids(content.get("steps", []))
    content["steps"] = steps
    return SkillCard.model_validate(content), warnings


def ensure_unique_step_ids(steps: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    used: set[str] = set()
    normalized_steps: list[dict[str, Any]] = []
    changed = False
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            continue
        step = dict(raw_step)
        original = str(step.get("step_id") or "").strip()
        base = original or f"step_{index + 1}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        if candidate != original:
            changed = True
            step["step_id"] = candidate
        else:
            step["step_id"] = original
        used.add(candidate)
        normalized_steps.append(step)
    warnings = ["检测到重复或空 step_id，已自动修正为唯一 ID。"] if changed else []
    return normalized_steps, warnings
