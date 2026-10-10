"""Routing: walk each venue's book, add its fees, pick the cheapest eligible venue (section 7).

Pure functions. Imports only equinox.models, and names no venue: display names come from
each market's own `venue` field.
"""

from equinox.router.depth import walk
from equinox.router.engine import failure_trace, quote, simulate

__all__ = ["failure_trace", "quote", "simulate", "walk"]
