from contextlib import contextmanager
from pathlib import Path
from threading import RLock

import duckdb
from app.storage.base_schema import initialize


class Database:
    """Serialize local writes; each operation owns its connection and transaction."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = RLock()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(str(self.path))
            try:
                connection.execute("BEGIN TRANSACTION")
                yield connection
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def initialize(self):
        with self.transaction() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS catalog_nodes (
                    id VARCHAR PRIMARY KEY,
                    kind VARCHAR NOT NULL,
                    parent_id VARCHAR,
                    name VARCHAR NOT NULL,
                    notes VARCHAR NOT NULL DEFAULT '',
                    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id VARCHAR PRIMARY KEY,
                    batch_id VARCHAR,
                    name VARCHAR NOT NULL,
                    run_no INTEGER NOT NULL DEFAULT 1,
                    origin_path JSON NOT NULL DEFAULT '[]'
                )
            """)

            initialize(connection)
