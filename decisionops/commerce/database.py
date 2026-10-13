"""Bounded PostgreSQL connections; URLs stay out of assessment/error output."""

import os
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def database_engine(url=None):
    url = url or os.environ.get("COMMERCE_DATABASE_URL")
    if not url:
        raise ValueError("Set COMMERCE_DATABASE_URL; see docs/commerce/RUNBOOK.md")
    try:
        parsed = make_url(url)
    except ArgumentError:
        raise ValueError("Invalid COMMERCE_DATABASE_URL format") from None
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError("Use a postgresql+psycopg database URL")
    return create_engine(
        url, connect_args={"connect_timeout": 3,
                           "options": parsed.query.get("options", "") + " -c timezone=UTC"}, pool_pre_ping=True,
        isolation_level="REPEATABLE READ", hide_parameters=True,
    )
