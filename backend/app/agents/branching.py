from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlmodel import Session, select

from app.db.models import (
    AgentKnowledgeBranch,
    AgentModelBinding,
    AgentProfile,
    AgentResourceBinding,
    AgentSkillBranch,
    AgentSkillBranchVersion,
    KnowledgeBase,
    KnowledgeBaseVersion,
    KnowledgeBucket,
    KnowledgeChunk,
    KnowledgeDiscoverySuggestion,
    KnowledgeDocument,
    ModelConfig,
    Skill,
    SkillVersion,
    utc_now,
)


DEFAULT_AGENT_ROLES = ("default", "router", "step", "response", "general_skill")


def get_overall_agent(db: Session, tenant_id: str) -> AgentProfile | None:
    return db.exec(
        select(AgentProfile).where(
            AgentProfile.tenant_id == tenant_id,
            AgentProfile.is_overall == True,  # noqa: E712
            AgentProfile.status != "archived",
        )
    ).first()


def get_agent(db: Session, tenant_id: str, agent_id: str | None) -> AgentProfile | None:
    if not agent_id:
        return None
    return db.exec(
        select(AgentProfile).where(
            AgentProfile.tenant_id == tenant_id,
            AgentProfile.id == agent_id,
            AgentProfile.status != "archived",
        )
    ).first()


def is_overall_agent(db: Session, tenant_id: str, agent_id: str | None) -> bool:
    agent = get_agent(db, tenant_id, agent_id)
    return bool(agent and agent.is_overall)


def require_overall_agent(db: Session, tenant_id: str, agent_id: str | None) -> None:
    if not agent_id and not get_overall_agent(db, tenant_id):
        return
    if not is_overall_agent(db, tenant_id, agent_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Only the overall agent can delete global resources")


def project_skill_with_branch(
    skill: Skill,
    branch: AgentSkillBranch | None,
    binding_status: str | None = None,
) -> Skill:
    if not branch:
        return skill
    content = dict(branch.content_json or {})
    content["version"] = branch.head_version
    is_visible = branch.status == "active" and (binding_status in {None, "active"})
    metadata = {
        "agent_id": branch.agent_id,
        "base_version": branch.base_version,
        "head_version": branch.head_version,
        "sync_state": branch.sync_state,
        "status": branch.status,
        "binding_status": binding_status,
    }
    projected = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        skill_id=skill.skill_id,
        version=branch.head_version,
        name=str(branch.content_json.get("name") or skill.name),
        business_domain=branch.content_json.get("business_domain") or skill.business_domain,
        description=branch.content_json.get("description") or skill.description,
        content_json=content,
        status="published" if is_visible else "archived",
        created_at=skill.created_at,
        updated_at=branch.updated_at,
    )
    object.__setattr__(projected, "agent_branch_meta", metadata)
    return projected


def visible_skill_rows(
    db: Session,
    tenant_id: str,
    agent_id: str | None = None,
    include_inactive: bool = True,
) -> list[Skill]:
    agent = get_agent(db, tenant_id, agent_id)
    if not agent or agent.is_overall:
        status_clause = Skill.status != "deleted" if include_inactive else Skill.status == "published"
        return list(
            db.exec(
                select(Skill)
                .where(Skill.tenant_id == tenant_id, status_clause)
                .order_by(Skill.updated_at.desc())
            ).all()
        )
    rows: list[Skill] = []
    bindings = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == tenant_id,
            AgentResourceBinding.agent_id == agent.id,
            AgentResourceBinding.resource_type == "skill",
        )
    ).all()
    for binding in bindings:
        if not include_inactive and binding.status != "active":
            continue
        skill = db.get(Skill, binding.resource_id)
        if not skill or skill.tenant_id != tenant_id:
            continue
        branch = ensure_agent_skill_branch(db, tenant_id, agent.id, skill)
        if not include_inactive and branch.status != "active":
            continue
        rows.append(project_skill_with_branch(skill, branch, binding.status))
    return sorted(rows, key=lambda item: item.updated_at, reverse=True)


def visible_published_skills(db: Session, tenant_id: str, agent_id: str | None = None) -> list[Skill]:
    return [skill for skill in visible_skill_rows(db, tenant_id, agent_id) if skill.status == "published"]


def visible_skill(db: Session, tenant_id: str, skill_id: str, agent_id: str | None = None) -> Skill | None:
    skill = db.exec(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.skill_id == skill_id)
    ).first()
    if not skill or skill.status == "archived":
        return None
    agent = get_agent(db, tenant_id, agent_id)
    if not agent or agent.is_overall:
        return skill
    binding = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == tenant_id,
            AgentResourceBinding.agent_id == agent.id,
            AgentResourceBinding.resource_type == "skill",
            AgentResourceBinding.resource_id == skill.id,
            AgentResourceBinding.status == "active",
        )
    ).first()
    if not binding:
        return None
    branch = ensure_agent_skill_branch(db, tenant_id, agent.id, skill)
    if branch.status != "active":
        return None
    return project_skill_with_branch(skill, branch)


def ensure_agent_skill_branch(
    db: Session,
    tenant_id: str,
    agent_id: str,
    skill: Skill,
) -> AgentSkillBranch:
    branch = db.exec(
        select(AgentSkillBranch).where(
            AgentSkillBranch.tenant_id == tenant_id,
            AgentSkillBranch.agent_id == agent_id,
            AgentSkillBranch.skill_id == skill.skill_id,
        )
    ).first()
    if branch:
        return branch
    branch = AgentSkillBranch(
        tenant_id=tenant_id,
        agent_id=agent_id,
        skill_id=skill.skill_id,
        source_skill_id=skill.id,
        base_version=skill.version,
        head_version=skill.version,
        content_json=dict(skill.content_json),
        status="active" if skill.status == "published" else "inactive",
        sync_state="synced",
    )
    db.add(branch)
    db.flush()
    _ensure_branch_version(db, branch, "初始化分支")
    return branch


def update_branch_skill(
    db: Session,
    tenant_id: str,
    agent_id: str,
    skill: Skill,
    content: dict[str, Any],
    change_summary: str = "分支改写",
) -> AgentSkillBranch:
    branch = ensure_agent_skill_branch(db, tenant_id, agent_id, skill)
    next_version = next_branch_version(branch.head_version)
    branch.content_json = dict(content)
    branch.head_version = next_version
    branch.status = "active"
    branch.sync_state = "diverged"
    branch.updated_at = utc_now()
    _ensure_branch_version(db, branch, change_summary)
    return branch


def sync_branch_from_overall(db: Session, tenant_id: str, agent_id: str, skill: Skill) -> AgentSkillBranch:
    branch = ensure_agent_skill_branch(db, tenant_id, agent_id, skill)
    branch.base_version = skill.version
    branch.head_version = skill.version
    branch.content_json = dict(skill.content_json)
    branch.status = "active" if skill.status == "published" else "inactive"
    branch.sync_state = "synced"
    branch.updated_at = utc_now()
    _ensure_branch_version(db, branch, "同步整体版本")
    return branch


def promote_branch_to_overall(db: Session, tenant_id: str, branch: AgentSkillBranch) -> Skill:
    skill = db.exec(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.skill_id == branch.skill_id)
    ).first()
    if not skill:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Skill not found")
    next_version = next_global_version(skill.version)
    content = dict(branch.content_json)
    content["version"] = next_version
    skill.version = next_version
    skill.name = str(content.get("name") or skill.name)
    skill.business_domain = content.get("business_domain") or skill.business_domain
    skill.description = content.get("description") or skill.description
    skill.content_json = content
    skill.status = "published"
    skill.updated_at = utc_now()
    db.add(
        SkillVersion(
            tenant_id=tenant_id,
            skill_id=skill.skill_id,
            version=next_version,
            name=skill.name,
            business_domain=skill.business_domain,
            description=skill.description,
            content_json=content,
            status="published",
        )
    )
    branch.base_version = next_version
    branch.head_version = next_version
    branch.content_json = content
    branch.sync_state = "synced"
    branch.updated_at = utc_now()
    _ensure_branch_version(db, branch, "推送到整体")
    return skill


def rollback_branch(db: Session, tenant_id: str, agent_id: str, skill_id: str, version: str) -> AgentSkillBranch:
    branch = db.exec(
        select(AgentSkillBranch).where(
            AgentSkillBranch.tenant_id == tenant_id,
            AgentSkillBranch.agent_id == agent_id,
            AgentSkillBranch.skill_id == skill_id,
        )
    ).first()
    if not branch:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Branch not found")
    version_row = db.exec(
        select(AgentSkillBranchVersion).where(
            AgentSkillBranchVersion.tenant_id == tenant_id,
            AgentSkillBranchVersion.agent_id == agent_id,
            AgentSkillBranchVersion.skill_id == skill_id,
            AgentSkillBranchVersion.version == version,
        )
    ).first()
    if not version_row:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Branch version not found")
    branch.content_json = dict(version_row.content_json)
    branch.head_version = version_row.version
    branch.status = version_row.status
    branch.sync_state = "synced" if version_row.version == branch.base_version else "diverged"
    branch.updated_at = utc_now()
    return branch


def branch_versions(db: Session, tenant_id: str, agent_id: str, skill_id: str) -> list[AgentSkillBranchVersion]:
    return list(
        db.exec(
            select(AgentSkillBranchVersion)
            .where(
                AgentSkillBranchVersion.tenant_id == tenant_id,
                AgentSkillBranchVersion.agent_id == agent_id,
                AgentSkillBranchVersion.skill_id == skill_id,
            )
            .order_by(AgentSkillBranchVersion.created_at.desc())
        ).all()
    )


def visible_knowledge_base_ids(db: Session, tenant_id: str, agent_id: str | None = None) -> list[str]:
    return list(visible_knowledge_base_versions(db, tenant_id, agent_id).keys())


def visible_knowledge_base_versions(
    db: Session,
    tenant_id: str,
    agent_id: str | None = None,
) -> dict[str, KnowledgeBaseVersion]:
    agent = get_agent(db, tenant_id, agent_id)
    if not agent or agent.is_overall:
        rows = db.exec(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.status != "archived",
            )
        ).all()
        return {row.id: ensure_knowledge_base_version(db, row, _current_knowledge_version(row)) for row in rows}
    branches = db.exec(
        select(AgentKnowledgeBranch).where(
            AgentKnowledgeBranch.tenant_id == tenant_id,
            AgentKnowledgeBranch.agent_id == agent.id,
            AgentKnowledgeBranch.status == "active",
        )
    ).all()
    result: dict[str, KnowledgeBaseVersion] = {}
    for branch in branches:
        kb = db.get(KnowledgeBase, branch.knowledge_base_id)
        if not kb or kb.tenant_id != tenant_id or kb.status == "archived":
            continue
        result[kb.id] = ensure_knowledge_base_version(db, kb, branch.head_version)
    return result


def visible_knowledge_base_version_ids(
    db: Session,
    tenant_id: str,
    agent_id: str | None = None,
) -> list[str]:
    return [row.id for row in visible_knowledge_base_versions(db, tenant_id, agent_id).values()]


def ensure_knowledge_base_version(db: Session, kb: KnowledgeBase, version: str | None = None) -> KnowledgeBaseVersion:
    normalized_version = version or _current_knowledge_version(kb)
    row = db.exec(
        select(KnowledgeBaseVersion).where(
            KnowledgeBaseVersion.tenant_id == kb.tenant_id,
            KnowledgeBaseVersion.knowledge_base_id == kb.id,
            KnowledgeBaseVersion.version == normalized_version,
        )
    ).first()
    if row:
        return row
    row = KnowledgeBaseVersion(
        id=f"kbver_{kb.id}_{_safe_version_id(normalized_version)}",
        tenant_id=kb.tenant_id,
        knowledge_base_id=kb.id,
        version=normalized_version,
        name=kb.name,
        description=kb.description,
        status=kb.status,
        metadata_json=dict(kb.metadata_json or {}),
    )
    db.add(row)
    db.flush()
    return row


def knowledge_version_for_upload(
    db: Session,
    tenant_id: str,
    knowledge_base_id: str,
    agent_id: str | None,
) -> KnowledgeBaseVersion:
    kb = db.get(KnowledgeBase, knowledge_base_id)
    if not kb or kb.tenant_id != tenant_id or kb.status == "archived":
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Knowledge base not found")
    agent = get_agent(db, tenant_id, agent_id)
    if not agent or agent.is_overall:
        return ensure_knowledge_base_version(db, kb, _current_knowledge_version(kb))
    branch = _ensure_knowledge_branch(db, tenant_id, agent.id, kb)
    next_version = _next_knowledge_branch_version(branch)
    branch.head_version = next_version
    branch.sync_state = "diverged"
    branch.status = "active"
    branch.updated_at = utc_now()
    return ensure_knowledge_base_version(db, kb, next_version)


def sync_knowledge_branch_from_overall(
    db: Session,
    tenant_id: str,
    agent_id: str,
    knowledge_base_id: str,
) -> AgentKnowledgeBranch:
    kb = _get_knowledge_base(db, tenant_id, knowledge_base_id)
    branch = _ensure_knowledge_branch(db, tenant_id, agent_id, kb)
    current_version = _current_knowledge_version(kb)
    ensure_knowledge_base_version(db, kb, current_version)
    branch.base_version = current_version
    branch.head_version = current_version
    branch.status = "active"
    branch.sync_state = "synced"
    branch.updated_at = utc_now()
    return branch


def promote_knowledge_branch_to_overall(
    db: Session,
    tenant_id: str,
    agent_id: str,
    knowledge_base_id: str,
) -> KnowledgeBaseVersion:
    kb = _get_knowledge_base(db, tenant_id, knowledge_base_id)
    branch = db.exec(
        select(AgentKnowledgeBranch).where(
            AgentKnowledgeBranch.tenant_id == tenant_id,
            AgentKnowledgeBranch.agent_id == agent_id,
            AgentKnowledgeBranch.knowledge_base_id == knowledge_base_id,
        )
    ).first()
    if not branch:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Knowledge branch not found")
    source = ensure_knowledge_base_version(db, kb, branch.head_version)
    next_version = next_global_version(_current_knowledge_version(kb))
    target = ensure_knowledge_base_version(db, kb, next_version)
    target.name = source.name
    target.description = source.description
    target.metadata_json = dict(source.metadata_json or {})
    target.status = "active"
    target.updated_at = utc_now()
    _retag_knowledge_version(db, tenant_id, knowledge_base_id, source.id, target.id)
    kb.name = source.name
    kb.description = source.description
    kb.metadata_json = {**(kb.metadata_json or {}), "current_version": next_version}
    kb.updated_at = utc_now()
    branch.base_version = next_version
    branch.head_version = next_version
    branch.sync_state = "synced"
    branch.updated_at = utc_now()
    return target


def rollback_knowledge_branch(
    db: Session,
    tenant_id: str,
    agent_id: str,
    knowledge_base_id: str,
    version: str,
) -> AgentKnowledgeBranch:
    kb = _get_knowledge_base(db, tenant_id, knowledge_base_id)
    target = ensure_knowledge_base_version(db, kb, version)
    branch = _ensure_knowledge_branch(db, tenant_id, agent_id, kb)
    branch.head_version = target.version
    branch.status = "active"
    branch.sync_state = "synced" if target.version == branch.base_version else "diverged"
    branch.updated_at = utc_now()
    return branch


def model_for_agent(db: Session, tenant_id: str, agent_id: str | None, role: str = "default") -> ModelConfig | None:
    agent = get_agent(db, tenant_id, agent_id)
    roles: Iterable[str] = (role, "default") if role != "default" else ("default",)
    if agent:
        for candidate_role in roles:
            binding = db.exec(
                select(AgentModelBinding).where(
                    AgentModelBinding.tenant_id == tenant_id,
                    AgentModelBinding.agent_id == agent.id,
                    AgentModelBinding.role == candidate_role,
                )
            ).first()
            if binding:
                model = db.get(ModelConfig, binding.model_config_id)
                if model and model.enabled:
                    return model
    return db.exec(
        select(ModelConfig).where(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.enabled == True,  # noqa: E712
        )
    ).first()


def copy_overall_scope_to_agent(db: Session, tenant_id: str, agent: AgentProfile) -> None:
    skills = db.exec(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.status != "archived")
    ).all()
    for skill in skills:
        _ensure_binding(db, tenant_id, agent.id, "skill", skill.id)
        ensure_agent_skill_branch(db, tenant_id, agent.id, skill)
    knowledge_bases = db.exec(
        select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.status != "archived")
    ).all()
    for kb in knowledge_bases:
        _ensure_binding(db, tenant_id, agent.id, "knowledge_base", kb.id)
        _ensure_knowledge_branch(db, tenant_id, agent.id, kb)
    from app.db.models import GeneralSkill

    general_skills = db.exec(
        select(GeneralSkill).where(GeneralSkill.tenant_id == tenant_id, GeneralSkill.status != "archived")
    ).all()
    for general_skill in general_skills:
        _ensure_binding(db, tenant_id, agent.id, "general_skill", general_skill.id)


def next_branch_version(version: str) -> str:
    base, _, suffix = version.partition("-branch.")
    if suffix.isdigit():
        return f"{base}-branch.{int(suffix) + 1}"
    return f"{base}-branch.1"


def next_global_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
        return f"{parts[0]}.{int(parts[1]) + 1}.0"
    return f"{version}.1"


def _ensure_branch_version(db: Session, branch: AgentSkillBranch, change_summary: str) -> None:
    existing = db.exec(
        select(AgentSkillBranchVersion).where(
            AgentSkillBranchVersion.tenant_id == branch.tenant_id,
            AgentSkillBranchVersion.agent_id == branch.agent_id,
            AgentSkillBranchVersion.skill_id == branch.skill_id,
            AgentSkillBranchVersion.version == branch.head_version,
        )
    ).first()
    if existing:
        return
    db.add(
        AgentSkillBranchVersion(
            tenant_id=branch.tenant_id,
            agent_id=branch.agent_id,
            skill_id=branch.skill_id,
            source_skill_id=branch.source_skill_id,
            version=branch.head_version,
            base_version=branch.base_version,
            content_json=dict(branch.content_json),
            status=branch.status,
            sync_state=branch.sync_state,
            change_summary=change_summary,
        )
    )


def _ensure_binding(db: Session, tenant_id: str, agent_id: str, resource_type: str, resource_id: str) -> None:
    existing = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == tenant_id,
            AgentResourceBinding.agent_id == agent_id,
            AgentResourceBinding.resource_type == resource_type,
            AgentResourceBinding.resource_id == resource_id,
        )
    ).first()
    if existing:
        existing.status = "active"
        existing.updated_at = utc_now()
        return
    db.add(
        AgentResourceBinding(
            tenant_id=tenant_id,
            agent_id=agent_id,
            resource_type=resource_type,
            resource_id=resource_id,
            status="active",
        )
    )


def _ensure_knowledge_branch(db: Session, tenant_id: str, agent_id: str, kb: KnowledgeBase) -> AgentKnowledgeBranch:
    branch = db.exec(
        select(AgentKnowledgeBranch).where(
            AgentKnowledgeBranch.tenant_id == tenant_id,
            AgentKnowledgeBranch.agent_id == agent_id,
            AgentKnowledgeBranch.knowledge_base_id == kb.id,
        )
    ).first()
    if branch:
        return branch
    branch = AgentKnowledgeBranch(
        tenant_id=tenant_id,
        agent_id=agent_id,
        knowledge_base_id=kb.id,
        base_version="1.0.0",
        head_version="1.0.0",
        status="active",
        sync_state="synced",
    )
    db.add(branch)
    return branch


def _get_knowledge_base(db: Session, tenant_id: str, knowledge_base_id: str) -> KnowledgeBase:
    kb = db.get(KnowledgeBase, knowledge_base_id)
    if not kb or kb.tenant_id != tenant_id or kb.status == "archived":
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


def _current_knowledge_version(kb: KnowledgeBase) -> str:
    metadata = kb.metadata_json or {}
    version = metadata.get("current_version") if isinstance(metadata, dict) else None
    return str(version or "1.0.0")


def _next_knowledge_branch_version(branch: AgentKnowledgeBranch) -> str:
    prefix = f"{branch.base_version}-branch.{_safe_version_id(branch.agent_id)}."
    if branch.head_version.startswith(prefix):
        suffix = branch.head_version.removeprefix(prefix)
        if suffix.isdigit():
            return f"{prefix}{int(suffix) + 1}"
    return f"{prefix}1"


def _retag_knowledge_version(
    db: Session,
    tenant_id: str,
    knowledge_base_id: str,
    source_version_id: str,
    target_version_id: str,
) -> None:
    tables = (KnowledgeDocument, KnowledgeBucket, KnowledgeChunk, KnowledgeDiscoverySuggestion)
    for model in tables:
        rows = db.exec(
            select(model).where(
                model.tenant_id == tenant_id,
                model.knowledge_base_id == knowledge_base_id,
                model.knowledge_base_version_id == source_version_id,
            )
        ).all()
        for row in rows:
            row.knowledge_base_version_id = target_version_id
            row.updated_at = utc_now()
            db.add(row)


def _safe_version_id(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)
