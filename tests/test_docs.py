"""feat-06: the docs are checked against the code, so a README number can't drift.

1. Every command in the README's demo block runs through cli.main and gives the exit code, status,
   winner, dollar totals and counts the README states.
2. Every decision (D), assumption (A), architecture section and venue fact the written deliverables
   cite exists.
"""

import json
import re
import shlex
from decimal import Decimal
from pathlib import Path

import pytest

from equinox import cli

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DELIVERABLES = (README, ROOT / "docs" / "EQUIVALENCE.md", ROOT / "docs" / "ROUTING.md")
DEMO = re.compile(r"<!-- demo:start -->(.*?)<!-- demo:end -->", re.DOTALL)
PREFIX = "python -m equinox "


def demo_rows() -> list[tuple[str, int, str]]:
    """(command, exit code, result) for each table row in the demo block."""
    block = DEMO.search(README.read_text(encoding="utf-8")) if README.exists() else None
    rows = []
    for line in block.group(1).splitlines() if block else []:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith(f"`{PREFIX}"):
            rows.append((cells[0].strip("`"), int(cells[1]), cells[2]))
    return rows


ROWS = demo_rows()


def test_readme_has_a_demo_block_with_every_demo_row():
    simulate = [row for row in ROWS if " simulate " in row[0]]
    assert len(simulate) >= 8, "the demo block must hold every row of architecture section 7.4"
    assert {code for _, code, _ in simulate} >= {0, 1, 2, 3, 4}


@pytest.mark.parametrize(
    "command, exit_code, result", ROWS, ids=[row[0][len(PREFIX) :] for row in ROWS]
)
def test_each_demo_command_gives_what_the_readme_says(capsys, command, exit_code, result):
    argv = shlex.split(command)[3:]  # drop "python -m equinox"
    assert "--source" in argv and argv[argv.index("--source") + 1] == "fixtures"
    code = cli.main([*argv, "--json"])
    output = json.loads(capsys.readouterr().out)
    assert code == exit_code

    if argv[0] == "markets":
        assert len(output["markets"]) == _first_number(result)
    elif argv[0] == "match":
        assert len(output["clusters"]) == _first_number(result)
    else:
        assert output["status"] == re.match(r"[A-Z_]+", result).group(0)
        winner = re.search(r"to `([^`]+)`", result)
        assert (output["decision"] or {}).get("winner") == (winner and winner.group(1))
        totals = {Decimal(q["total_cost"]) for q in output["quotes"]}
        for amount in re.findall(r"\$([\d,]+(?:\.\d+)?)", result):
            assert Decimal(amount.replace(",", "")) in totals, f"${amount} is not a quoted total"


def _first_number(text: str) -> int:
    return int(re.search(r"\d+", text).group(0))


# Every reference the written deliverables make exists.

DECISIONS = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
ARCHITECTURE = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
VENUE_FACTS = (ROOT / "docs" / "research" / "venue_facts.md").read_text(encoding="utf-8")
KNOWN = {
    "decision": set(re.findall(r"^\| (D\d+) \|", DECISIONS, re.MULTILINE)),
    "assumption": set(re.findall(r"\*\*(A\d+):\*\*", DECISIONS)),
    "section": set(re.findall(r"^#{2,3} (\d+(?:\.\d+)?)[. ]", ARCHITECTURE, re.MULTILINE)),
    "venue fact": set(re.findall(r"^\| ([KPMS]\d+) \|", VENUE_FACTS, re.MULTILINE)),
}
CITED = {
    "decision": re.compile(r"\b(D\d+)\b"),
    "assumption": re.compile(r"\b(A\d)\b"),
    "section": re.compile(r"§\s?(\d+(?:\.\d+)?)"),
    "venue fact": re.compile(r"\b([KPMS]\d{1,2})\b"),
}


def test_the_reference_lists_were_read():
    assert {"D8", "D44"} <= KNOWN["decision"] and {"A1", "A5"} <= KNOWN["assumption"]
    assert {"3", "6.1", "9.3"} <= KNOWN["section"] and {"K9", "P7", "M3"} <= KNOWN["venue fact"]


@pytest.mark.parametrize("path", DELIVERABLES, ids=lambda p: p.name)
def test_every_reference_in_the_deliverables_exists(path):
    assert path.exists(), f"{path.name} is missing"
    text = path.read_text(encoding="utf-8")
    missing = {
        kind: sorted(set(pattern.findall(text)) - KNOWN[kind]) for kind, pattern in CITED.items()
    }
    assert not any(missing.values()), f"{path.name} cites references that don't exist: {missing}"
