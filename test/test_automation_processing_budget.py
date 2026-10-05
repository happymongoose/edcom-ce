import os
import unittest
from unittest.mock import patch
import test_base  # establishes current-source import path
from api import automations


class TestProcessingBudget(unittest.TestCase):
    def run_budget(self, batch, budget="10", enabled=True, clock=None):
        with patch.dict(os.environ, {"automation_processing_budget_seconds": budget}), \
                patch.object(automations, "_process_eligible_automation_enrolments", side_effect=batch) as process, \
                patch.object(automations, "_customer_automation_processing_enabled", return_value=enabled), \
                patch.object(automations.time, "monotonic", side_effect=clock or (lambda: 0)):
            result = automations._process_automation_budget(None, "account", 100)
        return result, process.call_count

    def batch(self, succeeded=100, failed=0):
        return dict(processed=succeeded+failed, succeeded=succeeded, waiting=succeeded,
                    completed=0, exited=0, failed=failed, skipped_running=0, errors=[])

    def test_hard_batch_cap_even_if_clock_does_not_advance(self):
        result, calls = self.run_budget(lambda *args: self.batch())
        self.assertEqual(calls, 100)
        self.assertEqual(result["processed"], 10000)

    def test_no_progress_stops_without_spinning_on_claims(self):
        result, calls = self.run_budget(lambda *args: self.batch(0))
        self.assertEqual(calls, 1)
        self.assertEqual(result["processed"], 0)

    def test_failure_stops_further_batches(self):
        _, calls = self.run_budget(lambda *args: self.batch(1, 1))
        self.assertEqual(calls, 1)

    def test_account_disabled_between_batches_stops(self):
        _, calls = self.run_budget(lambda *args: self.batch(), enabled=False)
        self.assertEqual(calls, 1)

    def test_time_budget_clamped_to_thirty_seconds(self):
        _, calls = self.run_budget(lambda *args: self.batch(), budget="9999", clock=[0,31])
        self.assertEqual(calls, 1)

    def test_negative_budget_keeps_original_single_batch(self):
        _, calls = self.run_budget(lambda *args: self.batch(), budget="-5")
        self.assertEqual(calls, 1)
