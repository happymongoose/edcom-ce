import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import notify from '../utils/notify';
import Automation from './Automation';
import {shouldRemindAfterSave} from './AutomationSaveReminder';

jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn(), post: jest.fn()}));
jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('react-select2-wrapper', () => () => null);
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(node => node.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const click = node => TestUtils.Simulate.click(node);
let container, stored, preferences, originalStorage;
beforeEach(() => {
  preferences = {};
  originalStorage = Object.getOwnPropertyDescriptor(window, 'localStorage');
  Object.defineProperty(window, 'localStorage', {configurable: true, value: {
    getItem: key => preferences[key], setItem: (key, value) => {preferences[key] = value;},
  }});
  stored = {id: 'test', name: 'Reminder test', status: 'paused', entry: {type: 'manual'}, reentry: 'once',
    published_revision: 1, published_at: '2026-01-01', draft: {nodes: [{id: 'end', type: 'exit', label: 'Exit'}]}};
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/automations/test' ? stored :
    url.endsWith('/publish-impact') ? {review: {draft_fingerprint: 'd', published_fingerprint: 'p', published_revision: 1},
      sources: [], destinations: [], blockers: []} :
    url.includes('/enrolments') ? {summary: {}} : url.includes('/preflight') ? {} : []}));
  axios.patch.mockImplementation((url, data) => {stored = {...stored, ...data}; return Promise.resolve({data: stored});});
  axios.post.mockImplementation(() => Promise.resolve({data: {...stored, publication_receipt: {outcomes: []}}}));
  container = document.createElement('div'); document.body.appendChild(container);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);
  if (originalStorage) Object.defineProperty(window, 'localStorage', originalStorage);
  else delete window.localStorage;
  jest.resetAllMocks();
});
async function mount() {
  ReactDOM.render(<Automation history={{location: {search: ''}, push: jest.fn()}} match={{params: {id: 'test'}}} />, container);
  await tick();
}
async function save() {click(button(container, 'Save')); await tick();}

it('shows the reminder only after the draft save succeeds, without automatic publication', async () => {
  await mount(); let resolve;
  axios.patch.mockImplementation(() => new Promise(done => {resolve = done;}));
  await save(); expect(dialog()).toBe(null);
  resolve({data: stored}); await tick();
  expect(dialog().textContent).toContain('Saving does not update the live automation');
  expect(axios.post).not.toHaveBeenCalled();
  expect(axios.get.mock.calls.some(call => call[0].endsWith('/publish-impact'))).toBe(false);
});

it('does not show a publication reminder when saving fails', async () => {
  await mount(); axios.patch.mockImplementation(() => Promise.reject(new Error('save failed')));
  await save(); expect(dialog()).toBe(null); expect(axios.post).not.toHaveBeenCalled();
});

['Stay in draft', 'close', 'Escape'].forEach(action => {
  it('keeps the draft without publishing on ' + action, async () => {
    await mount(); await save();
    if (action === 'Escape') {
      const event = new window.Event('keydown', {bubbles: true}); event.keyCode = 27; document.dispatchEvent(event);
    } else click(action === 'close' ? dialog().querySelector('.close') : button(dialog(), action));
    await tick(); expect(axios.post).not.toHaveBeenCalled();
    expect(stored.status).toBe('paused');
    expect(shouldRemindAfterSave('test')).toBe(true);
  });
});

it('remembers opt-out for this automation only, without persisting it in workflow JSON', async () => {
  await mount(); await save();
  TestUtils.Simulate.change(dialog().querySelector('input[type="checkbox"]'), {target: {checked: true}});
  click(button(dialog(), 'Stay in draft'));
  expect(shouldRemindAfterSave('test')).toBe(false);
  expect(shouldRemindAfterSave('another')).toBe(true);
  await new Promise(resolve => setTimeout(resolve, 350));
  await save(); expect(dialog()).toBe(null);
  expect(axios.patch.mock.calls.length).toBe(2);
  expect(JSON.stringify(axios.patch.mock.calls)).not.toContain('reminder');
  expect(axios.post).not.toHaveBeenCalled();
});

it('enters the existing publish review only after the user chooses it, preserving pause', async () => {
  await mount(); await save();
  click(button(dialog(), 'Review and publish')); await tick(); await tick();
  expect(axios.get.mock.calls.some(call => call[0].endsWith('/publish-impact'))).toBe(true);
  expect(axios.post.mock.calls.length).toBe(1);
  expect(axios.post.mock.calls[0][0]).toBe('/api/automations/test/publish');
  expect(stored.status).toBe('paused');
  expect(document.querySelector('#automation-save-reminder-title')).toBe(null);
});

it('does not intercept a direct Publish click with a Save reminder', async () => {
  await mount(); click(button(container, 'Publish')); await tick(); await tick();
  expect(axios.post.mock.calls.length).toBe(1);
  expect(document.querySelector('#automation-save-reminder-title')).toBe(null);
});

it('still offers the reminder when browser preference storage is unavailable', () => {
  Object.defineProperty(window, 'localStorage', {configurable: true, get: () => {throw new Error('disabled');}});
  expect(shouldRemindAfterSave('test')).toBe(true);
});

[false, true].forEach(excluded => {
  it('does not save the draft or obscure enrolment feedback when excluded=' + excluded, async () => {
    await mount();
    if (excluded) axios.post.mockImplementation(() => Promise.reject({response: {data: {description: 'Contact matches an exit rule'}}}));
    const input = container.querySelector('input[placeholder="Existing contact email"]');
    TestUtils.Simulate.change(input, {target: {value: 'disposable@example.invalid'}});
    let form = input.parentNode;
    while (form.tagName !== 'FORM') form = form.parentNode;
    TestUtils.Simulate.submit(form);
    await tick();
    expect(axios.post.mock.calls[0]).toEqual(['/api/automations/test/enrolments', {email: 'disposable@example.invalid'}]);
    expect(axios.patch).not.toHaveBeenCalled();
    expect(notify.show).toHaveBeenCalledWith(excluded ? 'Contact matches an exit rule' : 'Contact enrolled', excluded ? 'error' : 'success');
    expect(dialog()).toBe(null);
  });
});
