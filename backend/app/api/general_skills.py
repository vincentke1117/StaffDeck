from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.db.models import GeneralSkill, ModelConfig, utc_now
from app.general_skills import GeneralSkillImportRequest, GeneralSkillRead, GeneralSkillRunRequest, GeneralSkillRunResponse
from app.general_skills.runner import GeneralSkillRunner
from app.security.tenant import ensure_tenant

router = APIRouter(prefix="/api/enterprise/general-skills", tags=["enterprise:general-skills"])


def general_skill_read(row: GeneralSkill) -> GeneralSkillRead:
    return GeneralSkillRead(
        id=row.id,
        tenant_id=row.tenant_id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        homepage=row.homepage,
        skill_markdown=row.skill_markdown,
        status=row.status,
        permissions=row.permissions_json or {},
        runtime_config=row.runtime_config_json or {},
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/import", response_model=GeneralSkillRead)
def import_general_skill(
    request: GeneralSkillImportRequest,
    db: Session = Depends(get_session),
) -> GeneralSkillRead:
    ensure_tenant(db, request.tenant_id)
    name = _required_text(request.name, "name")
    slug = _required_text(request.slug, "slug")
    markdown = _required_text(request.markdown, "markdown")
    description = _optional_text(request.description)
    homepage = _optional_text(request.homepage)
    _validate_slug(slug)
    lookup_slug = _optional_text(request.original_slug) or slug
    row = db.exec(
        select(GeneralSkill).where(
            GeneralSkill.tenant_id == request.tenant_id,
            GeneralSkill.slug == lookup_slug,
        )
    ).first()
    now = utc_now()
    if row:
        if slug != row.slug:
            conflict = db.exec(
                select(GeneralSkill).where(
                    GeneralSkill.tenant_id == request.tenant_id,
                    GeneralSkill.slug == slug,
                )
            ).first()
            if conflict:
                raise HTTPException(status_code=409, detail="General skill slug already exists")
        row.slug = slug
        row.name = name
        row.description = description
        row.homepage = homepage
        row.skill_markdown = markdown
        row.status = request.status
        row.updated_at = now
    else:
        row = GeneralSkill(
            tenant_id=request.tenant_id,
            slug=slug,
            name=name,
            description=description,
            homepage=homepage,
            skill_markdown=markdown,
            status=request.status,
            permissions_json={"network": True, "python": True},
            runtime_config_json={"runtime": "python", "timeout_seconds": 12},
            created_at=now,
            updated_at=now,
        )
    db.add(row)
    db.commit()
    db.refresh(row)
    return general_skill_read(row)


@router.get("", response_model=list[GeneralSkillRead])
def list_general_skills(
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
) -> list[GeneralSkillRead]:
    ensure_tenant(db, tenant_id)
    rows = db.exec(
        select(GeneralSkill).where(GeneralSkill.tenant_id == tenant_id).order_by(GeneralSkill.updated_at.desc())
    ).all()
    return [general_skill_read(row) for row in rows]


@router.get("/{slug}", response_model=GeneralSkillRead)
def get_general_skill(
    slug: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
) -> GeneralSkillRead:
    return general_skill_read(_get_general_skill(db, tenant_id, slug))


@router.post("/{slug}/run", response_model=GeneralSkillRunResponse)
def run_general_skill(
    slug: str,
    request: GeneralSkillRunRequest,
    db: Session = Depends(get_session),
) -> GeneralSkillRunResponse:
    skill = _get_general_skill(db, request.tenant_id, slug)
    if skill.status != "published":
        raise HTTPException(status_code=400, detail="General skill is not published")
    model_config = _get_default_model(db, request.tenant_id)
    return GeneralSkillRunner().run(skill, request.query, model_config, request.user_id, request.max_attempts)


@router.post("/{slug}/run/stream")
def run_general_skill_stream(
    slug: str,
    request: GeneralSkillRunRequest,
    db: Session = Depends(get_session),
) -> StreamingResponse:
    skill = _get_general_skill(db, request.tenant_id, slug)
    if skill.status != "published":
        raise HTTPException(status_code=400, detail="General skill is not published")
    model_config = _get_default_model(db, request.tenant_id)
    skill_snapshot = _general_skill_snapshot(skill)
    model_snapshot = _model_config_snapshot(model_config)

    def stream_events() -> Iterator[str]:
        events: queue.Queue[tuple[str, dict[str, object]] | None] = queue.Queue()

        def sink(item: dict[str, object]) -> None:
            events.put(("trace", item))

        def worker() -> None:
            try:
                response = GeneralSkillRunner().run(
                    skill_snapshot,
                    request.query,
                    model_snapshot,
                    request.user_id,
                    request.max_attempts,
                    sink,
                )
                events.put(("complete", response.model_dump(mode="json")))
            except Exception as exc:  # pragma: no cover - defensive stream boundary
                events.put(("error", {"message": str(exc)}))
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        yield _sse("stream_started", {"skill_slug": skill_snapshot.slug, "max_attempts": request.max_attempts})
        while True:
            item = events.get()
            if item is None:
                return
            event, payload = item
            yield _sse(event, payload)

    return StreamingResponse(stream_events(), media_type="text/event-stream")


def _get_general_skill(db: Session, tenant_id: str, slug: str) -> GeneralSkill:
    ensure_tenant(db, tenant_id)
    row = db.exec(
        select(GeneralSkill).where(GeneralSkill.tenant_id == tenant_id, GeneralSkill.slug == slug)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="General skill not found")
    return row


def _get_default_model(db: Session, tenant_id: str) -> ModelConfig:
    model_config = db.exec(
        select(ModelConfig).where(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.enabled == True,  # noqa: E712
        )
    ).first()
    if not model_config:
        raise HTTPException(status_code=400, detail="No default model config")
    return model_config


def _general_skill_snapshot(row: GeneralSkill) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=row.tenant_id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        homepage=row.homepage,
        skill_markdown=row.skill_markdown,
        status=row.status,
    )


def _model_config_snapshot(row: ModelConfig) -> SimpleNamespace:
    return SimpleNamespace(
        api_key_encrypted=row.api_key_encrypted,
        base_url=row.base_url,
        model=row.model,
        temperature=row.temperature,
        max_output_tokens=row.max_output_tokens,
    )


def _required_text(value: str | None, field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"General skill {field} cannot be empty")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _validate_slug(value: str) -> None:
    if any(char.isspace() for char in value) or "/" in value:
        raise HTTPException(status_code=400, detail="General skill slug cannot contain spaces or slashes")


def _sse(event: object, data: object) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
