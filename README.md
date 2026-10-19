# Daily

A lightweight personal to-do list. Plain HTML, CSS, and JavaScript; no framework, packages, or build step.

## Use the task list

Open `index.html` in your browser, or serve this folder with any static server. Tasks save automatically in this browser. Browser storage must be available for changes to survive a reload.

- Choose a date in the sidebar or switch to **Month** and open a day. On smaller screens use **Month** to choose dates.
- Add tasks quickly in the day list, or use **New task** to set a date, priority, and optional time.
- Pending tasks appear in high → medium → low priority order, followed by completed tasks. You can also sort by time or added order.
- Click a task title to edit it. Deletion, unchecking all, and clearing completed tasks offer a brief Undo action. Bulk actions affect only the selected day.
- Existing `dailyWikiTodos` tasks are imported once into today's date with medium priority. Their text and completion state are preserved; the old storage key is left intact.

## Optional email reminders

Email needs a running server because a closed browser cannot send scheduled messages. The included server uses **Python 3.10+ and its standard library only**. On systems without an IANA timezone database, install your operating system's timezone data first.

Start it with:

```sh
python3 server.py
```

Open **http://localhost:8000**. If that port is occupied, use `python3 server.py --port 8765` and open the matching address. Use the same address/port consistently: browser storage is specific to each origin, so `file://`, `localhost`, and `127.0.0.1` have separate task lists. Existing browser-only tasks migrate automatically only when opened at the same origin where they were saved. There is no automatic transfer between origins or devices.

Set these environment variables before starting the server; `.env.example` lists the supported values. The server does not automatically load `.env` files.

| Variable | Meaning |
| --- | --- |
| `SMTP_HOST` | Your provider's SMTP hostname |
| `SMTP_PORT` | SMTP port; default `587` |
| `SMTP_SECURITY` | `starttls` (default), or `ssl` for implicit TLS, usually port `465` |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password or provider app password |
| `SMTP_FROM` | Sender address; defaults to `SMTP_USER` |

For example, in a shell where the credentials are already exported:

```sh
export SMTP_HOST=smtp.example.com
export SMTP_PORT=587
export SMTP_SECURITY=starttls
export SMTP_FROM=you@example.com
python3 server.py
```

Keep credentials out of source control and browser code. An SMTP relay that does not need authentication can omit both `SMTP_USER` and `SMTP_PASSWORD`; TLS is always required. A sender verified with your email provider may be necessary.

In **Email reminders**, enter your email and timezone, then opt in. When connected, preferences are saved only after the server accepts them. Opening settings does not send anything, and saving preferences does not send a test email; the scheduler may send an already-due summary on its next check. No email is sent unless SMTP is configured and you opt in.

### Delivery rules

- The date must have been **opened in the day view** and had a task added to it. Just browsing a month does not activate every date. Creating a task through the editor opens its date too.
- **5 p.m. in your chosen timezone:** a summary of tasks completed that calendar day by 17:00, including tasks originally scheduled for other dates. Clearing completed tasks from the list retains that completion history for email.
- **9 a.m. the next day:** tasks assigned to the previous date that remain unfinished when the reminder runs. Completed, deleted, and unrelated future tasks are excluded. Tasks remain on their original dates; the reminder does not automatically reschedule them.
- Empty emails are skipped. A task unchecked again before the summary runs no longer counts as completed. Completions after 5 p.m. are not included in that day's fixed 5 p.m. summary.
- The server checks every 30 seconds and stores sent/empty deliveries in SQLite, preventing repeat messages after a restart. Failed sends retry after five minutes, up to three attempts. A connection failure after SMTP accepted a message can still produce a duplicate on retry; the message ID stays stable.
- The server can send while the page is closed, using its latest saved snapshot. It must remain running, with internet access and the computer awake. If restarted later the same day, it catches up that day's due jobs; it does not send a backlog from older days. Late morning follow-ups use the latest saved completion status.
- Changes made while offline stay in this browser and sync when the page can reach the server again. Emails cannot reflect changes the server has not received. Keep the page open until the footer confirms a server save before closing it after changes.

### Data and scope

The task list stays in browser local storage. Running the optional server also stores snapshots, email preferences, and delivery records in `data/daily.sqlite3` (ignored by Git). Use `--db /path/to/daily.sqlite3` to change that location. Back up that file and browser storage if needed. Completed tasks cleared from the UI remain in the snapshot as history; unfinished deleted tasks are removed. This is a small personal tool with a 5,000-task snapshot limit, including retained history.

Each browser has its own random workspace key; it acts as a local access token. Clearing browser storage creates a new workspace and does not cancel reminders already saved on the server. Turn reminders off and wait for a server save **before** clearing browser data. To remove all server data, stop the server and remove its database (including any SQLite `-wal`/`-shm` files); this also removes all reminder preferences and delivery history.

The server binds only to loopback, validates request origins and hostnames, and serves only the app's public files. It is intended for personal use on this computer, not public hosting or a shared multi-user deployment. It does not include accounts, cloud sync, or a background operating-system service.

## Verify

No dependencies need installing:

```sh
node --test tests/*.test.js
python3 -m unittest discover -s tests -v
```

The JavaScript suite tests date and priority helpers plus task interactions, migration, undo, and rendering text literally through a small DOM harness. The Python suite tests the schedule, timezones and DST, eligibility, completion history, empty summaries, restart deduplication, retries, SMTP message construction with a fake transport, input validation, and the local HTTP API. Tests use temporary databases and fake email delivery; they never send real emails. The DOM harness checks behavior, not visual layout.

## Repository review

The original repo contained one `index.html` and a generic `.gitignore`. It had an undated list stored in `dailyWikiTodos`, add/toggle/delete actions, and global uncheck/clear buttons. Task text was inserted through `innerHTML`, allowing saved task content to be interpreted as markup. There were no dependencies, backend, tests, or mail configuration.

The updated app preserves the buildless approach. `model.js` holds date/sort/migration helpers, `app.js` handles browser interactions and optional snapshot sync, `styles.css` handles layout, and `server.py` adds only the persistence and scheduler needed for email. Task titles are now rendered through `textContent`.
