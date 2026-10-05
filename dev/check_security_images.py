"""Disposable image compatibility checks. Never connects to a real mail provider."""
import datetime
import json
import smtplib
import ssl
import sys
import unittest
import urllib.request
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def serve():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "proxy")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("proxy")]), False)
            .sign(key, hashes.SHA256()))
    Path("/config/private.key").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    Path("/config/certificate_chain.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    Path("/config/use_ssl").write_text("1")
    class Handler(BaseHTTPRequestHandler):
        requests = []
        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            self.reply(200, self.requests if self.path == "/requests" else {"path": self.path})
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/api/transactional/send"
            assert payload["to"] == "recipient@example.invalid"
            self.requests.append(payload)
            key = self.headers.get("X-Auth-APIKey")
            self.reply({"invalid": 401, "unavailable": 503, "bad-request": 400}.get(key, 200),
                       {"description": "Disposable rejection"})
        def log_message(self, *args):
            pass
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()


class ImageChecks(unittest.TestCase):
    def fetch(self, url, **kwargs):
        with urllib.request.urlopen(url, timeout=10, **kwargs) as response:
            return response.read()

    def test_postgres_and_transaction_pool(self):
        import psycopg2
        for port in (5432, 6432):
            with psycopg2.connect(host="database", port=port, user="edcom",
                                  password="edcom", dbname="edcom", connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute("SHOW server_version_num")
                    self.assertEqual(int(cur.fetchone()[0]) // 10000, 15)
                    cur.execute("CREATE TEMP TABLE image_probe (value text) ON COMMIT DROP")
                    cur.execute("INSERT INTO image_probe VALUES ('roundtrip') RETURNING value")
                    self.assertEqual(cur.fetchone()[0], "roundtrip")

    def test_proxy_http_https_and_tracking_routes(self):
        context = ssl.create_default_context(cafile="/config/certificate_chain.crt")
        for scheme in ("http", "https"):
            root = scheme + "://proxy"
            options = {"context": context} if scheme == "https" else {}
            home = self.fetch(root + "/", **options)
            self.assertIn(b"<html", home.lower())
            self.assertEqual(self.fetch(root + "/automations", **options), home)
            for path in ("/api/test", "/signup/test", "/l?id=fixture",
                         "/api/automations/fixture/publish-impact"):
                self.assertEqual(json.loads(self.fetch(root + path, **options)), {"path": path})

    def send(self, key=None, tls=False, port=2525):
        message = EmailMessage()
        message["From"] = "Fixture <sender@example.invalid>"
        message["To"] = "Recipient <recipient@example.invalid>"
        message["Subject"] = "Disposable image compatibility test"
        if key:
            message["X-Auth-APIKey"] = key
        message.set_content("No real delivery: isolated fake API only.")
        with smtplib.SMTP("relay", port, timeout=10) as smtp:
            smtp.ehlo()
            if tls:
                # The relay's generated certificate is self-signed; this tests STARTTLS,
                # not the operator's separately supplied public certificate.
                smtp.starttls(context=ssl._create_unverified_context())
                smtp.login("fixture", "valid")
            return smtp.send_message(message)

    def test_smtp_handoff_auth_errors_and_starttls(self):
        before = len(json.loads(self.fetch("http://api:8000/requests")))
        with self.assertRaises(smtplib.SMTPDataError) as error:
            self.send()
        self.assertEqual(error.exception.smtp_code, 503)
        self.assertIn(b"authentication failed", error.exception.smtp_error)
        self.assertEqual(len(json.loads(self.fetch("http://api:8000/requests"))), before)
        self.assertEqual(self.send("valid"), {})
        self.assertEqual(self.send(tls=True, port=587), {})
        self.assertEqual(self.send("valid", port=8025), {})
        for key, code, text in (("invalid", 503, b"invalid API key"),
                                ("unavailable", 451, b"Local error in processing"),
                                ("bad-request", 501, b"Disposable rejection")):
            with self.assertRaises(smtplib.SMTPDataError) as error:
                self.send(key)
            self.assertEqual(error.exception.smtp_code, code)
            self.assertIn(text, error.exception.smtp_error)
        requests = json.loads(self.fetch("http://api:8000/requests"))
        self.assertEqual(len(requests) - before, 6)
        self.assertTrue(all(item["to"] == "recipient@example.invalid" for item in requests))
        self.assertEqual(requests[-1]["subject"], "Disposable image compatibility test")


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        serve()
    else:
        unittest.main()
