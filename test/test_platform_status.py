import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location(
    "platform_status", Path(__file__).resolve().parents[1] / "scripts/platform_status.py")
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


class TestPlatformStatus(unittest.TestCase):
    def healthy(self):
        return {"broker": {"available": True},
                "events": {"available": True, "held_requires_review": 0},
                "filesystems": {"buckets": {"available": True,
                    "bytes_total": 100, "bytes_available": 80,
                    "inodes_total": 100, "inodes_available": 80}}}

    def test_counts_all_priorities_without_reading_messages(self):
        broker = MagicMock()
        broker.pipeline.return_value.execute.side_effect = [[1, 2, 3, 4], [0]*4, [2]*4]
        broker.hlen.return_value = 3
        result = status.queue_depths(broker)
        self.assertEqual(result["waiting_tasks"], {"celery": 10, "interactive": 0, "transactional": 8})
        self.assertEqual(result["unacknowledged_tasks"], 3)
        self.assertEqual([call.args[0] for call in broker.pipeline.return_value.llen.call_args_list],
                         [q+s for q in ("celery", "interactive", "transactional") for s in ("", ":3", ":6", ":9")])
        broker.lrange.assert_not_called()
        broker.delete.assert_not_called()

    def test_errors_are_unknown_not_zero_and_hide_connection_details(self):
        def fail():
            raise OSError("secret password and private hostname")
        self.assertEqual(status.observe(fail), {"available": False, "error_type": "OSError"})
        result = self.healthy()
        result["broker"] = status.observe(fail)
        self.assertEqual(status.exit_status(result), 2)

    def test_healthy_exit_status(self):
        self.assertEqual(status.exit_status(self.healthy()), 0)

    def test_held_events_need_review(self):
        result = self.healthy()
        result["events"]["held_requires_review"] = 1
        self.assertEqual(status.exit_status(result), 1)

    def test_low_bytes_or_inodes_warn(self):
        for field in ("bytes_available", "inodes_available"):
            result = self.healthy()
            result["filesystems"]["buckets"][field] = 10
            self.assertEqual(status.exit_status(result), 1)

    def test_unavailable_filesystem_is_not_healthy(self):
        result = self.healthy()
        result["filesystems"]["buckets"] = {"available": False}
        self.assertEqual(status.exit_status(result), 2)

    def test_filesystem_reports_available_not_reserved_capacity(self):
        with patch.object(status.os, "statvfs", return_value=type("Stats", (), {
            "f_blocks": 100, "f_frsize": 4096, "f_bavail": 20,
            "f_files": 200, "f_favail": 15})()):
            self.assertEqual(status.filesystem("/fixture"), {"bytes_total": 409600,
                "bytes_available": 81920, "inodes_total": 200, "inodes_available": 15})
