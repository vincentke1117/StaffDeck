# Backend

FastAPI backend for the Skill Agent Loop MVP.

## Run

From the repository root, prefer:

```bash
scripts/dev_up.sh
```

For backend-only debugging:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

Swagger UI: `http://localhost:8000/docs`

`CORS_ORIGINS` controls the allowed frontend origins. The root `scripts/dev_up.sh`
sets local origins by default and can add public tunnel origins with
`PUBLIC_ENTERPRISE_ORIGIN` and `PUBLIC_CHAT_ORIGIN`.

## General Skill Code Runtime

通用技能生成的 Python/Bash runner 不直接依赖系统 Python。运行时按以下顺序选择环境：

1. `GENERAL_SKILL_RUNTIME_PYTHON` 指定的 Python；
2. `GENERAL_SKILL_RUNTIME_VENV` 指定虚拟环境中的 Python；
3. `backend/.venv/bin/python`；
4. 自动创建 `backend/.runtime_venv`。

`GENERAL_SKILL_RUNTIME_PACKAGES` 默认安装/校验 `requests,httpx`，用于通用 API
访问。需要文档解析或数据处理时可以扩展为：

```bash
GENERAL_SKILL_RUNTIME_PACKAGES="requests,httpx,beautifulsoup4,lxml,pypdf,python-docx,pandas,numpy,python-dateutil"
```

如果部署环境禁止自动安装依赖，设置：

```bash
GENERAL_SKILL_RUNTIME_AUTO_INSTALL="false"
GENERAL_SKILL_RUNTIME_PYTHON="/path/to/prepared/venv/bin/python"
```

## Demo Seed

Startup seeds:

- `tenant_demo`
- refund skill `after_sales_refund`
- exchange skill `after_sales_exchange`
- mock HTTP tool `order.query`

Set `DEMO_MODEL_API_KEY` before first startup if you want a default model config to be created automatically.
