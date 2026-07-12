import os
import sys
import falcon
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from api.transactional import Log, add_test_txn_log
import api.backends as backends
from api.shared.send import sender_domain, validate_sender_domains


class FakeDB:
    def __init__(self):
        self.executed = []
        self.cid = "cid-123"
        self.verified_domains = set()

    def get_cid(self):
        return self.cid

    def execute(self, query, *args):
        self.executed.append((query, args))
        return []

    def single(self, query, *args):
        self.executed.append((query, args))
        if "from clientdkim" in query and args[1] in self.verified_domains:
            return True
        return 0


class FakeReq:
    def __init__(self, params, db):
        self._params = params
        self.context = {"admin": False, "api": False, "db": db}

    def get_param(self, name, default=None):
        return self._params.get(name, default)


class FakeResp:
    pass


def test_add_test_txn_log_inserts_expected_transactional_entry():
    db = FakeDB()

    add_test_txn_log(
        db,
        "cid-123",
        "test@example.com",
        "Hello there",
        "mytag",
        "Sender",
        "sender@example.com",
        "Recipient",
        "route-1",
        "msg-1",
    )

    assert len(db.executed) == 1
    query, args = db.executed[0]

    assert "insert into txnsends" in query
    assert args[0] is not None
    assert args[1] == "cid-123"
    assert args[2] is not None
    assert args[3] == "msg-1"
    assert args[4]["event"] == "Injection"
    assert args[4]["status"] == "Queued"
    assert args[4]["to"] == "test@example.com"
    assert args[4]["subject"] == "Hello there"
    assert args[4]["tag"] == "mytag"
    assert args[4]["fromname"] == "Sender"
    assert args[4]["fromemail"] == "sender@example.com"
    assert args[4]["toname"] == "Recipient"
    assert args[4]["route"] == "route-1"


def test_log_filters_by_datetime_range():
    db = FakeDB()
    handler = Log()
    req = FakeReq({"start": "2026-07-08T10:00", "end": "2026-07-08T11:00"}, db)
    resp = FakeResp()

    handler.on_get(req, resp)

    assert len(db.executed) == 2
    query, args = db.executed[0]
    assert "where cid = %s" in query
    assert "and ts >= %s" in query
    assert "and ts <= %s" in query
    assert args[0] == db.cid
    assert args[1].year == 2026
    assert args[2].year == 2026


def test_sender_domain_parses_plain_and_formatted_addresses():
    assert sender_domain("sender@example.com") == "example.com"
    assert sender_domain("Sender <sender@Example.COM>") == "example.com"
    assert sender_domain("not-an-email") == ""


def test_validate_sender_domains_rejects_unverified_domain():
    db = FakeDB()

    try:
        validate_sender_domains(db, "cid-123", "Sender <sender@example.com>")
    except falcon.HTTPBadRequest:
        pass
    else:
        assert False, "Expected sender domain without verified DKIM to be rejected"


def test_validate_sender_domains_allows_verified_domain():
    db = FakeDB()
    db.verified_domains.add("example.com")

    validate_sender_domains(db, "cid-123", "sender@example.com")


def test_verify_client_dkim_dns_accepts_expected_txt_and_mx(monkeypatch):
    def fake_dns_query(name, qtype):
        if qtype == 16 and name == "a._domainkey.example.com":
            return ["v=DKIM1; p=abc123"]
        if qtype == 16 and name == "example.com":
            return ["v=spf1 include:mail.example.com ~all"]
        if qtype == 15 and name == "example.com":
            return ["10 mx1.mail.example.com"]
        return []

    monkeypatch.setattr(backends, "_dns_query", fake_dns_query)

    backends.verify_client_dkim_dns(
        {
            "serverentry": {
                "type": "TXT",
                "name": "a._domainkey.example.com",
                "value": "v=DKIM1; p=abc123",
            },
            "spfentry": {
                "type": "TXT",
                "name": "example.com",
                "value": "v=spf1 include:mail.example.com ~all",
            },
            "mx1entry": {
                "type": "MX",
                "name": "example.com",
                "value": "10 mx1.mail.example.com",
            },
        }
    )


def test_verify_client_dkim_dns_rejects_missing_record(monkeypatch):
    monkeypatch.setattr(backends, "_dns_query", lambda name, qtype: [])

    try:
        backends.verify_client_dkim_dns(
            {
                "serverentry": {
                    "type": "TXT",
                    "name": "a._domainkey.example.com",
                    "value": "v=DKIM1; p=abc123",
                },
            }
        )
    except falcon.HTTPBadRequest:
        pass
    else:
        assert False, "Expected missing DKIM DNS record to be rejected"
