"""Project Equinox."""

__version__ = "0.1.0"


def health() -> dict[str, object]:
    """Status payload served at /health and asserted in CI."""
    return {
        "name": "project-equinox",
        "status": "ok",
        "version": __version__,
        "hosts": ["github", "gitlab"],
    }
