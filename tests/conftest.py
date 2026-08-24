"""Collection policy for unavailable integration rehearsals."""

import os

collect_ignore = []


def pytest_ignore_collect(collection_path, config):
    if os.getenv("TEST_POSTGRES_DSN"):
        return False
    name = collection_path.name
    return name.startswith("test_postgres_") or name.startswith("test_e0_3_")
