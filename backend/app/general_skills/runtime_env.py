from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

from app.config import get_settings


IMPORT_NAMES = {
    "beautifulsoup4": "bs4",
    "python-docx": "docx",
    "python-dateutil": "dateutil",
}


class GeneralSkillRuntimeError(RuntimeError):
    pass


def ensure_runtime_python() -> Path:
    settings = get_settings()
    python_path = _resolve_runtime_python(settings.general_skill_runtime_python, settings.general_skill_runtime_venv)
    if not python_path.exists():
        _create_runtime_venv(python_path)
    if settings.general_skill_runtime_auto_install:
        _ensure_packages(python_path, settings.general_skill_runtime_package_list)
    return python_path


def runtime_environment(base_env: dict[str, str] | None = None) -> dict[str, str]:
    python_path = ensure_runtime_python()
    env = dict(base_env or os.environ)
    bin_dir = python_path.parent
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["VIRTUAL_ENV"] = str(bin_dir.parent)
    env["GENERAL_SKILL_RUNTIME_PYTHON"] = str(python_path)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_runtime_python(explicit_python: str, explicit_venv: str) -> Path:
    if explicit_python.strip():
        return Path(explicit_python).expanduser()
    if explicit_venv.strip():
        return _python_in_venv(Path(explicit_venv).expanduser())
    backend_venv = _backend_dir() / ".venv"
    if _python_in_venv(backend_venv).exists():
        return _python_in_venv(backend_venv)
    return _python_in_venv(_backend_dir() / ".runtime_venv")


def _python_in_venv(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _create_runtime_venv(python_path: Path) -> None:
    venv_dir = python_path.parent.parent
    venv_dir.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
    if not python_path.exists():
        raise GeneralSkillRuntimeError(f"通用技能运行环境创建失败：{python_path}")


def _ensure_packages(python_path: Path, packages: list[str]) -> None:
    missing = [package for package in packages if not _can_import(python_path, _import_name(package))]
    if not missing:
        return
    result = subprocess.run(
        [str(python_path), "-m", "pip", "install", *missing],
        cwd=str(_backend_dir()),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise GeneralSkillRuntimeError(
            "通用技能运行环境依赖安装失败："
            + ", ".join(missing)
            + "\n"
            + (result.stderr or result.stdout or "").strip()
        )


def _can_import(python_path: Path, import_name: str) -> bool:
    result = subprocess.run(
        [str(python_path), "-c", f"import {import_name}"],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    return result.returncode == 0


def _import_name(package: str) -> str:
    normalized = package.strip()
    return IMPORT_NAMES.get(normalized, normalized.split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0].replace("-", "_"))
