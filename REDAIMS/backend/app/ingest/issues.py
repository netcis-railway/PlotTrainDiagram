"""Source node labels for actionable import diagnostics, including invalid rows."""


def node_context(node):
    result = {}
    for field in ("node_ind", "node_name", "node_name_chn"):
        value = node.get(field, node.get(field.upper()))
        if value is not None and value != "":
            result[field] = (
                value if field == "node_ind" and type(value) in (int, float) else str(value)
            )
    return result
