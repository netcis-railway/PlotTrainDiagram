"""Read and fingerprint an uncommitted import source without changing its job."""

import json

from app.base_timetables.service import token, token_bytes
from app.ingest.base_service import ImportConflict


def import_source(c, base, job_id):
    row = c.execute(
        "SELECT state,filename,options,digest FROM base_tt_jobs WHERE id=? "
        "UNION ALL SELECT state,filename,options,digest FROM import_jobs WHERE id=? "
        "AND json_extract_string(options, '$.role')='result'",
        [job_id, job_id],
    ).fetchone()
    if not row or row[0] != "preview":
        raise ValueError("仅能修复尚未提交的导入预检，请重新预检")
    original = base.stage_path(job_id).read_bytes()
    if token_bytes(original) != row[3]:
        raise ImportConflict("暂存源文件已变化，请重新预检")
    options = json.loads(row[2])
    infrastructure = None
    if options.get("role") == "result":
        effective = base.resolve_state(base.state(c), options["batch_id"])
        infrastructure = (
            json.loads(base._row(c, effective["base_tt_id"])[5]) if effective["base_tt_id"] else {}
        )
    stamp = token([row, base.state(c), infrastructure])
    return original, options, infrastructure, stamp
