"""chore-01 (D52): the readability rules the gate checks.

The brief evaluates "code readability, modularity, and documentation quality". These are the parts
of that a test can hold: short modules and functions, interfaces that don't depend on each other,
and a map of the code in the README that points at files that exist.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "equinox"
MODULES = sorted(SRC.rglob("*.py"))
MAX_MODULE_LINES = 300
MAX_FUNCTION_LINES = 40
WEB_SIDE = [*sorted((SRC / "web").glob("*.py")), SRC / "server.py"]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    """Every module a file imports, with relative imports resolved inside `equinox`."""
    package = ".".join(("equinox", *path.relative_to(SRC).parent.parts)).rstrip(".")
    found = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = (
                package.split(".")[: len(package.split(".")) - node.level + 1] if node.level else []
            )
            found.add(".".join([*base, node.module] if node.module else base))
    return found


def _is_under(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(SRC)))
def test_modules_stay_short(path):
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= MAX_MODULE_LINES, f"{lines} lines: split it by responsibility"


def test_functions_stay_short():
    too_long = [
        f"{path.relative_to(SRC)}:{node.lineno} {node.name} ({node.end_lineno - node.lineno + 1})"
        for path in MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.end_lineno - node.lineno + 1 > MAX_FUNCTION_LINES
    ]
    assert too_long == []


def test_the_web_ui_and_the_command_line_do_not_import_each_other():
    web_uses_cli = sorted(
        f"{path.name} imports {module}"
        for path in WEB_SIDE
        for module in _imports(path)
        if _is_under(module, "equinox.cli")
    )
    cli_uses_web = [m for m in _imports(SRC / "cli.py") if _is_under(m, "equinox.web")]
    assert web_uses_cli == [] and cli_uses_web == []


def test_reading_the_code_points_at_files_that_exist():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = re.search(r"^## Reading the code\n(.*?)(?=^## )", readme, re.MULTILINE | re.DOTALL)
    assert section, "README.md has no 'Reading the code' section"
    paths = re.findall(r"`((?:src|tests|docs)/[^`\s]+)`", section.group(1))
    assert len(paths) >= 8
    assert [p for p in paths if not (ROOT / p).exists()] == []
