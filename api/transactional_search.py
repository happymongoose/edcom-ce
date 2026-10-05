def log_matches_search(record, search):
    search = (search or "").strip().lower()
    if not search:
        return True

    if not isinstance(record, dict):
        return False

    values = [
        record.get("to"),
        record.get("fromemail"),
        record.get("fromname"),
        record.get("toname"),
        record.get("subject"),
    ]

    return any(
        isinstance(value, str) and search in value.lower()
        for value in values
    )
