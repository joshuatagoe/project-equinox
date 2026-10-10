"""Layering guard (architecture section 3).

The matcher and router may import only equinox.models, their own package, the standard library
and pydantic, and their source may not name a venue. This is how "routing logic should not
contain venue-specific assumptions" is checked on every run.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "equinox"
ENGINES = ("matcher", "router")
VENUE_WORDS = re.compile("kalshi|polymarket|meridian", re.IGNORECASE)
THIRD_PARTY_ALLOWED = {"pydantic"}


def violations(source: str, package: str) -> list[str]:
    """Return each rule a module in equinox.<package> breaks, in plain words."""
    found = [f"names a venue: {m.group(0)!r}" for m in VENUE_WORDS.finditer(source)]
    own = f"equinox.{package}"
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = own.split(".")[: 3 - node.level]  # the module sits in equinox.<package>
                module = ".".join(base + ([node.module] if node.module else []))
                if not node.module and module == "equinox":
                    targets = [f"equinox.{alias.name}" for alias in node.names]
                else:
                    targets = [module]
            else:
                targets = [node.module or ""]
        else:
            continue
        found += [f"imports {t}" for t in targets if not _allowed(t, own)]
    return found


def _allowed(module: str, own: str) -> bool:
    top = module.split(".")[0]
    if top == "equinox":
        return any(module == p or module.startswith(p + ".") for p in ("equinox.models", own))
    return top in sys.stdlib_module_names or top in THIRD_PARTY_ALLOWED


ENGINE_FILES = sorted(p for engine in ENGINES for p in (SRC / engine).glob("**/*.py"))


@pytest.mark.parametrize("path", ENGINE_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_engines_keep_the_layering_rule(path):
    package = path.relative_to(SRC).parts[0]
    assert violations(path.read_text(encoding="utf-8"), package) == []


def test_engines_exist_or_the_guard_says_so():
    built = [engine for engine in ENGINES if (SRC / engine).is_dir()]
    if not built:
        pytest.skip("matcher/ and router/ are not built yet; the guard runs once they exist")
    assert ENGINE_FILES, f"{built} exist but contain no Python files"


# Test 9: the guard itself, on temporary files.

ALLOWED_SOURCE = """
from __future__ import annotations
from decimal import Decimal
from pydantic import BaseModel
from equinox.models import CanonicalMarket
from equinox.models.canonical import Fill
from ..models import OrderBookLevel
from . import depth
from .depth import walk
import equinox.router.rationale
"""


def test_9_guard_accepts_models_stdlib_pydantic_and_its_own_package(tmp_path):
    module = tmp_path / "engine.py"
    module.write_text(ALLOWED_SOURCE, encoding="utf-8")
    assert violations(module.read_text(encoding="utf-8"), "router") == []


@pytest.mark.parametrize(
    "source",
    [
        "import equinox.adapters",
        "from equinox.adapters.base import FetchError",
        "from ..adapters import fetch",
        "from .. import cli",
        "from equinox.matcher import build_clusters",
        "import requests",
        "# the kalshi book is sorted ascending",
        "VENUE = 'Polymarket'",
        "def meridian_rule(): ...",
    ],
)
def test_9_guard_rejects_forbidden_imports_and_venue_names(tmp_path, source):
    module = tmp_path / "engine.py"
    module.write_text(source, encoding="utf-8")
    assert violations(module.read_text(encoding="utf-8"), "router") != []
