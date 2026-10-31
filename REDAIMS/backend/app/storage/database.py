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

            connection.execute("""
                CREATE TABLE IF NOT EXISTS run_solver_logs (
                    id VARCHAR PRIMARY KEY,
                    run_id VARCHAR NOT NULL,
                    filename VARCHAR NOT NULL,
                    size_bytes BIGINT NOT NULL,
                    digest VARCHAR NOT NULL,
                    content BLOB NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                    UNIQUE (run_id, filename, digest)
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS run_diagram_views (
                    id VARCHAR PRIMARY KEY,
                    run_id VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    state JSON NOT NULL,
                    snapshot JSON NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
                    UNIQUE (run_id, name)
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS run_analysis_nodes (
                    id VARCHAR PRIMARY KEY,
                    run_id VARCHAR NOT NULL,
                    node_type VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    state JSON NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
                    UNIQUE (run_id, node_type, name)
                )
            """)

            for table in ("run_analysis_nodes", "run_diagram_views", "run_solver_logs"):
                if table != "run_solver_logs":
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS notes VARCHAR DEFAULT ''"
                    )
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                    "section_notes JSON DEFAULT '{}'"
                )
            connection.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS notes VARCHAR DEFAULT ''")
            connection.execute(
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS analysis_notes JSON DEFAULT '{}'"
            )

            initialize(connection)
            for column in (
                "solver_type VARCHAR DEFAULT 'unknown'",
                "default_plotter VARCHAR",
                "detection JSON DEFAULT '{}'",
                "best_objective DOUBLE",
                "solve_seconds DOUBLE",
                "objective_source VARCHAR DEFAULT 'unavailable'",
                "time_source VARCHAR DEFAULT 'unavailable'",
                "result_extraction JSON DEFAULT '{}'",
            ):
                connection.execute(f"ALTER TABLE run_solver_logs ADD COLUMN IF NOT EXISTS {column}")

            connection.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id VARCHAR PRIMARY KEY, name VARCHAR UNIQUE NOT NULL,
                    owner_category_id VARCHAR NOT NULL, notes VARCHAR NOT NULL DEFAULT '',
                    revision BIGINT NOT NULL DEFAULT 1
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS experiment_members (
                    experiment_id VARCHAR NOT NULL, run_id VARCHAR NOT NULL,
                    PRIMARY KEY (experiment_id, run_id)
                )
            """)
