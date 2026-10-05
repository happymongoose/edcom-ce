import os
import subprocess
import sys
import unittest


class TestWorkerConcurrency(unittest.TestCase):
    def command(self, value):
        env = dict(os.environ, EDCOM_CELERY_CONCURRENCY=value)
        return subprocess.run([sys.executable, "/scripts/num_tasks.py", "celery"],
                              env=env, capture_output=True, text=True)

    def test_small_worker_override(self):
        result = self.command("2")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "2")

    def test_invalid_override_fails_explicitly(self):
        for value in ("0", "65", "no", "2.5"):
            with self.subTest(value=value):
                result = self.command(value)
                self.assertEqual(result.returncode, 1)
                self.assertIn("1 to 64", result.stderr)
