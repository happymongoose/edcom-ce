import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import SubjectTests from './AutomationSubjectTests';
jest.mock('axios', () => ({get: jest.fn(), post: jest.fn()}));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(b => b.textContent.trim() === text);
const click = node => TestUtils.Simulate.click(node);
const dialog = () => document.querySelector('.modal[role="dialog"]');
let root, saved, rows;
const fixture = () => ({id: 'experiment', status: 'collecting', version: 3, maximum_sends: 2000, hours: 24, metric: 'ctr', control_id: 'a', variants: [{id: 'a', subject: 'Control', weight: 50}, {id: 'b', subject: 'Challenger', weight: 50}], statistics: [{id: 'a', subject: 'Control', assigned: 10, recipients: 9, accepted: 10, deliveries: 8, opens: 4, clicks: 2, or_rate: 0.5, ctr: 0.25, ctor: 0.5}], changes: []});
beforeEach(() => {
  rows = []; saved = jest.fn(() => Promise.resolve(true));
  axios.get.mockImplementation(() => Promise.resolve({data: rows}));
  axios.post.mockImplementation(() => Promise.resolve({data: {}}));
  root = document.createElement('div'); document.body.appendChild(root);
});
afterEach(() => {ReactDOM.unmountComponentAtNode(root); document.body.removeChild(root); jest.resetAllMocks();});
async function mount() {ReactDOM.render(<SubjectTests automationId="automation" emailId="email" saveEmail={saved} />, root); await tick();}
function fill(label, value) {TestUtils.Simulate.change(root.querySelector('[aria-label="' + label + '"]'), {target: {value}});}
async function prepare() {await mount(); fill('Test subject 1', 'A'); fill('Test subject 2', 'B'); click(button(root, 'Start experiment')); await tick();}
it('creates only after explicit confirmation and successful email save', async () => {
  await prepare(); expect(axios.post).not.toHaveBeenCalled(); click(button(dialog(), 'Confirm')); await tick();
  expect(saved).toHaveBeenCalled(); expect(axios.post).toHaveBeenCalledWith('/api/automations/automation/emails/email/subject-tests', {action: 'start', previous_id: null, maximum_sends: 2000, hours: 24, metric: 'ctr', variants: [{subject: 'A', weight: 50}, {subject: 'B', weight: 50}]});
});
it('failed email save prevents experiment start', async () => {saved.mockImplementation(() => Promise.resolve(false)); await prepare(); click(button(dialog(), 'Confirm')); await tick(); expect(axios.post).not.toHaveBeenCalled();});
['Cancel', 'Close', 'Escape'].forEach(method => it('discards confirmation on ' + method, async () => {
  await prepare();
  if (method === 'Escape') {const e = new window.Event('keydown', {bubbles: true}); e.keyCode = 27; document.dispatchEvent(e);}
  else click(method === 'Close' ? dialog().querySelector('.close') : button(dialog(), method));
  await tick(); expect(axios.post).not.toHaveBeenCalled(); expect(saved).not.toHaveBeenCalled();
}));
it('prevents duplicate submission while pending', async () => {await prepare(); let resolve; axios.post.mockImplementation(() => new Promise(done => {resolve = done;})); click(button(dialog(), 'Confirm')); await tick(); expect(button(dialog(), 'Applying…').disabled).toBe(true); expect(axios.post.mock.calls.length).toBe(1); resolve({data: {}}); await tick();});
it('renders delivery-based OR CTR CTOR and immutable decision evidence', async () => {
  const t = fixture(); t.status = 'selected'; t.winner_id = 'b'; t.decision = {at: '2026-01-01', reason: 'highest_observed_rate', statistics: t.statistics}; rows = [t]; await mount();
  expect(root.textContent).toContain('25.00%'); expect(root.textContent).toContain('50.00%'); expect(root.textContent).toContain('Current winning subject: Challenger'); expect(root.textContent).toContain('This snapshot is fixed');
});
it('sends an explicit version-guarded manual winner and refreshes', async () => {rows = [fixture()]; await mount(); click(button(root, 'Use this subject')); await tick(); click(button(dialog(), 'Confirm')); await tick(); expect(axios.post.mock.calls[0][1]).toEqual({action: 'winner', experiment_id: 'experiment', version: 3, variant_id: 'a'}); expect(axios.get.mock.calls.length).toBe(2);});
it('shows stale or uncertain response without automatic resubmission', async () => {rows = [fixture()]; await mount(); axios.post.mockImplementation(() => Promise.reject({response: {data: {description: 'Reload experiment'}}})); click(button(root, 'Use this subject')); await tick(); click(button(dialog(), 'Confirm')); await tick(); expect(root.textContent).toContain('Reload experiment'); expect(axios.post.mock.calls.length).toBe(1);});
it('edits relative weights without sending until saved and supports pause at zero', async () => {rows = [fixture()]; await mount(); fill('Weight for Challenger', '0'); expect(axios.post).not.toHaveBeenCalled(); click(button(root, 'Save allocation')); await tick(); expect(axios.post.mock.calls[0][1].weights).toEqual({a: 50, b: 0});});
it('adds a challenger without modifying tested subjects', async () => {rows = [fixture()]; await mount(); fill('New challenger subject', 'Third'); click(button(root, 'Add challenger')); await tick(); expect(axios.post.mock.calls[0][1]).toEqual({action: 'challenger', experiment_id: 'experiment', version: 3, subject: 'Third', weight: 50});});
it('can seed the next experiment with the previous winning control', async () => {const t = fixture(); t.status = 'selected'; t.winner_id = 'b'; rows = [t]; await mount(); click(button(root, 'Use previous winner as control')); expect(root.querySelector('[aria-label="Test subject 1"]').value).toBe('Challenger');});

it('uses singular hour for a one-hour experiment', async () => {const t = fixture(); t.hours = 1; rows = [t]; await mount(); expect(root.textContent).toContain('1 hour · Winner by'); expect(root.textContent).not.toContain('1 hours');});
