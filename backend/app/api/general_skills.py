from __future__ import annotations

import json
import queue
import re
import threading
import zipfile
from collections.abc import Iterator
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.agents.branching import get_agent, require_overall_agent
from app.db import get_session
from app.db.models import AgentResourceBinding, GeneralSkill, ModelConfig, utc_now
from app.general_skills import (
    GeneralSkillClawHubImportRequest,
    GeneralSkillImportRequest,
    GeneralSkillRead,
    GeneralSkillRunRequest,
    GeneralSkillRunResponse,
)
from app.general_skills.schema import GeneralSkillFile
from app.general_skills.runner import GeneralSkillRunner
from app.security.tenant import ensure_tenant

router = APIRouter(prefix="/api/enterprise/general-skills", tags=["enterprise:general-skills"])

MAX_CLAWHUB_PACKAGE_BYTES = 24 * 1024 * 1024
MAX_CLAWHUB_FILE_BYTES = 2 * 1024 * 1024
MAX_CLAWHUB_FILES = 240


def _agent_id_or_none(agent_id: object | None) -> str | None:
    return agent_id if isinstance(agent_id, str) and agent_id else None


def general_skill_read(row: GeneralSkill, status_override: str | None = None) -> GeneralSkillRead:
    return GeneralSkillRead(
        id=row.id,
        tenant_id=row.tenant_id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        homepage=row.homepage,
        skill_markdown=row.skill_markdown,
        skill_files=[GeneralSkillFile.model_validate(item) for item in _skill_files_or_markdown(row)],
        metadata=row.metadata_json or {},
        status=status_override or row.status,
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
    files = _normalize_skill_files(request.files, request.markdown)
    markdown = _skill_markdown_from_files(files)
    metadata = _parse_skill_metadata(markdown)
    name = _optional_text(request.name) or _metadata_text(metadata, "name", "title") or "未命名通用技能"
    slug = _optional_text(request.slug) or _metadata_text(metadata, "slug", "id") or _slugify(name)
    description = _optional_text(request.description) or _metadata_text(metadata, "description", "summary")
    homepage = _optional_text(request.homepage) or _metadata_text(metadata, "homepage", "url", "source")
    _validate_slug(slug)
    lookup_slug = _optional_text(request.original_slug)
    row = None
    if lookup_slug:
        row = db.exec(
            select(GeneralSkill).where(
                GeneralSkill.tenant_id == request.tenant_id,
                GeneralSkill.slug == lookup_slug,
            )
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="General skill to update was not found")
    else:
        conflict = db.exec(
            select(GeneralSkill).where(
                GeneralSkill.tenant_id == request.tenant_id,
                GeneralSkill.slug == slug,
            )
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="General skill slug already exists")
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
        row.skill_files_json = [file.model_dump(mode="json") for file in files]
        row.metadata_json = metadata
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
            skill_files_json=[file.model_dump(mode="json") for file in files],
            metadata_json=metadata,
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


@router.post("/import-clawhub", response_model=GeneralSkillRead)
def import_clawhub_skill(
    request: GeneralSkillClawHubImportRequest,
    db: Session = Depends(get_session),
) -> GeneralSkillRead:
    ensure_tenant(db, request.tenant_id)
    raw_files = _load_clawhub_source(request.source)
    files = _normalize_skill_files(raw_files, None)
    markdown = _skill_markdown_from_files(files)
    metadata = _parse_skill_metadata(markdown)
    name = _optional_text(request.name) or _metadata_text(metadata, "name", "title") or _source_name(request.source)
    slug_base = _optional_text(request.slug) or _metadata_text(metadata, "slug", "id") or _slugify(name)
    slug = _unique_slug(db, request.tenant_id, slug_base)
    description = _optional_text(request.description) or _metadata_text(metadata, "description", "summary")
    homepage = _optional_text(request.homepage) or _metadata_text(metadata, "homepage", "url", "source")
    _validate_slug(slug)
    now = utc_now()
    row = GeneralSkill(
        tenant_id=request.tenant_id,
        slug=slug,
        name=name,
        description=description,
        homepage=homepage,
        skill_markdown=markdown,
        skill_files_json=[file.model_dump(mode="json") for file in files],
        metadata_json={**metadata, "import_source": request.source},
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
    agent_id: str | None = Query(None),
) -> list[GeneralSkillRead]:
    ensure_tenant(db, tenant_id)
    agent_id = _agent_id_or_none(agent_id)
    agent = get_agent(db, tenant_id, agent_id)
    if agent and not agent.is_overall:
        bindings = db.exec(
            select(AgentResourceBinding)
            .where(
                AgentResourceBinding.tenant_id == tenant_id,
                AgentResourceBinding.agent_id == agent.id,
                AgentResourceBinding.resource_type == "general_skill",
            )
            .order_by(AgentResourceBinding.updated_at.desc())
        ).all()
        if not bindings:
            return []
        rows_by_id = {
            row.id: row
            for row in db.exec(
                select(GeneralSkill).where(
                    GeneralSkill.tenant_id == tenant_id,
                    GeneralSkill.id.in_([binding.resource_id for binding in bindings]),
                )
            ).all()
        }
        return [
            general_skill_read(
                rows_by_id[binding.resource_id],
                status_override="published" if binding.status == "active" else "archived",
            )
            for binding in bindings
            if binding.resource_id in rows_by_id
        ]
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


@router.post("/{slug}/publish", response_model=GeneralSkillRead)
def publish_general_skill(
    slug: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    agent_id: str | None = Query(None),
) -> GeneralSkillRead:
    row = _get_general_skill(db, tenant_id, slug)
    agent_id = _agent_id_or_none(agent_id)
    agent = get_agent(db, tenant_id, agent_id)
    if agent and not agent.is_overall:
        binding = _ensure_general_skill_binding(db, tenant_id, agent.id, row.id)
        binding.status = "active"
        binding.updated_at = utc_now()
        db.add(binding)
        db.commit()
        return general_skill_read(row, status_override="published")
    row.status = "published"
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return general_skill_read(row)


@router.post("/{slug}/archive", response_model=GeneralSkillRead)
def archive_general_skill(
    slug: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    agent_id: str | None = Query(None),
) -> GeneralSkillRead:
    row = _get_general_skill(db, tenant_id, slug)
    agent_id = _agent_id_or_none(agent_id)
    agent = get_agent(db, tenant_id, agent_id)
    if agent and not agent.is_overall:
        binding = _ensure_general_skill_binding(db, tenant_id, agent.id, row.id)
        binding.status = "inactive"
        binding.updated_at = utc_now()
        db.add(binding)
        db.commit()
        return general_skill_read(row, status_override="archived")
    row.status = "archived"
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return general_skill_read(row)


@router.delete("/{slug}")
def delete_general_skill(
    slug: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    agent_id: str | None = Query(None),
) -> dict[str, str]:
    agent_id = _agent_id_or_none(agent_id)
    require_overall_agent(db, tenant_id, agent_id)
    row = _get_general_skill(db, tenant_id, slug)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "slug": slug}


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


def _ensure_general_skill_binding(
    db: Session,
    tenant_id: str,
    agent_id: str,
    general_skill_id: str,
) -> AgentResourceBinding:
    row = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == tenant_id,
            AgentResourceBinding.agent_id == agent_id,
            AgentResourceBinding.resource_type == "general_skill",
            AgentResourceBinding.resource_id == general_skill_id,
        )
    ).first()
    if row:
        return row
    row = AgentResourceBinding(
        tenant_id=tenant_id,
        agent_id=agent_id,
        resource_type="general_skill",
        resource_id=general_skill_id,
        status="active",
        metadata_json={},
    )
    db.add(row)
    db.flush()
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
        skill_files_json=_skill_files_or_markdown(row),
        metadata_json=row.metadata_json or {},
        permissions_json=row.permissions_json or {},
        runtime_config_json=row.runtime_config_json or {},
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


def _normalize_skill_files(
    requested_files: list[GeneralSkillFile],
    markdown: str | None,
) -> list[GeneralSkillFile]:
    if not requested_files:
        content = _required_text(markdown, "markdown")
        return [GeneralSkillFile(path="SKILL.md", content=content, size=len(content.encode("utf-8")))]
    cleaned_files: list[GeneralSkillFile] = []
    for file in requested_files:
        path = _clean_package_path(file.path)
        content = file.content or ""
        cleaned_files.append(
            GeneralSkillFile(
                path=path,
                content=content,
                size=file.size if file.size is not None else len(content.encode("utf-8")),
                mime_type=file.mime_type,
            )
        )
    skill_file = _find_skill_file(cleaned_files)
    if not skill_file:
        raise HTTPException(status_code=400, detail="General skill folder must contain SKILL.md")
    base_dir = skill_file.path.rsplit("/", 1)[0] if "/" in skill_file.path else ""
    if not base_dir:
        return cleaned_files
    normalized: list[GeneralSkillFile] = []
    prefix = f"{base_dir}/"
    for file in cleaned_files:
        if file.path == base_dir or not file.path.startswith(prefix):
            continue
        normalized.append(file.model_copy(update={"path": file.path[len(prefix):]}))
    return normalized


def _clean_package_path(path: str) -> str:
    cleaned = str(path or "").replace("\\", "/").strip().strip("/")
    parts = [part for part in cleaned.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail=f"Invalid general skill file path: {path}")
    return "/".join(parts)


def _find_skill_file(files: list[GeneralSkillFile]) -> GeneralSkillFile | None:
    return next((file for file in files if file.path.rsplit("/", 1)[-1].lower() == "skill.md"), None)


def _skill_markdown_from_files(files: list[GeneralSkillFile]) -> str:
    skill_file = _find_skill_file(files)
    if not skill_file or not skill_file.content.strip():
        raise HTTPException(status_code=400, detail="General skill SKILL.md cannot be empty")
    return skill_file.content


def _skill_files_or_markdown(row: GeneralSkill) -> list[dict[str, object]]:
    files = row.skill_files_json or []
    if files:
        return files
    return [{"path": "SKILL.md", "content": row.skill_markdown, "size": len(row.skill_markdown.encode("utf-8"))}]


def _parse_skill_metadata(markdown: str) -> dict[str, object]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, object] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return metadata
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            continue
        metadata[key] = _parse_metadata_value(value.strip())
    return metadata


def _parse_metadata_value(value: str) -> object:
    cleaned = value.strip().strip("'\"")
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return [
            item.strip().strip("'\"")
            for item in cleaned[1:-1].split(",")
            if item.strip()
        ]
    return cleaned


def _metadata_text(metadata: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-_")
    return slug or "general-skill"


def _unique_slug(db: Session, tenant_id: str, base_slug: str) -> str:
    base = _slugify(base_slug)
    candidate = base
    suffix = 2
    while db.exec(select(GeneralSkill).where(GeneralSkill.tenant_id == tenant_id, GeneralSkill.slug == candidate)).first():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _source_name(source: str) -> str:
    parsed = urlparse(source)
    path = parsed.path if parsed.scheme else source
    cleaned = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".zip").removesuffix(".md")
    return cleaned or "ClawHub 通用技能"


def _load_clawhub_source(source: str) -> list[GeneralSkillFile]:
    cleaned = _required_text(source, "source")
    if cleaned.startswith(("http://", "https://")):
        return _load_remote_skill_source(cleaned)
    if _looks_like_github_shorthand(cleaned):
        return _load_remote_skill_source(f"https://github.com/{cleaned}")
    raise HTTPException(
        status_code=400,
        detail="ClawHub source must be a GitHub URL, raw SKILL.md URL, zip URL, or owner/repo path",
    )


def _looks_like_github_shorthand(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/.+)?", value.strip()))


def _load_remote_skill_source(url: str) -> list[GeneralSkillFile]:
    parsed = urlparse(url)
    if parsed.netloc in {"github.com", "www.github.com"}:
        return _load_github_skill_source(parsed)
    data, content_type = _download_url(url)
    if url.lower().endswith(".zip") or "zip" in content_type:
        return _files_from_zip(data)
    text = _decode_text(data)
    return [GeneralSkillFile(path="SKILL.md", content=text, size=len(data), mime_type=content_type or "text/markdown")]


def _load_github_skill_source(parsed) -> list[GeneralSkillFile]:
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="GitHub source must include owner and repository")
    owner, repo = parts[0], parts[1]
    if "raw.githubusercontent.com" in parsed.netloc:
        data, content_type = _download_url(parsed.geturl())
        return [GeneralSkillFile(path="SKILL.md", content=_decode_text(data), size=len(data), mime_type=content_type or "text/markdown")]
    if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
        branch = parts[3]
        file_path = "/".join(parts[4:])
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
        data, content_type = _download_url(raw_url)
        return [GeneralSkillFile(path=file_path.rsplit("/", 1)[-1] or "SKILL.md", content=_decode_text(data), size=len(data), mime_type=content_type or "text/markdown")]
    if len(parts) >= 5 and parts[2] == "tree":
        branch = parts[3]
        subtree = "/".join(parts[4:])
        return _download_github_archive(owner, repo, [branch], subtree)
    subtree = "/".join(parts[2:]) if len(parts) > 2 else ""
    return _download_github_archive(owner, repo, ["main", "master"], subtree)


def _download_github_archive(owner: str, repo: str, branches: list[str], subtree: str = "") -> list[GeneralSkillFile]:
    errors: list[str] = []
    for branch in branches:
        archive_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        try:
            data, _ = _download_url(archive_url)
            return _files_from_zip(data, subtree=subtree)
        except HTTPException as exc:
            errors.append(str(exc.detail))
    raise HTTPException(status_code=400, detail=f"Unable to download GitHub skill package: {'; '.join(errors)}")


def _download_url(url: str) -> tuple[bytes, str]:
    try:
        request = Request(url, headers={"User-Agent": "UltraRAG4-GeneralSkillImporter/1.0"})
        with urlopen(request, timeout=20) as response:  # noqa: S310 - user-confirmed import source
            content_type = response.headers.get("content-type", "")
            data = response.read(MAX_CLAWHUB_PACKAGE_BYTES + 1)
    except HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Download failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise HTTPException(status_code=400, detail=f"Download failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=400, detail="Download timed out") from exc
    if len(data) > MAX_CLAWHUB_PACKAGE_BYTES:
        raise HTTPException(status_code=400, detail="General skill package is too large")
    return data, content_type


def _files_from_zip(data: bytes, subtree: str = "") -> list[GeneralSkillFile]:
    normalized_subtree = subtree.strip("/")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/") and not _skip_package_path(name)]
        skill_candidates = [name for name in names if name.rsplit("/", 1)[-1].lower() == "skill.md"]
        if normalized_subtree:
            skill_candidates = [name for name in skill_candidates if _zip_relative_path(name, normalized_subtree) is not None]
        if not skill_candidates:
            raise HTTPException(status_code=400, detail="Package does not contain SKILL.md")
        base = skill_candidates[0].rsplit("/", 1)[0] if "/" in skill_candidates[0] else ""
        files: list[GeneralSkillFile] = []
        for name in names:
            if base:
                if not name.startswith(f"{base}/"):
                    continue
                relative = name[len(base) + 1 :]
            else:
                relative = name
            if not relative or relative.endswith("/"):
                continue
            info = archive.getinfo(name)
            if info.file_size > MAX_CLAWHUB_FILE_BYTES:
                continue
            if len(files) >= MAX_CLAWHUB_FILES:
                break
            content = _decode_text(archive.read(name))
            files.append(
                GeneralSkillFile(
                    path=relative,
                    content=content,
                    size=info.file_size,
                    mime_type=_guess_mime_type(relative),
                )
            )
    return files


def _zip_relative_path(name: str, subtree: str) -> str | None:
    parts = name.split("/")
    for index in range(1, len(parts)):
        candidate = "/".join(parts[index:])
        if candidate == subtree or candidate.startswith(f"{subtree}/"):
            return candidate
    return None


def _skip_package_path(path: str) -> bool:
    parts = path.split("/")
    return any(part in {"__MACOSX", ".git", "node_modules", ".venv", "dist", "build"} for part in parts)


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _guess_mime_type(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".md"):
        return "text/markdown"
    if lower.endswith((".py", ".sh", ".js", ".ts", ".json", ".txt", ".yaml", ".yml")):
        return "text/plain"
    return "text/plain"


def _validate_slug(value: str) -> None:
    if any(char.isspace() for char in value) or "/" in value:
        raise HTTPException(status_code=400, detail="General skill slug cannot contain spaces or slashes")


def _sse(event: object, data: object) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
