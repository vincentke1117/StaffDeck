from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.models import ChatSession, ModelConfig, Skill
from app.llm import LLMClient, LLMError
from app.session.helpers import public_session
from app.session.session_schema import RouterDecision


PROMPT_PATH = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "router_prompt.md"


class Router:
    def decide(
        self,
        message: str,
        session: ChatSession,
        available_skills: list[Skill],
        model_config: ModelConfig,
        conversation_context: dict[str, object] | None = None,
    ) -> RouterDecision:
        payload = {
            "user_message": message,
            "conversation_context": conversation_context or {},
            "current_session": public_session(session).model_dump(),
            "available_skills": [
                {
                    "skill_id": skill.skill_id,
                    "name": skill.name,
                    "description": skill.description,
                    "business_domain": skill.content_json.get("business_domain"),
                    "trigger_intents": skill.content_json.get("trigger_intents", []),
                    "required_info": skill.content_json.get("required_info", []),
                    "steps": [
                        {
                            "step_id": step.get("step_id"),
                            "name": step.get("name"),
                            "instruction": step.get("instruction"),
                            "expected_user_info": step.get("expected_user_info", []),
                            "allowed_actions": step.get("allowed_actions", []),
                        }
                        for step in skill.content_json.get("steps", [])
                        if isinstance(step, dict)
                    ],
                }
                for skill in available_skills
            ],
        }
        try:
            raw = LLMClient(model_config).generate_json(PROMPT_PATH.read_text(encoding="utf-8"), payload)
            decision = RouterDecision.model_validate(raw)
        except Exception as exc:
            if isinstance(exc, LLMError):
                raise
            raise LLMError(f"Router returned invalid JSON schema: {exc}") from exc
        return self._normalize_decision(decision, session, available_skills)

    def _normalize_decision(
        self, decision: RouterDecision, session: ChatSession, available_skills: list[Skill]
    ) -> RouterDecision:
        skills = {skill.skill_id: skill for skill in available_skills}
        if decision.decision in {"start_skill", "suspend_current_and_start_new_skill"}:
            if not decision.target_skill_id or decision.target_skill_id not in skills:
                decision.decision = "clarify"
                decision.clarification_question = "请问您想办理哪类业务？"
                return decision
        if not decision.target_skill_id and session.active_skill_id:
            decision.target_skill_id = session.active_skill_id
        if decision.target_skill_id and not decision.target_step_id:
            target_skill = skills.get(decision.target_skill_id)
            steps: list[dict[str, Any]] = target_skill.content_json.get("steps", []) if target_skill else []
            if steps:
                decision.target_step_id = steps[0].get("step_id")
        normalized_tasks = []
        for task in decision.pending_tasks:
            if not task.target_skill_id or task.target_skill_id not in skills:
                continue
            if not task.target_step_id:
                target_skill = skills.get(task.target_skill_id)
                steps = target_skill.content_json.get("steps", []) if target_skill else []
                if steps:
                    task.target_step_id = steps[0].get("step_id")
            normalized_tasks.append(task)
        decision.pending_tasks = normalized_tasks
        return decision
