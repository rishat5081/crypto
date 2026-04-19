from __future__ import annotations

from pathlib import Path


def _max_python_file_lines() -> int:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("max_python_file_lines"):
            return int(stripped.split("=", 1)[1].strip())
    raise AssertionError("max_python_file_lines is not configured in pyproject.toml")


def test_backend_python_files_stay_within_line_limit() -> None:
    max_lines = _max_python_file_lines()
    backend_root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        line_count = sum(1 for _ in path.open("r", encoding="utf-8"))
        if line_count > max_lines:
            offenders.append((line_count, path.relative_to(backend_root)))
    assert not offenders, f"Python files exceed {max_lines} lines: {offenders}"
