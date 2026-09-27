"""Small local incident evaluation harness."""

LABELS = ("database_failure", "authentication_failure", "disk_full", "healthy")
DESCRIPTIONS = {
    "database_failure": "Database connections fail or time out.",
    "authentication_failure": "Access fails because credentials are invalid.",
    "disk_full": "Storage is exhausted and writes fail.",
    "healthy": "The service operates normally without errors.",
}
