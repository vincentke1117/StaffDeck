from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class GeneralSkillImportRequest(BaseModel):
    tenant_id: str
    name: str
    slug: str
    description: Optional[str] = None
    homepage: Optional[str] = None
    markdown: str
    status: str = "published"
    original_slug: Optional[str] = None


class GeneralSkillRead(BaseModel):
    id: str
    tenant_id: str
    slug: str
    name: str
    description: Optional[str] = None
    homepage: Optional[str] = None
    skill_markdown: str
    status: str
    permissions: dict[str, Any] = Field(default_factory=dict)
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class GeneralSkillRunRequest(BaseModel):
    tenant_id: str
    user_id: str = ""
    query: str
    session_id: Optional[str] = None
    max_attempts: int = Field(default=10, ge=1, le=10)


class GeneralSkillRunResponse(BaseModel):
    skill_slug: str
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    generated_code: str = ""
    stdout: str = ""
    stderr: str = ""
    structured_result: dict[str, Any] = Field(default_factory=dict)
    reply: str


class GeneralSkillSelection(BaseModel):
    use_general_skill: bool = False
    selected_slug: Optional[str] = None
    confidence: float = 0.0
    reason: Optional[str] = None


class GeneralSkillExecutionPlan(BaseModel):
    code: str
    rationale: Optional[str] = None
    expected_output: Optional[str] = None


class GeneralSkillReply(BaseModel):
    reply: str
