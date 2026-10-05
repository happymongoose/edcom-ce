import os
import unittest
from unittest.mock import patch
import test_base
from api.shared.tasks import tasks


class TestTransactionalQueue(unittest.TestCase):
    def route(self, name, **options):
        return tasks.amqp.router.route(options, name)['queue'].name

    def test_opt_in_and_independent_interactive_routing(self):
        for flag, expected in [('false', 'celery'), ('', 'celery'), ('true', 'transactional'), ('True', 'transactional'), ('1', 'transactional')]:
            with self.subTest(flag=flag), patch.dict(os.environ, {
                'transactional_task_queue': flag, 'interactive_task_queue': 'true'
            }):
                self.assertEqual(self.route('api.transactional.send_txn'), expected)
                self.assertEqual(self.route('api.lists.list_find'), 'interactive')

    def test_only_transactional_orchestration_moves(self):
        with patch.dict(os.environ, {'transactional_task_queue': 'true', 'interactive_task_queue': 'false'}):
            for name in ('api.campaigns.send_queued_camp', 'api.shared.send.mailgun_send',
                         'api.automations.process_automation_enrolments_task',
                         'api.lists.list_find', 'future.task'):
                with self.subTest(name=name):
                    self.assertEqual(self.route(name), 'celery')

    def test_explicit_default_override(self):
        with patch.dict(os.environ, {'transactional_task_queue': 'true'}):
            self.assertEqual(self.route('api.transactional.send_txn', queue='celery'), 'celery')
