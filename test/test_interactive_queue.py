import os
import unittest
from unittest.mock import patch
import test_base
from api.shared.tasks import tasks, route_interactive_task


class TestInteractiveQueue(unittest.TestCase):
    def test_disabled_preserves_default(self):
        with patch.dict(os.environ, {"interactive_task_queue":"false"}):
            self.assertIsNone(route_interactive_task('api.lists.list_find', (), {}, {}))

    def test_only_parent_and_child_route_to_interactive(self):
        with patch.dict(os.environ, {"interactive_task_queue":"true"}):
            for name in ('api.lists.list_find_start','api.lists.list_find'):
                self.assertEqual(tasks.amqp.router.route({},name)['queue'].name,'interactive')
            for name in ('api.campaigns.send_queued_camp','api.lists.export_list',
                         'api.automations.process_automation_enrolments_task','future.task'):
                self.assertEqual(tasks.amqp.router.route({},name)['queue'].name,'celery')

    def test_explicit_legacy_queue_still_supported(self):
        with patch.dict(os.environ, {"interactive_task_queue":"true"}):
            self.assertEqual(tasks.amqp.router.route({'queue':'celery'},'api.lists.list_find_start')['queue'].name,'celery')
