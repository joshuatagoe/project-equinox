"""Write `evals/traps.json`: false same-bets the model read, found by the score parser (feat-11).

    python docs/research/build_traps.py <catalog file from before the parser>

On 2026-10-11 the full read (prompt feat-10.7) read seven exact-score pairs as the same bet whose
scores are reversed: Kalshi's "Racing Club De Lens wins 4-1" against Polymarket's "Racing Club de
Lens 1 - 4 Sporting CP". The score parser read them as different bets, and the raw texts agree.
Each pair is written in the labelled-pairs format, labelled different, with the texts the model
read. The catalog file is the one saved before the refresh that brought the parser.
"""

import json
import sqlite3
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "evals" / "traps.json"
TRAPS = (
    (
        "kalshi:KXUCLSCORE-26OCT13RCLSPO-RCL4SPO1",
        "polymarket:5134646",
        "Lens wins 4-1 vs Lens 1 - 4",
    ),
    (
        "kalshi:KXUCLSCORE-26OCT13RCLSPO-RCL5SPO1",
        "polymarket:5134657",
        "Lens wins 5-1 vs Lens 1 - 5",
    ),
    (
        "kalshi:KXSERIEA1HSCORE-26OCT12ATAVEN-ATA1VEN0",
        "polymarket:5292515",
        "1st half 1, 0 vs 0 - 1",
    ),
    ("kalshi:KXAFCCLSCORE-26OCT13ITJSAH-ITJ4SAH1", "polymarket:5452517", "Al-Ittihad 4-1 vs 1 - 4"),
    ("kalshi:KXAFCCLSCORE-26OCT12TRASHM-TRA2SHM0", "polymarket:5452136", "Tractor 2-0 vs 0 - 2"),
    ("kalshi:KXLALIGASCORE-26OCT10RVCATH-RVC4ATH1", "polymarket:5015171", "Rayo 4-1 vs Rayo 1 - 4"),
    ("kalshi:KXLIGAMXSCORE-26OCT11PACNCX-PAC4NCX1", "polymarket:5083208", "Pachuca 4-1 vs 1 - 4"),
)
WHY = (
    "Reversed score: Kalshi names the winner and its goals first; Polymarket writes the home "
    "team's goals first. Read as the same bet in the 2026-10-11 full read; the parser and both "
    "texts say otherwise."
)


def market(db: sqlite3.Connection, market_id: str) -> dict:
    query = (
        "SELECT e.venue, e.event_title, e.title, e.outcome_label, e.closes_at, t.rules, t.strike "
        "FROM entries e JOIN texts t ON t.market_id = e.market_id WHERE e.market_id = ?"
    )
    venue, event, title, label, closes, rules, strike = db.execute(query, (market_id,)).fetchone()
    return {
        "market_id": market_id,
        "venue": venue,
        "event_title": event,
        "title": title,
        "outcome_label": label,
        "closes_at": closes,
        "rules": rules,
        "strike": strike,
    }


def main(catalog: Path) -> None:
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: a gold set is never overwritten")
    db = sqlite3.connect(f"{catalog.resolve().as_uri()}?mode=ro", uri=True)
    items = [
        {
            "name": f"Reversed score: {name}",
            "label": "different",
            "why": WHY,
            "a": market(db, a),
            "b": market(db, b),
        }
        for a, b, name in TRAPS
    ]
    OUT.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(items)} traps written to {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
