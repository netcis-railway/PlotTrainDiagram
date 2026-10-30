TABLES = [
    """CREATE TABLE IF NOT EXISTS import_jobs (
        id VARCHAR PRIMARY KEY, filename VARCHAR NOT NULL, digest VARCHAR NOT NULL,
        state VARCHAR NOT NULL, options JSON NOT NULL, report JSON,
        run_id VARCHAR, error VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp
    )""",
    """CREATE TABLE IF NOT EXISTS base_run_data (
        run_id VARCHAR PRIMARY KEY, role VARCHAR NOT NULL, user_id VARCHAR NOT NULL,
        network_id VARCHAR NOT NULL, date_base DATE NOT NULL, metadata JSON NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS nodes (
        id VARCHAR PRIMARY KEY, node_name VARCHAR UNIQUE NOT NULL,
        node_name_chn VARCHAR UNIQUE NOT NULL, node_code VARCHAR UNIQUE NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS network_node_maps (
        network_id VARCHAR, node_ind INTEGER, node_id VARCHAR NOT NULL,
        PRIMARY KEY(network_id, node_ind), UNIQUE(network_id, node_id)
    )""",
    """CREATE TABLE IF NOT EXISTS network_lines (
        network_id VARCHAR, line_ind INTEGER, line_id VARCHAR NOT NULL,
        line_code VARCHAR NOT NULL, PRIMARY KEY(network_id, line_ind),
        UNIQUE(network_id, line_code)
    )""",
    """CREATE TABLE IF NOT EXISTS run_nodes (
        run_id VARCHAR, node_id VARCHAR, data JSON NOT NULL, PRIMARY KEY(run_id, node_id)
    )""",
    """CREATE TABLE IF NOT EXISTS infrastructure_records (
        id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, kind VARCHAR NOT NULL, data JSON NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS run_trains (
        id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, train_course_id VARCHAR NOT NULL,
        train_base_date DATE NOT NULL, data JSON NOT NULL,
        UNIQUE(run_id, train_course_id, train_base_date)
    )""",
    """CREATE TABLE IF NOT EXISTS timetable_events (
        id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, train_id VARCHAR NOT NULL,
        node_id VARCHAR NOT NULL, train_course_id VARCHAR NOT NULL, node_name VARCHAR NOT NULL,
        node_name_chn VARCHAR NOT NULL, visit_seq INTEGER NOT NULL,
        arrival_hms VARCHAR, arrival_seconds BIGINT, arrival_day_offset INTEGER,
        departure_hms VARCHAR, departure_seconds BIGINT, departure_day_offset INTEGER,
        track_code INTEGER, source JSON NOT NULL, line_inds JSON NOT NULL,
        UNIQUE(run_id, train_id, visit_seq), UNIQUE(run_id, train_id, node_id)
    )""",
    """CREATE TABLE IF NOT EXISTS source_files (
        id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, job_id VARCHAR NOT NULL,
        filename VARCHAR NOT NULL, digest VARCHAR NOT NULL, managed_name VARCHAR UNIQUE NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS base_bindings (
        scope_id VARCHAR PRIMARY KEY, base_run_id VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS file_cleanup (
        managed_name VARCHAR PRIMARY KEY, error VARCHAR
    )""",
]


def initialize(connection):
    independent = [
        """CREATE TABLE IF NOT EXISTS run_workbooks (
            run_id VARCHAR PRIMARY KEY, managed_name VARCHAR UNIQUE NOT NULL,
            digest VARCHAR NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS base_tt_workbooks (
            base_tt_id VARCHAR PRIMARY KEY, managed_name VARCHAR UNIQUE NOT NULL,
            digest VARCHAR NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS base_timetables (
            id VARCHAR PRIMARY KEY, base_tt_no VARCHAR UNIQUE NOT NULL,
            owner_category_id VARCHAR UNIQUE NOT NULL, name VARCHAR NOT NULL,
            date_base DATE NOT NULL, document JSON NOT NULL, revision BIGINT NOT NULL DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS base_tt_sources (
            id VARCHAR PRIMARY KEY, base_tt_id VARCHAR NOT NULL, job_id VARCHAR NOT NULL,
            filename VARCHAR NOT NULL, digest VARCHAR NOT NULL, managed_name VARCHAR UNIQUE NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS base_tt_jobs (
            id VARCHAR PRIMARY KEY, filename VARCHAR NOT NULL, digest VARCHAR NOT NULL,
            state VARCHAR NOT NULL, options JSON NOT NULL, report JSON,
            base_tt_id VARCHAR, error VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp
        )""",
        """CREATE TABLE IF NOT EXISTS base_tt_migrations (
            old_run_id VARCHAR PRIMARY KEY, base_tt_id VARCHAR UNIQUE NOT NULL,
            snapshot JSON NOT NULL, created_at TIMESTAMP DEFAULT current_timestamp
        )""",
        """CREATE TABLE IF NOT EXISTS run_working_data (
            run_id VARCHAR PRIMARY KEY, date_base DATE NOT NULL,
            revision BIGINT NOT NULL DEFAULT 1
        )""",
    ]
    for statement in TABLES + independent:
        connection.execute(statement)
