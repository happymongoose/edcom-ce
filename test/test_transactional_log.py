from api.transactional_search import log_matches_search


def test_log_matches_search_matches_to_from_and_subject_fields():
    record = {
        "to": "recipient@example.com",
        "fromemail": "sender@example.com",
        "subject": "Welcome to the platform",
    }

    assert log_matches_search(record, "recipient")
    assert log_matches_search(record, "SENDER")
    assert log_matches_search(record, "welcome")
    assert not log_matches_search(record, "missing")
