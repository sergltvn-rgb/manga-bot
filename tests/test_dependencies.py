from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _normalized_requirement_lines(path: Path) -> set[str]:
    return {
        line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")
    }


def test_runtime_requirements_include_bot_import_dependencies():
    requirements = ROOT / "requirements.txt"

    assert requirements.exists()

    lines = _normalized_requirement_lines(requirements)
    for package in ("aiogram", "aiohttp", "aiosqlite", "python-dotenv", "pillow"):
        assert any(line == package or line.startswith(f"{package}==") or line.startswith(f"{package}>=") for line in lines)


def test_dev_requirements_install_runtime_requirements_first():
    lines = _normalized_requirement_lines(ROOT / "requirements-dev.txt")

    assert "-r requirements.txt" in lines


def test_quality_workflow_installs_runtime_requirements():
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")

    assert "python -m pip install -r requirements.txt" in workflow
    assert "python -m pip install -r requirements-dev.txt" in workflow
