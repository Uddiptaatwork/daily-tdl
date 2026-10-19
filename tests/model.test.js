const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../model.js');

test('calendar is Monday-first across leap days and year boundaries', () => {
  assert.equal(M.calendarDays('2026-02')[0], '2026-01-26');
  assert.equal(M.calendarDays('2026-02').length, 35);
  assert.ok(M.calendarDays('2024-02').includes('2024-02-29'));
  assert.equal(M.calendarDays('2026-12').at(-1), '2027-01-03');
  assert.equal(M.addDays('2026-12-31', 1), '2027-01-01');
});

test('invalid dates are rejected without throwing', () => {
  for (const key of ['2026-02-29', '2026-13-01', '2026-00-00', 'hi', null, '2026-2-01']) assert.equal(M.validDate(key), false);
  assert.equal(M.validDate('2024-02-29'), true);
});

test('date keys use the chosen timezone, including midnight and DST', () => {
  assert.equal(M.dateKey(new Date('2026-10-19T23:30:00Z'), 'Europe/Zurich'), '2026-10-20');
  assert.equal(M.dateKey(new Date('2026-10-25T23:30:00Z'), 'Europe/Zurich'), '2026-10-26');
  assert.equal(M.dateKey(new Date('2026-10-19T00:30:00Z'), 'America/Los_Angeles'), '2026-10-18');
});

test('priority sorting keeps completed tasks last, then uses time and added order', () => {
  const task = (id, priority, time = '', completedAt = null) => ({ id, priority, time, completedAt, createdAt: '2026-10-19T08:00:00Z' });
  const tasks = [task('a', 'low'), task('b', 'high', '', '2026-10-19T09:00:00Z'), task('c', 'medium', '08:00'), task('d', 'high'), task('e', 'high', '10:00')];
  assert.deepEqual(M.sortTasks(tasks).map(t => t.id), ['e', 'd', 'c', 'a', 'b']);
  assert.deepEqual(M.sortTasks(tasks, 'time').map(t => t.id), ['c', 'e', 'a', 'd', 'b']);
  assert.deepEqual(M.sortTasks(tasks, 'created').map(t => t.id), ['a', 'c', 'd', 'e', 'b']);
  assert.equal(tasks[0].id, 'a', 'sorting does not mutate saved tasks');
});

test('legacy tasks keep text and completion and migrate once into the current date', () => {
  let id = 0;
  const state = M.migrateLegacy([{ text: '<b>Real text</b>', completed: true }, { text: 'Next', completed: false }, { text: '' }, null], '2026-10-19', 'Europe/Zurich', () => String(++id), '2026-10-19T10:00:00Z');
  assert.equal(state.tasks.length, 2);
  assert.equal(state.tasks[0].title, '<b>Real text</b>');
  assert.equal(state.tasks[0].completedAt, '2026-10-19T10:00:00Z');
  assert.equal(state.tasks[1].completedAt, null);
  assert.deepEqual(state.days['2026-10-19'], { opened: true, created: true });
  assert.equal(state.settings.enabled, false);
});
