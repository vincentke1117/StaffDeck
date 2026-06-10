from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.db.models import Tool, utc_now
from app.security.tenant import ensure_tenant
from app.tools import ToolExecutor
from app.tools.tool_schema import (
    ToolCall,
    ToolCreateRequest,
    ToolError,
    ToolProbeRequest,
    ToolProbeResponse,
    ToolRead,
    ToolResult,
    ToolTestRequest,
    ToolUpdateRequest,
)

router = APIRouter(prefix="/api/enterprise/tools", tags=["enterprise:tools"])


def tool_read(row: Tool) -> ToolRead:
    return ToolRead(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        method=row.method,
        url=row.url,
        headers=row.headers_json or {},
        auth=row.auth_json or {},
        input_schema=row.input_schema or {},
        output_schema=row.output_schema or {},
        allowed_skills=row.allowed_skills_json or [],
        enabled=row.enabled,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("", response_model=list[ToolRead])
def list_tools(tenant_id: str = Query(...), db: Session = Depends(get_session)) -> list[ToolRead]:
    ensure_tenant(db, tenant_id)
    rows = db.exec(select(Tool).where(Tool.tenant_id == tenant_id)).all()
    return [tool_read(row) for row in rows]


@router.post("", response_model=ToolRead)
def create_tool(request: ToolCreateRequest, db: Session = Depends(get_session)) -> ToolRead:
    ensure_tenant(db, request.tenant_id)
    existing = db.exec(
        select(Tool).where(Tool.tenant_id == request.tenant_id, Tool.name == request.name)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Tool name already exists for this tenant")
    row = Tool(
        tenant_id=request.tenant_id,
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        method=request.method,
        url=request.url,
        headers_json=request.headers,
        auth_json=request.auth,
        input_schema=request.input_schema,
        output_schema=request.output_schema,
        allowed_skills_json=request.allowed_skills,
        enabled=request.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return tool_read(row)


@router.post("/probe", response_model=ToolProbeResponse)
def probe_tool(request: ToolProbeRequest, db: Session = Depends(get_session)) -> ToolProbeResponse:
    ensure_tenant(db, request.tenant_id)
    headers = ToolExecutor(db)._resolve_headers(request.headers, request.auth)  # noqa: SLF001
    url = _normalize_probe_url(request.url)
    try:
        with httpx.Client(timeout=get_settings().tool_timeout_seconds) as client:
            if request.method.upper() == "GET":
                response = client.request(request.method.upper(), url, headers=headers, params=request.sample_arguments)
            else:
                response = client.request(request.method.upper(), url, headers=headers, json=request.sample_arguments)
    except httpx.TimeoutException:
        return ToolProbeResponse(
            success=False,
            error=ToolError(code="TIMEOUT", message="工具探测超时。"),
        )
    except Exception as exc:
        return ToolProbeResponse(
            success=False,
            error=ToolError(code="PROBE_ERROR", message=str(exc)),
        )

    data_preview = _response_preview(response)
    success = 200 <= response.status_code < 300
    return ToolProbeResponse(
        success=success,
        status_code=response.status_code,
        data_preview=data_preview,
        inferred_output_schema=_infer_json_schema(data_preview) if success else {},
        error=None
        if success
        else ToolError(code="HTTP_ERROR", message=f"工具探测返回异常状态码：{response.status_code}"),
    )


@router.get("/{tool_id}", response_model=ToolRead)
def get_tool(tool_id: str, tenant_id: str = Query(...), db: Session = Depends(get_session)) -> ToolRead:
    row = _get_tool(db, tenant_id, tool_id)
    return tool_read(row)


@router.put("/{tool_id}", response_model=ToolRead)
def update_tool(tool_id: str, request: ToolUpdateRequest, db: Session = Depends(get_session)) -> ToolRead:
    row = _get_tool(db, request.tenant_id, tool_id)
    row.name = request.name
    row.display_name = request.display_name
    row.description = request.description
    row.method = request.method
    row.url = request.url
    row.headers_json = request.headers
    row.auth_json = request.auth
    row.input_schema = request.input_schema
    row.output_schema = request.output_schema
    row.allowed_skills_json = request.allowed_skills
    row.enabled = request.enabled
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return tool_read(row)


@router.delete("/{tool_id}")
def delete_tool(
    tool_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
) -> dict[str, str]:
    row = _get_tool(db, tenant_id, tool_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@router.post("/{tool_id}/test", response_model=ToolResult)
def test_tool(tool_id: str, request: ToolTestRequest, db: Session = Depends(get_session)) -> ToolResult:
    row = _get_tool(db, request.tenant_id, tool_id)
    return ToolExecutor(db).execute(request.tenant_id, ToolCall(name=row.name, arguments=request.arguments))


def _get_tool(db: Session, tenant_id: str, tool_id: str) -> Tool:
    ensure_tenant(db, tenant_id)
    row = db.get(Tool, tool_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    return row


def _normalize_probe_url(url: str) -> str:
    stripped = url.strip()
    if stripped.startswith("/"):
        return f"{get_settings().normalized_tool_base_url}{stripped}"
    return stripped


def _response_preview(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        text = response.text
        return text[:2000] if len(text) > 2000 else text


def _infer_json_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        properties = {str(key): _infer_json_schema(item) for key, item in value.items()}
        return {"type": "object", "properties": properties, "required": list(properties.keys())}
    if isinstance(value, list):
        item_schema = _infer_json_schema(value[0]) if value else {}
        return {"type": "array", "items": item_schema}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    return {"type": "string"}
