/* Shared, dependency-free date and task helpers; also used by the Node tests. */
(function (root) {
  'use strict';
  const PRIORITY = { high: 0, medium: 1, low: 2 };
  function dateKey(instant = new Date(), timezone) {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(instant);
    const part = type => parts.find(p => p.type === type).value;
    return `${part('year')}-${part('month')}-${part('day')}`;
  }
  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '1900-01-01' || value > '2100-12-31') return false;
    const parsed = new Date(`${value}T12:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
  }
  function addDays(key, count) {
    const date = new Date(`${key}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + count);
    return date.toISOString().slice(0, 10);
  }
  function formatDate(key, options) {
    return new Intl.DateTimeFormat('en-GB', { ...options, timeZone: 'UTC' }).format(new Date(`${key}T12:00:00Z`));
  }
  function calendarDays(month) {
    const first = `${month.slice(0, 7)}-01`;
    const offset = (new Date(`${first}T12:00:00Z`).getUTCDay() + 6) % 7;
    const next = new Date(`${first}T12:00:00Z`);
    next.setUTCMonth(next.getUTCMonth() + 1);
    const length = Math.ceil((offset + new Date(next.getTime() - 86400000).getUTCDate()) / 7) * 7;
    return Array.from({ length }, (_, index) => addDays(first, index - offset));
  }
  function sortTasks(tasks, order = 'priority') {
    return [...tasks].sort((a, b) => {
      if (Boolean(a.completedAt) !== Boolean(b.completedAt)) return a.completedAt ? 1 : -1;
      if (order === 'priority' && PRIORITY[a.priority] !== PRIORITY[b.priority]) return PRIORITY[a.priority] - PRIORITY[b.priority];
      if (order !== 'created' && (a.time || '99:99') !== (b.time || '99:99')) return (a.time || '99:99').localeCompare(b.time || '99:99');
      return a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id);
    });
  }
  function newState() {
    return { version: 1, tasks: [] };
  }
  function migrateLegacy(todos, today, idFactory, now) {
    const state = newState();
    if (!Array.isArray(todos)) return state;
    state.tasks = todos.filter(t => t && typeof t.text === 'string' && t.text.trim()).map(t => ({
      id: idFactory(), title: t.text.trim().slice(0, 300), date: today, priority: 'medium', time: '',
      createdAt: now, completedAt: t.completed ? now : null,
    }));
    return state;
  }
  const api = { PRIORITY, dateKey, validDate, addDays, formatDate, calendarDays, sortTasks, newState, migrateLegacy };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DailyModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
