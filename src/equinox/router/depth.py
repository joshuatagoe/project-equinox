"""Walk one outcome's asks from the cheapest level (section 7.1, step 1)."""

from decimal import Decimal

from equinox.models import Fill, OutcomeBook


def walk(book: OutcomeBook, quantity: Decimal) -> tuple[list[Fill], Decimal]:
    """Take min(remaining, level quantity) from each ask until the order fills or levels run out.

    Returns the fills and the quantity filled, which is less than `quantity` on a thin book.
    """
    fills: list[Fill] = []
    remaining = quantity
    for level in book.asks:
        if remaining <= 0:
            break
        take = min(remaining, level.quantity)
        fills.append(Fill(price=level.price, quantity=take))
        remaining -= take
    return fills, quantity - remaining
