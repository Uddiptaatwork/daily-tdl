import copy
from datetime import datetime, timezone
from functools import partial
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from server import Handler, Mailer, Store, due_jobs, run_due, validate_state


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def state():
    return {'version': 1, 'tasks': [
        {'id': 'one', 'title': 'Done task', 'date': '2026-10-19', 'priority': 'high', 'time': '', 'createdAt': '2026-10-19T06:00:00Z', 'completedAt': '2026-10-19T12:00:00Z', 'archived': False},
        {'id': 'two', 'title': 'Open task', 'date': '2026-10-19', 'priority': 'medium', 'time': '10:00', 'createdAt': '2026-10-19T06:00:00Z', 'completedAt': None, 'archived': False},
    ], 'days': {'2026-10-19': {'opened': True, 'created': True}},
        'settings': {'enabled': True, 'email': 'test@example.com', 'timezone': 'Europe/Zurich'}}


class FakeMailer:
    configured = True

    def __init__(self):
        self.messages = []
        self.fail = False

    def send(self, workspace, day, kind, tasks, settings):
        if self.fail:
            raise ConnectionError('Test SMTP failure')
        self.messages.append((workspace, day, kind, tasks, settings))


class SchedulingTests(unittest.TestCase):
    def test_exact_local_schedule_boundaries(self):
        data = state()
        self.assertEqual(due_jobs(data, at('2026-10-19T14:59:59Z')), [])
        evening = due_jobs(data, at('2026-10-19T15:00:00Z'))
        self.assertEqual([(d, k, [t['id'] for t in ts]) for d, k, ts in evening], [('2026-10-19', 'completed', ['one'])])
        self.assertEqual(due_jobs(data, at('2026-10-20T06:59:59Z')), [])
        morning = due_jobs(data, at('2026-10-20T07:00:00Z'))
        self.assertEqual([(d, k, [t['id'] for t in ts]) for d, k, ts in morning], [('2026-10-19', 'pending', ['two'])])

    def test_timezone_dst_changes_preserve_wall_clock(self):
        data = state()
        data['days'] = {'2026-10-25': {'opened': True, 'created': True}}
        data['tasks'][0]['completedAt'] = '2026-10-25T12:00:00Z'
        self.assertEqual(due_jobs(data, at('2026-10-25T15:59:59Z')), [])
        self.assertEqual(due_jobs(data, at('2026-10-25T16:00:00Z'))[0][1], 'completed')
        self.assertEqual(due_jobs(data, at('2026-10-26T07:59:59Z')), [])
        self.assertEqual(due_jobs(data, at('2026-10-26T08:00:00Z'))[0][1], 'pending')

    def test_requires_opt_in_and_both_activity_flags(self):
        data = state()
        for missing in ('opened', 'created'):
            sample = copy.deepcopy(data)
            sample['days']['2026-10-19'][missing] = False
            self.assertEqual(due_jobs(sample, at('2026-10-19T15:00:00Z')), [])
        data['settings']['enabled'] = False
        self.assertEqual(due_jobs(data, at('2026-10-19T15:00:00Z')), [])

    def test_no_old_backfill_or_future_task_leaks(self):
        data = state()
        self.assertEqual(due_jobs(data, at('2026-10-21T15:00:00Z')), [])
        future = copy.deepcopy(data['tasks'][1])
        future['date'], future['id'] = '2026-10-21', 'future'
        data['tasks'].append(future)
        self.assertEqual([t['id'] for t in due_jobs(data, at('2026-10-20T07:00:00Z'))[0][2]], ['two'])

    def test_cleared_completion_history_still_in_evening_digest(self):
        data = state()
        data['tasks'][0]['archived'] = True
        self.assertEqual(due_jobs(data, at('2026-10-19T15:00:00Z'))[0][2][0]['id'], 'one')
        data['tasks'][0]['completedAt'] = '2026-10-19T16:00:00Z'
        self.assertEqual(due_jobs(data, at('2026-10-19T17:00:00Z'))[0][2], [])

    def test_morning_uses_current_completion_status(self):
        data = state()
        data['tasks'][1]['completedAt'] = '2026-10-20T06:30:00Z'
        self.assertEqual(due_jobs(data, at('2026-10-20T07:00:00Z'))[0][2], [])

    def test_deliveries_survive_restart_and_empty_emails_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            store, mailer = Store(path), FakeMailer()
            store.save('workspace', state())
            run_due(store, mailer, at('2026-10-19T15:00:00Z'))
            run_due(Store(path), mailer, at('2026-10-19T15:05:00Z'))
            self.assertEqual(len(mailer.messages), 1)
            run_due(store, mailer, at('2026-10-20T07:00:00Z'))
            run_due(store, mailer, at('2026-10-20T07:01:00Z'))
            self.assertEqual(len(mailer.messages), 2)
            self.assertEqual(mailer.messages[1][2], 'pending')
            data = state()
            data['tasks'][0]['completedAt'] = None
            store.save('empty', data)
            run_due(store, mailer, at('2026-10-19T15:00:00Z'))
            self.assertEqual(len(mailer.messages), 2)

    def test_failed_delivery_retries_after_five_minutes(self):
        with tempfile.TemporaryDirectory() as directory:
            store, mailer = Store(Path(directory) / 'test.sqlite3'), FakeMailer()
            store.save('workspace', state())
            mailer.fail = True
            with self.assertLogs('daily', level='ERROR'):
                run_due(store, mailer, at('2026-10-19T15:00:00Z'))
            mailer.fail = False
            run_due(store, mailer, at('2026-10-19T15:04:59Z'))
            self.assertEqual(mailer.messages, [])
            run_due(store, mailer, at('2026-10-19T15:05:00Z'))
            self.assertEqual(len(mailer.messages), 1)


class ValidationTests(unittest.TestCase):
    def test_valid_snapshot_and_reject_bad_inputs(self):
        self.assertEqual(validate_state(state()), state())
        for change in (
            lambda d: d['settings'].update(email='test@example.com\r\nBcc: x@y.com'),
            lambda d: d['settings'].update(timezone='Invalid/Zone'),
            lambda d: d['tasks'][0].update(date='2026-02-30'),
            lambda d: d['tasks'][0].update(priority='invalid'),
            lambda d: d['tasks'][0].update(time='25:00'),
            lambda d: d['tasks'][0].update(completedAt='2026-10-19T09:00:00'),
            lambda d: d['tasks'].append(copy.deepcopy(d['tasks'][0])),
        ):
            data = state()
            change(data)
            with self.assertRaises(ValueError):
                validate_state(data)

    def test_smtp_transport_and_summary_format_without_sending(self):
        mailer = Mailer({'SMTP_HOST': 'smtp.example.com', 'SMTP_FROM': 'Daily <daily@example.com>', 'SMTP_USER': 'user', 'SMTP_PASSWORD': 'secret'})
        self.assertTrue(mailer.configured)
        data = state()
        with patch('server.smtplib.SMTP') as smtp:
            mailer.send('workspace', '2026-10-19', 'completed', [data['tasks'][0]], data['settings'])
            client = smtp.return_value.__enter__.return_value
            client.starttls.assert_called_once()
            client.login.assert_called_once_with('user', 'secret')
            message = client.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'test@example.com')
            self.assertIn('Done task', message.get_content())
            self.assertIn('Europe/Zurich', message.get_content())
        with self.assertRaises(ValueError):
            Mailer({'SMTP_SECURITY': 'none'})


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.directory.name) / 'test.sqlite3')
        cls.mailer = FakeMailer()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, store=cls.store, mailer=cls.mailer))
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join()
        cls.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=3)
        base = {'Content-Type': 'application/json', 'X-Workspace-Id': 'a' * 32}
        base.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, base)
        response = conn.getresponse()
        payload = response.read()
        status = response.status
        conn.close()
        return status, payload

    def test_static_and_status(self):
        code, body = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn(b'Daily', body)
        code, body = self.request('GET', '/api/status')
        self.assertEqual(json.loads(body)['service'], 'daily-planner')
        for path in ('/server.py', '/data/daily.sqlite3', '/.env', '/..%2Fserver.py'):
            self.assertEqual(self.request('GET', path)[0], 404)

    def test_save_restore_and_workspace_isolation(self):
        self.assertEqual(self.request('PUT', '/api/state', state())[0], 200)
        _, body = self.request('GET', '/api/state')
        self.assertEqual(json.loads(body)['state'], state())
        _, body = self.request('GET', '/api/state', headers={'X-Workspace-Id': 'b' * 32})
        self.assertIsNone(json.loads(body)['state'])
        self.assertEqual(self.request('PUT', '/api/state', state(), {'X-Workspace-Id': 'bad'})[0], 400)

    def test_cross_origin_and_rebinding_are_rejected(self):
        self.assertEqual(self.request('PUT', '/api/state', state(), {'Origin': 'https://external.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'external.example'})[0], 403)
        self.assertEqual(self.request('PUT', '/api/state', state(), {'Content-Type': 'text/plain'})[0], 415)

    def test_opt_in_requires_smtp_but_opt_out_is_saved(self):
        self.mailer.configured = False
        try:
            self.assertEqual(self.request('PUT', '/api/state', state())[0], 503)
            data = state()
            data['settings']['enabled'] = False
            self.assertEqual(self.request('PUT', '/api/state', data)[0], 200)
        finally:
            self.mailer.configured = True


if __name__ == '__main__':
    unittest.main()
