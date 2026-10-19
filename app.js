/* Plain browser JavaScript. Tasks stay in this browser; no network requests. */
(() => {
  'use strict';
  const M = window.DailyModel;
  const $ = id => document.getElementById(id);
  const STORAGE_KEY = 'dailyPlannerV1';
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const uid = () => typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  let storageOK = true;
  let initialWarning = '';
  let state;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      state = restoreState(JSON.parse(saved));
    } else {
      const legacy = JSON.parse(localStorage.getItem('dailyWikiTodos') || '[]');
      state = M.migrateLegacy(legacy, M.dateKey(new Date(), timezone), uid, new Date().toISOString());
    }
  } catch {
    state = M.newState();
    storageOK = false;
    initialWarning = 'Saved data could not be read. Existing storage has been left untouched. Reload after checking browser storage.';
  }
  // Remove the obsolete local identifier used by the retired sync feature.
  try { localStorage.removeItem('dailyPlannerWorkspace'); } catch { /* Storage may be blocked. */ }
  let selected = today();
  let month = selected.slice(0, 7);
  let view = 'list';
  let editingId = null;
  let toastTimer, undoAction;
  let lastDay = today();

  function today() { return M.dateKey(new Date(), timezone); }
  function restoreState(saved) {
    if (saved.version !== 1 || !Array.isArray(saved.tasks)) throw new Error('Invalid saved data');
    // Keep visible tasks while discarding obsolete preferences and activity history.
    return { version: 1, tasks: saved.tasks.filter(task => !task.archived).map(task => ({
      id: task.id, title: task.title, date: task.date, priority: task.priority,
      time: task.time, createdAt: task.createdAt, completedAt: task.completedAt,
    })) };
  }
  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function notify(message, undo) {
    clearTimeout(toastTimer);
    $('toast-message').textContent = message;
    $('undo-button').hidden = !undo;
    $('toast').hidden = false;
    undoAction = undo;
    toastTimer = setTimeout(() => { $('toast').hidden = true; undoAction = null; }, undo ? 10000 : 7000);
  }
  function persist() {
    if (storageOK) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
      catch { storageOK = false; notify('Browser storage is full or unavailable. Changes may not survive a reload.'); }
    }
    if (!storageOK) $('storage-note').textContent = 'Browser storage unavailable. Keep this page open.';
  }
  function chooseDate(date, openList = true) {
    selected = date;
    month = date.slice(0, 7);
    if (openList) view = 'list';
    render();
  }
  function monthLabel() { return M.formatDate(`${month}-01`, { month: 'long', year: 'numeric' }); }
  function dayTasks(date) { return state.tasks.filter(task => task.date === date); }
  function renderCalendars() {
    $('mini-month').textContent = monthLabel();
    $('full-month-label').textContent = M.formatDate(`${month}-01`, { month: 'short', year: 'numeric' });
    $('mini-calendar').replaceChildren();
    $('month-grid').replaceChildren();
    const taskMap = new Map();
    state.tasks.forEach(t => taskMap.set(t.date, [...(taskMap.get(t.date) || []), t]));
    M.calendarDays(month).forEach(date => {
      const tasks = M.sortTasks(taskMap.get(date) || []);
      const classes = [date.slice(0, 7) !== month ? 'outside' : '', date === today() ? 'today' : '', date === selected ? 'selected' : ''].join(' ');
      const dayName = M.formatDate(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
      const mini = make('button', `mini-day ${classes} ${tasks.length ? 'has-tasks' : ''}`, Number(date.slice(-2)));
      mini.setAttribute('aria-label', `${dayName}, ${tasks.length} tasks`);
      mini.setAttribute('aria-pressed', String(date === selected));
      if (date === today()) mini.setAttribute('aria-current', 'date');
      mini.addEventListener('click', () => chooseDate(date));
      $('mini-calendar').append(mini);
      const cell = make('button', `month-cell ${classes}`);
      cell.setAttribute('aria-label', `${dayName}, ${tasks.length} tasks. Open day.`);
      if (date === today()) cell.setAttribute('aria-current', 'date');
      cell.append(make('span', 'month-number', Number(date.slice(-2))));
      tasks.slice(0, 2).forEach(task => cell.append(make('span', `month-task ${task.priority} ${task.completedAt ? 'done' : ''}`, task.title)));
      if (tasks.length > 2) cell.append(make('span', 'month-more', `+${tasks.length - 2} more`));
      cell.addEventListener('click', () => chooseDate(date));
      $('month-grid').append(cell);
    });
  }
  function render() {
    const tasks = dayTasks(selected);
    const completed = tasks.filter(task => task.completedAt).length;
    const remaining = tasks.length - completed;
    $('day-eyebrow').textContent = `${M.formatDate(selected, { weekday: 'long' }).toUpperCase()}${selected === today() ? ' · TODAY' : ''}`;
    $('day-title').textContent = M.formatDate(selected, { day: 'numeric', month: 'long' });
    $('day-subtitle').textContent = tasks.length ? `${remaining} ${remaining === 1 ? 'thing' : 'things'} to do. One at a time is enough.` : 'Your day, at your own pace.';
    $('progress-count').textContent = `${completed} / ${tasks.length}`;
    $('progress-label').textContent = !tasks.length ? 'A fresh start' : completed === tasks.length ? 'All done. Nicely done.' : 'Making progress';
    $('day-progress').max = tasks.length || 1;
    $('day-progress').value = completed;
    $('progress-message').textContent = !tasks.length ? 'Make a little room for what matters.' : `${completed} ${completed === 1 ? 'task' : 'tasks'} done. ${remaining ? 'Every small step counts.' : 'Enjoy a little breathing room.'}`;
    $('task-summary').textContent = `${tasks.length} ${tasks.length === 1 ? 'task' : 'tasks'} · ${completed} completed`;
    $('empty-state').hidden = tasks.length > 0;
    $('list-footer').hidden = !completed;
    $('list-panel').hidden = view !== 'list';
    $('calendar-panel').hidden = view !== 'calendar';
    $('sort-control').hidden = view !== 'list';
    $('full-month-nav').hidden = view !== 'calendar';
    ['list', 'calendar'].forEach(name => {
      $(`${name}-view`).classList.toggle('active', view === name);
      $(`${name}-view`).setAttribute('aria-pressed', String(view === name));
    });
    renderCalendars();
    const groups = $('task-groups');
    groups.replaceChildren();
    const ordered = M.sortTasks(tasks, $('sort-order').value);
    const pending = ordered.filter(t => !t.completedAt);
    if ($('sort-order').value === 'priority') {
      for (const priority of ['high', 'medium', 'low']) renderGroup(groups, pending.filter(t => t.priority === priority), `${priority[0].toUpperCase()}${priority.slice(1)} priority`, priority);
    } else renderGroup(groups, pending, 'To do', '');
    renderGroup(groups, ordered.filter(t => t.completedAt), 'Completed', '');
  }
  function renderGroup(container, tasks, label, priority) {
    if (!tasks.length) return;
    const section = make('section', 'task-group');
    const heading = make('h2', 'group-label');
    heading.append(make('span', `priority-dot ${priority}`), document.createTextNode(label), make('span', 'count', tasks.length));
    section.append(heading);
    const ul = make('ul', 'task-list');
    tasks.forEach(task => {
      const li = make('li', `task-row ${task.completedAt ? 'completed' : ''}`);
      const check = make('input', 'task-checkbox');
      check.type = 'checkbox';
      check.checked = Boolean(task.completedAt);
      check.setAttribute('aria-label', `Mark ${task.title} ${task.completedAt ? 'incomplete' : 'complete'}`);
      check.addEventListener('change', () => {
        task.completedAt = check.checked ? new Date().toISOString() : null;
        persist(); render();
        $('live-status').textContent = `${task.title} marked ${task.completedAt ? 'complete' : 'incomplete'}.`;
        // Re-rendering moves priority groups; restore keyboard focus to this task.
        const restored = [...$('task-groups').querySelectorAll('.task-checkbox')].find(el => el.dataset.id === task.id);
        restored?.focus({ preventScroll: true });
      });
      check.dataset.id = task.id;
      const main = make('div', 'task-main');
      const title = make('button', 'task-title', task.title);
      title.title = 'Edit task';
      title.setAttribute('aria-label', `Edit ${task.title}`);
      title.addEventListener('click', () => openTask(task));
      main.append(title);
      if (task.time) main.append(make('span', 'task-time', task.time));
      const remove = make('button', 'delete-task', '×');
      remove.setAttribute('aria-label', `Delete ${task.title}`);
      remove.addEventListener('click', () => {
        const snapshot = { ...task };
        state.tasks = state.tasks.filter(t => t.id !== task.id);
        persist(); render();
        notify('Task removed', () => {
          state.tasks = state.tasks.filter(t => t.id !== snapshot.id);
          state.tasks.push(snapshot);
          persist(); render();
        });
      });
      li.append(check, main, make('span', `priority-pill ${task.priority}`, task.priority[0].toUpperCase() + task.priority.slice(1)), remove);
      ul.append(li);
    });
    section.append(ul); container.append(section);
  }
  function addTask(title, date, priority, time = '') {
    state.tasks.push({ id: uid(), title, date, priority, time, createdAt: new Date().toISOString(), completedAt: null });
  }
  function openTask(task) {
    editingId = task?.id || null;
    $('task-dialog-title').textContent = task ? 'Edit your task' : 'A new task';
    $('task-title').value = task?.title || '';
    $('task-date').value = task?.date || selected;
    $('task-priority').value = task?.priority || 'medium';
    $('task-time').value = task?.time || '';
    $('task-dialog').showModal();
    $('task-title').focus();
  }
  $('quick-add').addEventListener('submit', event => {
    event.preventDefault();
    const title = $('quick-title').value.trim();
    if (!title) return;
    addTask(title, selected, $('quick-priority').value);
    $('quick-title').value = '';
    persist(); render();
    $('quick-title').focus();
    $('live-status').textContent = 'Task added.';
  });
  $('task-form').addEventListener('submit', event => {
    event.preventDefault();
    const title = $('task-title').value.trim();
    const date = $('task-date').value;
    if (!title || !M.validDate(date)) return;
    const task = state.tasks.find(t => t.id === editingId);
    if (task) {
      Object.assign(task, { title, date, priority: $('task-priority').value, time: $('task-time').value });
    } else addTask(title, date, $('task-priority').value, $('task-time').value);
    persist();
    chooseDate(date);
    $('task-dialog').close();
    notify(task ? 'Task updated' : 'Task added');
  });
  $('new-task-button').addEventListener('click', () => openTask());
  $('empty-add').addEventListener('click', () => $('quick-title').focus());
  $('today-button').addEventListener('click', () => chooseDate(today()));
  document.querySelectorAll('.prev-month, .next-month').forEach(button => button.addEventListener('click', () => {
    const date = new Date(`${month}-01T12:00:00Z`);
    date.setUTCMonth(date.getUTCMonth() + (button.classList.contains('next-month') ? 1 : -1));
    const nextMonth = date.toISOString().slice(0, 7);
    if (nextMonth >= '1900-01' && nextMonth <= '2100-12') { month = nextMonth; renderCalendars(); }
  }));
  $('list-view').addEventListener('click', () => { view = 'list'; month = selected.slice(0, 7); render(); });
  $('calendar-view').addEventListener('click', () => { view = 'calendar'; render(); });
  $('sort-order').addEventListener('change', render);
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
  $('uncheck-all').addEventListener('click', () => {
    const changed = dayTasks(selected).filter(t => t.completedAt).map(t => ({ id: t.id, completedAt: t.completedAt }));
    dayTasks(selected).forEach(t => { t.completedAt = null; });
    persist(); render();
    notify('Tasks unchecked for this day', () => { changed.forEach(old => { const task = state.tasks.find(t => t.id === old.id); if (task) task.completedAt = old.completedAt; }); persist(); render(); });
  });
  $('clear-completed').addEventListener('click', () => {
    const removed = dayTasks(selected).filter(t => t.completedAt);
    state.tasks = state.tasks.filter(t => !removed.includes(t));
    persist(); render();
    notify('Completed tasks cleared', () => { state.tasks.push(...removed); persist(); render(); });
  });
  $('undo-button').addEventListener('click', () => { undoAction?.(); undoAction = null; $('toast').hidden = true; });
  window.addEventListener('storage', event => {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try { state = restoreState(JSON.parse(event.newValue)); render(); } catch { /* Keep the current state if another tab writes invalid data. */ }
  });
  persist();
  render();
  if (initialWarning) notify(initialWarning);
  // Move to the new day at midnight when the current day is selected.
  setInterval(() => {
    const currentDay = today();
    if (currentDay !== lastDay) { if (selected === lastDay) chooseDate(currentDay); lastDay = currentDay; }
  }, 30000);
})();
