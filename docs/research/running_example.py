"""Running example and demo scenarios, from the snapshot in src/equinox/fixtures/.

Fed pair: Kalshi KXFEDDECISION-26OCT-H0 and Polymarket market 2589812 ("No change"), plus the
Kalshi C25 / Polymarket 2589811 ("25 bps decrease") pair. AAPL pair: Polymarket 5455686 ("$330")
and a synthetic Meridian book. Fees are summed per level and rounded up once per order (D13).

    python docs/research/running_example.py
"""

import json
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[2] / "src/equinox/fixtures/snapshot-2026-10-10"
KALSHI_COEFFICIENT, KALSHI_STEP = Decimal("0.07"), Decimal("0.01")  # series fee_multiplier is 1
POLY_STEP = Decimal("0.00001")

# Synthetic Meridian book for AAPL-330-2026-10-12 (the bot quotes 5 contracts a side; M3). Cents.
MERIDIAN_AAPL_330 = {"bids": [[93, 5]], "asks": [[95, 5]]}


def load(name: str) -> dict:
    return json.loads((SNAPSHOT / name).read_text(encoding="utf-8"), parse_float=Decimal)


def ladder(levels) -> list[tuple[Decimal, Decimal]]:
    return sorted(levels, key=lambda lvl: lvl[0])


def kalshi_books(ticker: str) -> dict:
    book = load(f"kalshi_orderbook_{ticker}.json")["orderbook_fp"]

    def asks(opposite):
        return ladder((1 - Decimal(p), Decimal(q)) for p, q in opposite)

    return {"YES": asks(book["no_dollars"]), "NO": asks(book["yes_dollars"])}


def polymarket_books(market_id: str) -> dict:
    def asks(side):
        book = load(f"polymarket_book_{market_id}_{side}.json")
        return ladder((Decimal(lvl["price"]), Decimal(lvl["size"])) for lvl in book["asks"])

    return {"YES": asks("yes"), "NO": asks("no")}


def meridian_books(book: dict) -> dict:
    yes_asks = ladder((Decimal(p) / 100, Decimal(q)) for p, q in book["asks"])
    no_asks = ladder((1 - Decimal(p) / 100, Decimal(q)) for p, q in book["bids"])
    return {"YES": yes_asks, "NO": no_asks}


def walk(asks, qty: Decimal, coefficient: Decimal, step: Decimal) -> dict:
    remaining, base, raw_fee, levels = qty, Decimal(0), Decimal(0), 0
    for price, size in asks:
        if remaining <= 0:
            break
        take = min(remaining, size)
        base += take * price
        raw_fee += coefficient * take * price * (1 - price)
        remaining -= take
        levels += 1
    filled = qty - remaining
    fee = (raw_fee / step).to_integral_value(rounding=ROUND_CEILING) * step
    return {
        "filled": filled,
        "levels": levels,
        "best": asks[0][0] if asks else None,
        "vwap": (base / filled).quantize(Decimal("0.0001")) if filled else None,
        "base": base.normalize(),
        "fee": fee.normalize(),
        "total": (base + fee).normalize(),
    }


def depth(asks) -> Decimal:
    return sum((size for _, size in asks), Decimal(0))


def main() -> None:
    hold = {
        "kalshi": (kalshi_books("KXFEDDECISION-26OCT-H0"), KALSHI_COEFFICIENT, KALSHI_STEP),
        "polymarket": (polymarket_books("2589812"), Decimal("0.05"), POLY_STEP),
    }
    cut25 = {
        "kalshi": (kalshi_books("KXFEDDECISION-26OCT-C25"), KALSHI_COEFFICIENT, KALSHI_STEP),
        "polymarket": (polymarket_books("2589811"), Decimal("0.05"), POLY_STEP),
    }
    aapl330 = {
        "meridian": (meridian_books(MERIDIAN_AAPL_330), Decimal(0), KALSHI_STEP),
        "polymarket": (polymarket_books("5455686"), Decimal("0.04"), POLY_STEP),
    }
    for name, cluster in (("hold", hold), ("cut25", cut25), ("aapl330", aapl330)):
        for outcome in ("YES", "NO"):
            sizes = {venue: str(depth(books[outcome])) for venue, (books, _, _) in cluster.items()}
            print(f"{name} {outcome} total ask depth: {sizes}")
    scenarios = [
        ("hold", hold, "YES", Decimal(100)),
        ("hold", hold, "NO", Decimal(100)),
        ("hold", hold, "NO", Decimal(5000)),
        ("cut25", cut25, "NO", Decimal(100)),
        ("aapl330", aapl330, "YES", Decimal(5)),
        ("aapl330", aapl330, "YES", Decimal(10)),
    ]
    for name, cluster, outcome, qty in scenarios:
        print(f"\n{name}: buy {qty} {outcome}")
        for venue, (books, coefficient, step) in cluster.items():
            print(f"  {venue:10s} {walk(books[outcome], qty, coefficient, step)}")


if __name__ == "__main__":
    main()
