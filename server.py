#!/usr/bin/env python3
"""Optional personal server for Daily. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, parseaddr
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import signal
import smtplib
import sqlite3
import ssl
import threading
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
MAX_BODY = 2_000_000
LOG = logging.getLogger('daily')
ASSETS = {'/': ('index.html', 'text/html'), '/index.html': ('index.html', 'text/html'),
          '/styles.css': ('styles.css', 'text/css'), '/model.js': ('model.js', 'text/javascript'),
          '/app.js': ('app.js', 'text/javascript')}


def parse_instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('Invalid task timestamp.')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid task timestamp.') from None
    if instant.tzinfo is None:
        raise ValueError('Task timestamps must include a timezone.')
    return instant


def valid_day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid calendar date.')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError('Invalid calendar date.') from None
    if not 1900 <= parsed.year <= 2100:
        raise ValueError('Dates must be between 1900 and 2100.')
    return parsed


def validate_state(state):
    if not isinstance(state, dict) or state.get('version') != 1:
        raise ValueError('Unsupported task data.')
    tasks, days, settings = state.get('tasks'), state.get('days'), state.get('settings')
    if not isinstance(tasks, list) or len(tasks) > 5000 or not isinstance(days, dict) or len(days) > 20000 or not isinstance(settings, dict):
        raise ValueError('Invalid or oversized task data.')
    if not isinstance(settings.get('enabled'), bool):
        raise ValueError('Invalid email preference.')
    email = settings.get('email', '')
    if not isinstance(email, str) or len(email) > 254 or '\r' in email or '\n' in email:
        raise ValueError('Invalid email address.')
    if email and (parseaddr(email)[1] != email or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email)):
        raise ValueError('Enter a valid email address.')
    if settings['enabled'] and not email:
        raise ValueError('An email address is required for reminders.')
    zone = settings.get('timezone')
    if not isinstance(zone, str) or len(zone) > 100:
        raise ValueError('Invalid timezone.')
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Timezone is not available on this server.') from None
    ids = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError('Invalid task.')
        task_id = task.get('id')
        if not isinstance(task_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', task_id) or task_id in ids:
            raise ValueError('Invalid or duplicate task ID.')
        ids.add(task_id)
        title = task.get('title')
        if not isinstance(title, str) or not title.strip() or len(title) > 300 or any(ord(c) < 32 for c in title):
            raise ValueError('Task titles must be 1–300 characters on a single line.')
        valid_day(task.get('date'))
        if task.get('priority') not in ('high', 'medium', 'low'):
            raise ValueError('Invalid task priority.')
        if not isinstance(task.get('time'), str) or (task['time'] and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', task['time'])):
            raise ValueError('Invalid task time.')
        if not isinstance(task.get('archived'), bool):
            raise ValueError('Invalid task history.')
        parse_instant(task.get('createdAt'))
        if task.get('completedAt') is not None:
            parse_instant(task['completedAt'])
    for day, activity in days.items():
        valid_day(day)
        if not isinstance(activity, dict) or any(k not in ('opened', 'created') or not isinstance(v, bool) for k, v in activity.items()):
            raise ValueError('Invalid calendar activity.')
    return state


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
                workspace TEXT, day TEXT, kind TEXT, status TEXT NOT NULL,
                attempts INTEGER NOT NULL, attempted_at TEXT NOT NULL,
                PRIMARY KEY (workspace, day, kind))''')

    @contextmanager
    def connection(self):
        # Connections are intentionally per operation: request and scheduler threads do not share one.
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, workspace, state):
        with self.connection() as db:
            db.execute('INSERT INTO workspaces VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET state=excluded.state',
                       (workspace, json.dumps(state, separators=(',', ':'))))

    def load(self, workspace):
        with self.connection() as db:
            row = db.execute('SELECT state FROM workspaces WHERE id=?', (workspace,)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self):
        with self.connection() as db:
            rows = db.execute('SELECT id, state FROM workspaces').fetchall()
        return [(workspace, json.loads(state)) for workspace, state in rows]

    def claim(self, workspace, day, kind, now):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status, attempts, attempted_at FROM deliveries WHERE workspace=? AND day=? AND kind=?',
                             (workspace, day, kind)).fetchone()
            if row:
                status, attempts, attempted_at = row
                if status in ('sent', 'empty') or attempts >= 3 or now - parse_instant(attempted_at) < timedelta(minutes=5):
                    return False
                db.execute('UPDATE deliveries SET status=?, attempts=attempts+1, attempted_at=? WHERE workspace=? AND day=? AND kind=?',
                           ('sending', now.isoformat(), workspace, day, kind))
            else:
                db.execute('INSERT INTO deliveries VALUES (?, ?, ?, ?, 1, ?)',
                           (workspace, day, kind, 'sending', now.isoformat()))
            return True

    def finish(self, workspace, day, kind, status):
        with self.connection() as db:
            db.execute('UPDATE deliveries SET status=? WHERE workspace=? AND day=? AND kind=?',
                       (status, workspace, day, kind))


def due_jobs(state, now):
    """Only today's 17:00 digest and yesterday's 09:00 follow-up; never backfill older days."""
    settings = state['settings']
    if not settings['enabled']:
        return []
    zone = ZoneInfo(settings['timezone'])
    local = now.astimezone(zone)
    jobs = []
    for source, kind, due_date, hour in (
        (local.date(), 'completed', local.date(), 17),
        (local.date() - timedelta(days=1), 'pending', local.date(), 9),
    ):
        key = source.isoformat()
        activity = state['days'].get(key, {})
        if not activity.get('opened') or not activity.get('created'):
            continue
        cutoff = datetime.combine(due_date, time(hour), zone)
        if local < cutoff:
            continue
        if kind == 'completed':
            # Only completions up to 17:00 count, even if the server resumes later.
            tasks = [t for t in state['tasks'] if t.get('completedAt')
                     and parse_instant(t['completedAt']).astimezone(zone).date() == source
                     and parse_instant(t['completedAt']) <= cutoff]
        else:
            # The follow-up is for tasks on that calendar day, not unrelated future work.
            tasks = [t for t in state['tasks'] if t['date'] == key and not t.get('archived') and not t.get('completedAt')]
        tasks.sort(key=lambda t: ({'high': 0, 'medium': 1, 'low': 2}[t['priority']], t.get('time') or '99:99', t['createdAt'], t['id']))
        jobs.append((key, kind, tasks))
    return jobs


class Mailer:
    def __init__(self, environ=None):
        env = os.environ if environ is None else environ
        self.host = env.get('SMTP_HOST', '')
        self.port = int(env.get('SMTP_PORT', '587'))
        self.user = env.get('SMTP_USER', '')
        self.password = env.get('SMTP_PASSWORD', '')
        self.sender = env.get('SMTP_FROM', self.user)
        self.security = env.get('SMTP_SECURITY', 'starttls')
        if self.security not in ('starttls', 'ssl'):
            raise ValueError('SMTP_SECURITY must be starttls or ssl.')
        if bool(self.user) != bool(self.password):
            raise ValueError('Set both SMTP_USER and SMTP_PASSWORD, or neither for an authenticated relay.')
        if '\r' in self.sender or '\n' in self.sender:
            raise ValueError('Invalid SMTP_FROM.')
        self.configured = bool(self.host and parseaddr(self.sender)[1] and '@' in parseaddr(self.sender)[1])

    def send(self, workspace, day, kind, tasks, settings):
        message = EmailMessage()
        label = 'Your completed tasks' if kind == 'completed' else 'A few things for today'
        message['Subject'] = f'Daily · {label} · {day}'
        message['From'] = self.sender
        message['To'] = settings['email']
        message['Date'] = format_datetime(datetime.now(timezone.utc))
        message['Message-ID'] = f'<daily.{workspace}.{day}.{kind}@{parseaddr(self.sender)[1].split("@")[-1]}>'
        introduction = f'Here is what you completed on {day} by 17:00. Nicely done.' if kind == 'completed' else f'These tasks from {day} are still open. Take them one at a time.'
        lines = [introduction, '']
        lines.extend(f'{"✓" if kind == "completed" else "•"} {t["title"]} [{t["priority"]} priority]{" · " + t["time"] if t.get("time") else ""}' for t in tasks)
        lines.extend(['', f'Times use {settings["timezone"]}.', 'Manage or turn off these reminders in Daily → Email reminders.'])
        message.set_content('\n'.join(lines))
        context = ssl.create_default_context()
        smtp_class = smtplib.SMTP_SSL if self.security == 'ssl' else smtplib.SMTP
        kwargs = {'context': context} if self.security == 'ssl' else {}
        with smtp_class(self.host, self.port, timeout=20, **kwargs) as smtp:
            if self.security == 'starttls':
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)


def run_due(store, mailer, now=None):
    if not mailer.configured:
        return
    now = now or datetime.now(timezone.utc)
    for workspace, state in store.all():
        for day, kind, tasks in due_jobs(state, now):
            if not store.claim(workspace, day, kind, now):
                continue
            if not tasks:
                store.finish(workspace, day, kind, 'empty')
                continue
            try:
                mailer.send(workspace, day, kind, tasks, state['settings'])
            except Exception as error:
                # Log the exception type, never credentials, email addresses, or task text.
                LOG.error('Email delivery failed (%s); retrying in five minutes, up to three attempts.', type(error).__name__)
                store.finish(workspace, day, kind, 'failed')
            else:
                store.finish(workspace, day, kind, 'sent')
                LOG.info('Delivered a %s summary for %s.', kind, day)


def scheduler(store, mailer, stop):
    while not stop.is_set():
        try:
            run_due(store, mailer)
        except Exception as error:
            LOG.error('Scheduler check failed (%s).', type(error).__name__)
        stop.wait(30)


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, store, mailer, **kwargs):
        self.store, self.mailer = store, mailer
        super().__init__(*args, **kwargs)

    def log_message(self, *_args):
        pass  # Avoid logging user identifiers and request details.

    def reply(self, status, data, content_type='application/json'):
        body = json.dumps(data).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', f'{content_type}; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def workspace(self):
        workspace = self.headers.get('X-Workspace-Id', '')
        if not re.fullmatch(r'[a-f0-9-]{32,36}', workspace):
            raise ValueError('Invalid browser workspace.')
        return workspace

    def trusted_request(self):
        # Bind to loopback and reject DNS rebinding / cross-origin writes.
        host = self.headers.get('Host', '')
        allowed = {f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}'}
        if host not in allowed:
            self.reply(403, {'error': 'This personal server accepts localhost requests only.'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{host}', f'https://{host}'}:
            self.reply(403, {'error': 'Cross-origin requests are not allowed.'})
            return False
        return True

    def do_GET(self):
        if not self.trusted_request():
            return
        path = urlsplit(self.path).path
        if path == '/api/status':
            self.reply(200, {'service': 'daily-planner', 'emailConfigured': self.mailer.configured})
        elif path == '/api/state':
            try:
                self.reply(200, {'state': self.store.load(self.workspace())})
            except ValueError as error:
                self.reply(400, {'error': str(error)})
        elif path in ASSETS:
            filename, content_type = ASSETS[path]
            self.reply(200, (ROOT / filename).read_bytes(), content_type)
        else:
            self.reply(404, {'error': 'Not found.'})

    def do_PUT(self):
        if not self.trusted_request():
            return
        if urlsplit(self.path).path != '/api/state':
            self.reply(404, {'error': 'Not found.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            self.reply(415, {'error': 'Expected application/json.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > MAX_BODY:
                self.reply(413, {'error': 'Task data is too large or empty.'})
                return
            workspace = self.workspace()
            state = validate_state(json.loads(self.rfile.read(length)))
            if state['settings']['enabled'] and not self.mailer.configured:
                self.reply(503, {'error': 'Configure SMTP on the server before enabling reminders.'})
                return
            self.store.save(workspace, state)
            self.reply(200, {'saved': True})
        except (ValueError, TypeError, KeyError) as error:
            self.reply(400, {'error': str(error) if isinstance(error, ValueError) else 'Invalid task data.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', default=str(ROOT / 'data' / 'daily.sqlite3'))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    path = Path(args.db)
    path.parent.mkdir(parents=True, exist_ok=True)
    store, mailer, stop = Store(path), Mailer(), threading.Event()
    httpd = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, store=store, mailer=mailer))
    httpd.daemon_threads = True
    worker = threading.Thread(target=scheduler, args=(store, mailer, stop), daemon=True)
    worker.start()
    print(f'Daily is ready at http://localhost:{httpd.server_port}', flush=True)
    print('Email is configured.' if mailer.configured else 'Email is off. Set SMTP environment variables to enable it.', flush=True)
    def shutdown(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, shutdown)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()
        worker.join(timeout=25)


if __name__ == '__main__':
    main()
