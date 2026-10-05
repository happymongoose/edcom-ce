import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import Automation from './Automation';
import AutomationWorkflowEditor, {automationWorkflowPreviewFlow} from './AutomationWorkflowEditor';
import pendingRemovals from './automationPendingRemovals';

jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn(), post: jest.fn()}));

const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, label) => Array.from(root.querySelectorAll('button')).find(el => el.textContent.trim() === label);
const wait = id => ({id, label: 'Wait', type: 'wait_duration', duration: {days: 2, hours: 0, minutes: 0}});
const nodes = () => [wait('a'), wait('b'), {id: 'exit', type: 'exit', label: 'Exit automation'}];
const base = '/api/automations/test';
let container, owner, editor, stored, summary;
const cards = () => Array.from(container.querySelectorAll('.automation-pending-removal'));
const modal = () => document.querySelector('.modal[role="dialog"]');

beforeEach(() => {
  stored = {id: 'test', name: 'Pending removal test', status: 'paused', published_at: '2026-01-01',
    entry: {type: 'manual'}, reentry: 'once', draft: {nodes: nodes()}, published: {nodes: nodes()}};
  summary = {nodes: {a: 1}, node_positions: {'1': 1}};
  axios.get.mockImplementation(url => Promise.resolve({data: url === base ? clone(stored) :
    url.endsWith('/publish-impact') ? {review: {draft_fingerprint: 'a'.repeat(64), published_fingerprint: 'b'.repeat(64), published_revision: 1},
      sources: [{node_id: 'a', label: 'Wait', type: 'wait_duration', enrolment_count: 1}],
      destinations: stored.draft.nodes.map(node => ({node_id: node.id, label: node.label, type: node.type})), blockers: []} :
    url.indexOf('/enrolments') >= 0 ? {summary} : url.indexOf('/preflight') >= 0 ? {} : []}));
  axios.patch.mockImplementation((url, data) => {stored = {...stored, ...clone(data)}; return Promise.resolve({data: clone(stored)});});
  axios.post.mockImplementation(() => {
    stored.published = clone(stored.draft); summary = {nodes: {b: 1}};
    return Promise.resolve({data: {...clone(stored), publication_receipt: {outcomes: [{action: 'move', enrolment_count: 1}]}}});
  });
  container = document.createElement('div'); document.body.appendChild(container);
});
afterEach(() => {ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container); jest.resetAllMocks();});
async function mount() {
  owner = ReactDOM.render(<Automation match={{params: {id: 'test'}}} history={{location: {search: ''}}} />, container);
  await tick(); editor = TestUtils.findRenderedComponentWithType(owner, AutomationWorkflowEditor);
  TestUtils.Simulate.click(button(container, 'Edit list'));
}
function removeFirst() {TestUtils.Simulate.click(button(container, 'Delete'));}
async function review() {TestUtils.Simulate.click(button(container, 'Publish')); await tick();}
function selectMove() {
  TestUtils.Simulate.change(document.getElementById('migration-action-a'), {target: {value: 'move'}});
  TestUtils.Simulate.change(document.getElementById('migration-destination-a'), {target: {value: 'b'}});
}

it('anchors first, consecutive and last removals using published neighbours', () => {
  const published = [wait('a'), wait('b'), wait('c'), wait('d')];
  expect(pendingRemovals(published, [published[2]]).map(item => [item.node.id, item.anchorId, item.side, item.publishedStep]))
    .toEqual([['a', 'c', 'before', 1], ['b', 'c', 'before', 2], ['d', 'c', 'after', 4]]);
});
it('uses fallback for reversed neighbours or no survivors without changing draft order', () => {
  const published = nodes(); const draft = [published[2], published[0]]; const before = clone(draft);
  expect(pendingRemovals(published, draft)[0].anchorId).toBe(null);
  expect(pendingRemovals(published, []).map(item => item.node.id)).toEqual(['a', 'b', 'exit']);
  expect(draft).toEqual(before);
});
it('uses exact IDs, deduplicates published IDs, and ignores retained settings and draft-only deletions', () => {
  expect(pendingRemovals([wait('a')], [wait('a'), wait('new')])).toEqual([]);
  expect(pendingRemovals([wait('a')], [{...wait('a'), label: 'Changed'}])).toEqual([]);
  expect(pendingRemovals([wait('a'), wait('a')], [wait('A')]).map(item => item.node.id)).toEqual(['a']);
});
it('shows the occupied published card inline immediately, with the exact View link and no edit controls', async () => {
  await mount(); removeFirst(); const card = cards()[0];
  expect(card.textContent).toContain('Published step 1 · Wait'); expect(card.textContent).toContain('Wait: 2 days');
  expect(card.textContent).toContain('1 live contact'); expect(card.textContent).toContain('Still live until you publish.');
  expect(card.querySelector('a').getAttribute('href')).toBe(base.replace('/api', '') + '/enrolments?view=active&node_id=a');
  expect(card.querySelector('a').textContent).toBe('View contacts');
  expect(card.querySelectorAll('button, input, select').length).toBe(0);
  const wrapper = card.parentNode;
  expect(wrapper.firstChild).toBe(card); expect(wrapper.textContent).toContain('Step 1 (0 live contacts)');
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['b', 'exit']);
  expect(axios.get.mock.calls.filter(call => call[0].endsWith('/publish-impact')).length).toBe(0);
  expect(editor.nodeTargetOptions(owner.state.data.draft.nodes[0]).some(option => option.id === 'a')).toBe(false);
});
it('keeps consecutive cards in published order and distinguishes identical labels', async () => {
  await mount(); removeFirst(); removeFirst();
  expect(cards().map(card => card.getAttribute('data-node-id'))).toEqual(['a', 'b']);
  expect(cards()[1].textContent).toContain('Published step 2 · Wait');
  expect(cards()[1].textContent).toContain('0 live contacts');
});
it('uses a labelled fallback after neighbours reverse, while survivors keep canonical order and counts', async () => {
  await mount(); owner.updateData({draft: {nodes: {$set: [nodes()[2], nodes()[0]]}}});
  expect(container.querySelector('[aria-label="Other pending removals"]')).not.toBe(null);
  expect(cards()[0].getAttribute('data-node-id')).toBe('b');
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['exit', 'a']);
  expect(container.textContent).toContain('Step 2 (1 live contact');
});
it('removes the pending designation when the ID returns and never marks a removed draft-only node', async () => {
  await mount(); removeFirst(); owner.updateData({draft: {nodes: {$set: nodes()}}}); expect(cards().length).toBe(0);
  owner.updateData({draft: {nodes: {$set: nodes().concat(wait('new'))}}}); editor.deleteNode(3);
  expect(cards().length).toBe(0);
});
[undefined, {}, {nodes: null}, {nodes: {a: null}}].forEach(unavailable => {
  it('does not turn unavailable counts into zero: ' + JSON.stringify(unavailable), async () => {
    summary = unavailable; await mount(); removeFirst();
    expect(cards()[0].textContent).toContain('Live contact count unavailable');
    expect(cards()[0].textContent).not.toContain('0 live'); expect(cards()[0].querySelector('a').getAttribute('href')).toContain('node_id=a');
  });
});
it('keeps zero-count removals visible with a usable View link', async () => {
  summary = {nodes: {}}; await mount(); removeFirst();
  expect(cards()[0].textContent).toContain('0 live contacts');
  expect(cards()[0].querySelector('a').getAttribute('disabled')).toBe(null);
});
it('shows visual annotations outside the unchanged draft graph, then remains visible in Edit list', async () => {
  await mount(); removeFirst(); const before = automationWorkflowPreviewFlow(owner.state.data.draft.nodes);
  TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(cards().length).toBe(1); expect(cards()[0].parentNode.className).toBe('automation-pending-annotations');
  expect(automationWorkflowPreviewFlow(owner.state.data.draft.nodes)).toEqual(before);
  expect(container.querySelector('button[aria-label*="Edit Wait step 1:"]').textContent).not.toContain('Pending removal');
  TestUtils.Simulate.click(button(container, 'Edit list')); expect(cards().length).toBe(1);
});
it('shows unrendered-anchor removals in the preview fallback', async () => {
  stored.published.nodes = [nodes()[2], wait('a'), wait('b')]; stored.draft.nodes = [nodes()[2], wait('b')];
  await mount(); TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(container.querySelector('[aria-label="Other pending removals"] .automation-pending-removal')).not.toBe(null);
});
it('keeps removals discoverable when the draft is empty or the preview is unavailable on narrow screens', async () => {
  await mount(); removeFirst(); TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(container.querySelector('.automation-workflow-visual-preview-narrow-message').textContent).toContain('1 pending removal still live');
  TestUtils.Simulate.click(button(container, 'View pending removals in Edit list')); expect(cards().length).toBe(1);
  owner.updateData({draft: {nodes: {$set: []}}}); TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(cards().map(card => card.getAttribute('data-node-id'))).toEqual(['a', 'b', 'exit']);
  expect(container.querySelector('[aria-label="Other pending removals"]')).not.toBe(null);
});
it('renders one annotation even if its anchor is shared by both preview lanes', async () => {
  const branch = {id: 'branch', type: 'if_has_tag', draft_tag: 'test', label: 'Branch', yes_node_id: 'b', no_node_id: 'b'};
  stored.published.nodes = [branch, wait('a'), wait('b'), nodes()[2]];
  stored.draft.nodes = [branch, wait('b'), nodes()[2]];
  await mount(); TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(cards().length).toBe(1); expect(cards()[0].textContent).toContain('1 live contact');
});
it('keeps pending cards through review cancellation and saved-draft reload without migration', async () => {
  await mount(); const published = clone(stored.published); removeFirst(); await review(); selectMove();
  expect(modal().textContent).toContain('Your draft changes remain saved. Contacts stay at their current live steps until you publish.');
  expect(Array.from(document.getElementById('migration-destination-a').options).map(option => option.value)).toEqual(['', 'b', 'exit']);
  TestUtils.Simulate.click(button(modal(), 'Keep editing draft')); await tick();
  expect(cards().length).toBe(1); expect(axios.post).not.toHaveBeenCalled(); expect(stored.published).toEqual(published);
  await owner.reloadData(); expect(cards().length).toBe(1); expect(stored.draft.nodes.map(node => node.id)).toEqual(['b', 'exit']);
});
it('removes pending cards only after successful publication and authoritative reload, updating live counts', async () => {
  await mount(); removeFirst(); await review(); selectMove();
  TestUtils.Simulate.click(button(modal(), 'Publish')); await tick();
  expect(cards().length).toBe(0); expect(container.textContent).toContain('Step 1 (1 live contact');
  expect(owner.state.data.status).toBe('paused'); expect(stored.draft.nodes.map(node => node.id)).toEqual(['b', 'exit']);
});
it('does not optimistically remove pending cards while a publication request is still running', async () => {
  let resolve; const response = new Promise(done => {resolve = done;});
  await mount(); removeFirst(); await review(); selectMove(); axios.post.mockImplementation(() => response);
  TestUtils.Simulate.click(button(modal(), 'Publish')); await tick();
  expect(cards().length).toBe(1); expect(cards()[0].textContent).toContain('1 live contact');
  expect(button(modal(), 'Keep editing draft')).toBe(undefined);
  resolve({data: {...stored, publication_receipt: {outcomes: []}}}); await tick();
  // The server reload still reports the old snapshot; the view must retain it.
  expect(cards().length).toBe(1);
});
[new Error('Lost response'), {response: {status: 409, data: {description: 'Execution claim remains'}}}].forEach(error => {
  it('preserves pending cards and counts after ' + (error.response ? 'refusal' : 'an uncertain response'), async () => {
    await mount(); removeFirst(); await review(); selectMove(); axios.post.mockImplementation(() => Promise.reject(error));
    TestUtils.Simulate.click(button(modal(), 'Publish')); await tick();
    expect(cards().length).toBe(1); expect(cards()[0].textContent).toContain('1 live contact');
    expect(stored.published.nodes.map(node => node.id)).toEqual(['a', 'b', 'exit']);
  });
});
