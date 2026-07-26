"""Console logging configuration."""

import logging


def configure_logging() -> None:
    """Configure application-wide console logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
