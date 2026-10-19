# Daily

A lightweight personal to-do list with a calendar, priorities, and optional task times. Plain HTML, CSS, and JavaScript; no framework, packages, accounts, or build step.

## Use

Open `index.html` in your browser, or publish this folder on GitHub Pages or another static host. The app needs no backend or configuration.

- Choose a date in the sidebar or switch to **Month** and open a day. On smaller screens use **Month** to choose dates.
- Add tasks quickly in the day list, or use **New task** to set a date, priority, and optional time.
- Pending tasks appear in high → medium → low priority order, followed by completed tasks. You can also sort by time or added order.
- Click a task title to edit it. Deletion, unchecking all, and clearing completed tasks offer a brief Undo action. Bulk actions affect only the selected day.
- Existing `dailyWikiTodos` tasks are imported once into today's date with medium priority. Their text and completion state are preserved; the old storage key is left intact.

## Privacy and storage

Tasks save automatically in this browser's local storage. The app makes no API requests and includes no analytics, third-party scripts, or external fonts. Dates follow the browser's timezone. There is no email collection, account, server-side task storage, or cloud sync.

Use the same browser and website address to access saved tasks. Other browsers, devices, private sessions, and website origins have separate storage. Clearing browser/site data removes saved tasks; blocked or full storage prevents changes from surviving a reload. Hosting providers still handle the normal requests needed to load the website's files.

When upgrading from the previous version, existing visible tasks are preserved. Obsolete contact preferences, the workspace identifier, and calendar activity records are removed from the app's browser storage. Previously cleared task history is also discarded. Deleted and cleared tasks are removed from saved state; Undo restores them during the short undo window.

## Verify

No dependencies need installing:

```sh
node --test tests/*.test.js
```

Tests cover date and priority helpers, task interactions, migration, undo, literal text rendering, removal of obsolete preferences, and the absence of API requests. The small DOM harness checks behavior, not visual layout.

## Files

- `index.html`: app layout and task editor.
- `styles.css`: responsive styling.
- `model.js`: date, sorting, and legacy task migration helpers.
- `app.js`: task interactions and browser storage.
- `tests/`: dependency-free Node tests.
