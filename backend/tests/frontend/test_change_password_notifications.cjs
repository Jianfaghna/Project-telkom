// Run: node --test backend/tests/frontend/test_change_password_notifications.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../../templates/ganti_password.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(categories) {
  let now = 0;
  const timers = [];
  const messages = categories.map(category => ({
    category, removed: false,
    remove() { this.removed = true; },
  }));
  vm.runInNewContext(script, {
    document: {
      querySelectorAll(selector) {
        assert.equal(selector, '.gp-feedback-success');
        return messages.filter(message => message.category === 'success');
      },
    },
    setTimeout(callback, delay) { timers.push({callback, at: now + delay}); },
  });
  return {
    messages, timers,
    advance(ms) {
      now += ms;
      timers.filter(timer => !timer.fired && timer.at <= now).forEach(timer => {
        timer.fired = true;
        timer.callback();
      });
    },
  };
}

test('success remains visible for eight seconds then disappears', () => {
  const ctx = setup(['success']);
  ctx.advance(7999);
  assert.equal(ctx.messages[0].removed, false);
  ctx.advance(1);
  assert.equal(ctx.messages[0].removed, true);
});

test('errors and warnings remain visible even alongside a successful result', () => {
  const ctx = setup(['success', 'error', 'warning']);
  ctx.advance(60000);
  assert.deepEqual(ctx.messages.map(message => message.removed), [true, false, false]);
});

test('no timer is scheduled for an empty form or failed result', () => {
  for (const categories of [[], ['error']]) {
    assert.equal(setup(categories).timers.length, 0);
  }
});
