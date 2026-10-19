/* Small DOM harness to check browser behavior without installing a browser/package.
   This exercises events and saved data; it does not replace visual browser QA. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const M = require('../model.js');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.attributes = {}; this.handlers = {};
    this.dataset = {}; this.value = ''; this.className = ''; this.checked = false; this.hidden = false;
  }
  set textContent(value) { this.children = []; this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ''; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  async fire(type) { for (const fn of this.handlers[type] || []) await fn({ preventDefault() {} }); }
  click() { return this.fire('click'); }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  checkValidity() { return /.+@.+\..+/.test(this.value); }
  get classList() {
    return {
      contains: name => this.className.split(' ').includes(name),
      toggle: (name, on) => { this.className = this.className.split(' ').filter(c => c !== name).concat(on ? [name] : []).join(' '); },
    };
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(selector.startsWith('.') && child.classList.contains(selector.slice(1)) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
}

function boot(entries = {}) {
  const data = new Map(Object.entries(entries));
  const ids = new Map();
  const all = [];
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/g)) {
    const element = new Element(match[1]);
    for (const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) {
      element.attributes[attr[1]] = attr[2];
      if (attr[1] === 'id') ids.set(attr[2], element);
      if (attr[1] === 'class') element.className = attr[2];
      if (attr[1].startsWith('data-')) element.dataset[attr[1].slice(5)] = attr[2];
    }
    all.push(element);
  }
  const get = id => ids.get(id);
  get('sort-order').value = 'priority';
  get('quick-priority').value = 'medium';
  const document = {
    getElementById: get,
    createElement: tag => new Element(tag),
    createTextNode: text => { const el = new Element('#text'); el.textContent = text; return el; },
    querySelectorAll: selector => all.filter(el => selector === '[data-close]' ? Boolean(el.dataset.close) : selector.split(',').some(s => el.classList.contains(s.trim().slice(1)))),
  };
  const window = { DailyModel: M, addEventListener() {} };
  const localStorage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
  const context = { window, document, localStorage, crypto: webcrypto, Intl, Date, console, location: { protocol: 'file:' }, setTimeout: () => 1, clearTimeout() {}, setInterval() {} };
  vm.runInNewContext(fs.readFileSync(require.resolve('../app.js'), 'utf8'), context);
  return { get, data, saved: () => JSON.parse(data.get('dailyPlannerV1')), titles: () => get('task-groups').querySelectorAll('.task-title').map(el => el.textContent) };
}

async function quickAdd(app, title, priority) {
  app.get('quick-title').value = title;
  app.get('quick-priority').value = priority;
  await app.get('quick-add').fire('submit');
}

test('legacy text is rendered literally and only imported once', () => {
  const legacy = JSON.stringify([{ text: '<img src=x onerror=alert(1)>', completed: false }]);
  const app = boot({ dailyWikiTodos: legacy });
  assert.deepEqual(app.titles(), ['<img src=x onerror=alert(1)>']);
  assert.equal(app.get('task-groups').querySelectorAll('.task-title')[0].children.length, 0);
  assert.equal(boot(Object.fromEntries(app.data)).saved().tasks.length, 1);
  assert.equal(app.data.get('dailyWikiTodos'), legacy);
});

test('quick add sorts priorities, completion moves down, delete can be undone', async () => {
  const app = boot();
  await quickAdd(app, 'Low task', 'low');
  await quickAdd(app, 'High task', 'high');
  assert.deepEqual(app.titles(), ['High task', 'Low task']);
  const check = app.get('task-groups').querySelectorAll('.task-checkbox')[0];
  check.checked = true;
  await check.fire('change');
  assert.deepEqual(app.titles(), ['Low task', 'High task']);
  await app.get('task-groups').querySelectorAll('.delete-task')[0].click();
  assert.deepEqual(app.titles(), ['High task']);
  await app.get('undo-button').click();
  assert.deepEqual(app.titles(), ['Low task', 'High task']);
});

test('clearing completed tasks retains email history and undo restores the list', async () => {
  const app = boot({ dailyWikiTodos: JSON.stringify([{ text: 'Done', completed: true }]) });
  await app.get('clear-completed').click();
  assert.deepEqual(app.titles(), []);
  assert.equal(app.saved().tasks[0].archived, true);
  assert.ok(app.saved().tasks[0].completedAt);
  await app.get('undo-button').click();
  assert.deepEqual(app.titles(), ['Done']);
  assert.equal(app.saved().tasks[0].archived, false);
});

test('task editor chooses dates and bulk actions affect only that day', async () => {
  const app = boot({ dailyWikiTodos: JSON.stringify([{ text: 'Today done', completed: true }]) });
  const tomorrow = M.addDays(app.saved().tasks[0].date, 1);
  await app.get('new-task-button').click();
  app.get('task-title').value = 'Tomorrow task';
  app.get('task-date').value = tomorrow;
  app.get('task-priority').value = 'high';
  app.get('task-time').value = '09:00';
  await app.get('task-form').fire('submit');
  assert.deepEqual(app.titles(), ['Tomorrow task']);
  const check = app.get('task-groups').querySelectorAll('.task-checkbox')[0];
  check.checked = true;
  await check.fire('change');
  await app.get('uncheck-all').click();
  assert.ok(app.saved().tasks.find(t => t.title === 'Today done').completedAt);
  assert.equal(app.saved().tasks.find(t => t.title === 'Tomorrow task').completedAt, null);
  assert.deepEqual(app.saved().days[tomorrow], { created: true, opened: true });
});

test('email status is explicit and reminders cannot be enabled on a static page', async () => {
  const app = boot();
  assert.equal(app.get('reminder-note-title').textContent, 'Email reminders off');
  await app.get('setup-reminders').click();
  assert.equal(app.get('reminder-dialog').open, true);
  assert.equal(app.get('reminder-enabled').disabled, true);
  assert.match(app.get('service-status').textContent, /optional Python server/);
  assert.equal(app.saved().settings.enabled, false);
});
