import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import Automation from './Automation';
import AutomationPublishReview from './AutomationPublishReview';
import notify from '../utils/notify';

jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn(), post: jest.fn()}));

const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const deferred = () => {let resolve, reject; const promise = new Promise((a, b) => {resolve = a; reject = b;}); return {promise, resolve, reject};};
const failure = (status, title, description) => ({response: {status, data: {title, description}}});
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(el => el.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const review = () => ({draft_fingerprint: 'a'.repeat(64), published_fingerprint: 'b'.repeat(64), published_revision: 2});
const source = id => ({node_id: id, label: 'Old wait', type: 'wait_duration', enrolment_count: 2, states: {waiting: 2}});
const base = '/api/automations/test';
let container, owner, controller, stored, impact, calls;

function get(url) {
  calls.push('GET ' + url);
  return Promise.resolve({data: url === base ? clone(stored) :
    url === base + '/publish-impact' ? clone(impact) :
    url.indexOf('/enrolments') !== -1 ? {summary: {}} : url.indexOf('/preflight') !== -1 ? {} : []});
}
function commit(url, body) {
  calls.push('POST ' + url);
  const payload = JSON.parse(body);
  stored.published_revision++;
  stored.status = stored.status === 'paused' ? 'paused' : 'published';
  stored.published = clone(stored.draft);
  stored.publication_receipt = {request_id: payload.request_id, published_revision: stored.published_revision,
    outcomes: Object.keys(payload.resolutions).map(id => ({source_node_id: id, ...payload.resolutions[id], enrolment_count: 3}))};
  return Promise.resolve({data: clone(stored)});
}
beforeEach(() => {
  stored = {id: 'test', name: 'Publish review test', status: 'published', published_at: '2026-01-01',
    published_revision: 2, entry: {type: 'manual'}, reentry: 'once',
    draft: {nodes: [{id: 'next', type: 'wait_duration', label: 'Wait', duration: {days: 1, hours: 0, minutes: 0}},
      {id: 'exit', type: 'exit', label: 'Exit'}]},
    published: {nodes: [{...source('old'), id: 'old'}]}};
  impact = {review: review(), automation_status: 'published', sources: [source('old')],
    destinations: [{node_id: 'next', label: 'Wait', type: 'wait_duration'}, {node_id: 'exit', label: 'Exit', type: 'exit'}], blockers: []};
  calls = [];
  axios.get.mockImplementation(get);
  axios.patch.mockImplementation((url, data) => {
    calls.push('PATCH ' + url); stored = {...stored, ...clone(data)}; return Promise.resolve({data: clone(stored)});
  });
  axios.post.mockImplementation(commit);
  container = document.createElement('div'); document.body.appendChild(container);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container); jest.resetAllMocks();
});
async function mount() {
  owner = ReactDOM.render(<Automation history={{location: {search: ''}, push: jest.fn()}}
    match={{params: {id: 'test'}}} />, container);
  await tick();
  controller = TestUtils.findRenderedComponentWithType(owner, AutomationPublishReview);
  calls = [];
}
async function open() {
  const trigger = button(container, 'Publish'); trigger.focus(); TestUtils.Simulate.click(trigger); await tick(); return trigger;
}
function choose(id, action, destination) {
  TestUtils.Simulate.change(document.getElementById('migration-action-' + id), {target: {value: action}});
  if (destination !== undefined) TestUtils.Simulate.change(document.getElementById('migration-destination-' + id), {target: {value: destination}});
}
async function confirm() {TestUtils.Simulate.click(button(dialog(), 'Publish')); await tick();}
async function reassess(label = 'Reassess') {TestUtils.Simulate.click(button(dialog(), label)); await tick();}

it('awaits successful Save before assessment, with no publication while Save is pending', async () => {
  const save = deferred(); axios.patch.mockImplementation(() => save.promise);
  await mount(); await open();
  expect(dialog().textContent).toContain('Saving draft');
  expect(calls).toEqual([]); expect(axios.post).not.toHaveBeenCalled();
  save.resolve({data: stored}); await tick();
  expect(calls).toEqual(['GET ' + base + '/publish-impact']);
  expect(dialog().textContent).toContain('Old wait (old)');
});
it('stops on Save failure and preserves ordinary Save without assessing or publishing', async () => {
  await mount();
  TestUtils.Simulate.change(container.querySelector('#name'), {target: {id: 'name', value: 'Updated draft'}});
  TestUtils.Simulate.click(button(container, 'Save')); await tick();
  expect(stored.name).toBe('Updated draft');
  expect(axios.post).not.toHaveBeenCalled(); expect(calls).toEqual(['PATCH ' + base]);
  expect(dialog().textContent).toContain('Draft saved');
  TestUtils.Simulate.click(button(dialog(), 'Stay in draft'));
  await new Promise(resolve => setTimeout(resolve, 350));
  axios.patch.mockImplementation(() => Promise.reject(failure(400, 'Invalid draft', 'Draft save refused')));
  await open(); await new Promise(resolve => setTimeout(resolve, 350));
  expect(dialog()).toBe(null); expect(axios.post).not.toHaveBeenCalled();
  expect(calls.filter(call => call.indexOf('publish-impact') >= 0)).toEqual([]);
  expect(notify.show).toHaveBeenCalledWith('Draft save refused', 'error');
});
it('reports assessment failure without publication and can reassess without another save', async () => {
  await mount(); axios.get.mockImplementation(url => url.endsWith('/publish-impact') ? Promise.reject(failure(503, 'Unavailable', 'Assessment unavailable')) : get(url));
  await open(); expect(dialog().textContent).toContain('Assessment unavailable'); expect(axios.post).not.toHaveBeenCalled();
  axios.get.mockImplementation(get); await reassess();
  expect(document.getElementById('migration-action-old').value).toBe('');
  expect(axios.patch.mock.calls.length).toBe(1);
});
it('publishes a clear impact without an extra confirmation, using its review and authoritative reload', async () => {
  impact.sources = []; await mount(); await open();
  expect(calls.slice(0, 3)).toEqual(['PATCH ' + base, 'GET ' + base + '/publish-impact', 'POST ' + base + '/publish']);
  const request = JSON.parse(axios.post.mock.calls[0][1]);
  expect(request.review).toEqual(review()); expect(request.resolutions).toEqual({});
  expect(request.request_id).toMatch(/^[0-9a-zA-Z_-]{1,64}$/);
  expect(owner.state.data.published_revision).toBe(3);
  expect(calls.filter(call => call === 'GET ' + base).length).toBe(1);
  expect(controller._requestBody).toBe(null);
});
it('shows structured blockers and refuses publication even if choices would otherwise be complete', async () => {
  impact.blockers = [{code: 'execution_claims', title: 'Execution claims remain', description: 'Wait for execution to finish.', enrolment_count: 2}];
  await mount(); await open();
  expect(dialog().textContent).toContain('Execution claims remain'); expect(dialog().textContent).toContain('Enrolments: 2.');
  expect(button(dialog(), 'Publish').disabled).toBe(true); await controller.submit(); expect(axios.post).not.toHaveBeenCalled();
});
it('requires explicit choices for multiple stable sources and valid destinations, keeping canonical data unchanged', async () => {
  impact.sources.push(source('other')); await mount(); const canonical = clone(owner.state.data); await open();
  expect(document.getElementById('migration-action-old').value).toBe('');
  expect(document.getElementById('migration-action-other').value).toBe('');
  expect(button(dialog(), 'Publish').disabled).toBe(true);
  choose('old', 'move'); expect(document.getElementById('migration-destination-old').value).toBe('');
  expect(Array.from(document.getElementById('migration-destination-old').options).map(option => option.value)).toEqual(['', 'next', 'exit']);
  choose('other', 'exit'); expect(button(dialog(), 'Publish').disabled).toBe(true);
  choose('old', 'move', 'NEXT'); await controller.submit(); expect(axios.post).not.toHaveBeenCalled();
  choose('old', 'move', 'next'); expect(button(dialog(), 'Publish').disabled).toBe(false);
  expect(owner.state.data).toEqual(canonical);
  expect(dialog().textContent).toContain('resets any existing wait'); expect(dialog().textContent).toContain('even while paused');
  await confirm();
  expect(JSON.parse(axios.post.mock.calls[0][1]).resolutions).toEqual({old: {action: 'move', destination_node_id: 'next'}, other: {action: 'exit'}});
  expect(notify.show).toHaveBeenCalledWith('Automation published. 3 enrolments moved; 3 exited immediately.', 'success');
});
['Keep editing draft', 'close', 'Escape'].forEach(action => {
  it(action + ' discards review choices, restores focus and leaves live state unchanged after saving the draft', async () => {
    await mount(); const previous = clone(stored.published); const trigger = await open(); choose('old', 'move', 'exit');
    expect(container.querySelector('fieldset[disabled]')).not.toBe(null);
    if (action === 'Escape') {
      const event = document.createEvent('Event'); event.initEvent('keydown', true, true); event.keyCode = 27;
      document.getElementById('migration-action-old').dispatchEvent(event);
    } else TestUtils.Simulate.click(action === 'close' ? dialog().querySelector('.close') : button(dialog(), 'Keep editing draft'));
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(dialog()).toBe(null); expect(document.activeElement).toBe(trigger);
    expect(stored.published).toEqual(previous); expect(axios.post).not.toHaveBeenCalled();
    expect(notify.show).toHaveBeenCalledWith('Draft saved. Live publication was not changed by this review.', 'success');
    await open(); expect(document.getElementById('migration-action-old').value).toBe('');
  });
});
it('blocks duplicate submission and close/Escape during the server transaction', async () => {
  const pending = deferred(); axios.post.mockImplementation(() => pending.promise);
  await mount(); await open(); choose('old', 'exit');
  const publish = button(dialog(), 'Publish'); TestUtils.Simulate.click(publish); TestUtils.Simulate.click(publish);
  controller.close();
  const event = document.createEvent('Event'); event.initEvent('keydown', true, true); event.keyCode = 27; dialog().dispatchEvent(event);
  expect(axios.post.mock.calls.length).toBe(1); expect(dialog().textContent).toContain('does not cancel');
  expect(dialog().querySelector('.close')).toBe(null);
  pending.resolve({data: {...stored, publication_receipt: {outcomes: []}}}); await tick();
});
it('invalidates local review choices if canonical publish inputs change through another path', async () => {
  await mount(); await open(); choose('old', 'exit');
  owner.updateData({name: {$set: 'Concurrent local edit'}});
  expect(dialog().textContent).toContain('automation changed while this review');
  expect(button(dialog(), 'Publish')).toBe(undefined); await controller.submit(); expect(axios.post).not.toHaveBeenCalled();
});
it('ignores unrelated metadata and object key ordering when checking local review identity', async () => {
  await mount(); await open(); choose('old', 'exit');
  owner.updateData({modified: {$set: 'later'}, draft: {$set: {nodes: owner.state.data.draft.nodes.map(node =>
    Object.keys(node).reverse().reduce((obj, key) => ({...obj, [key]: node[key]}), {}))}}});
  expect(button(dialog(), 'Publish').disabled).toBe(false); await confirm(); expect(axios.post.mock.calls.length).toBe(1);
});
it('reloads after a stale review and discards decisions instead of transferring them to the changed workflow', async () => {
  await mount(); await open(); choose('old', 'exit');
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Automation publish review is stale', 'Reload publish impact.')));
  await confirm(); expect(dialog().textContent).toContain('Reload publish impact.');
  stored.name = 'Server change'; impact.review.draft_fingerprint = 'c'.repeat(64);
  await reassess('Reload and reassess');
  expect(owner.state.data.name).toBe('Server change');
  expect(document.getElementById('migration-action-old').value).toBe('');
  expect(button(dialog(), 'Publish').disabled).toBe(true); expect(axios.patch.mock.calls.length).toBe(1);
});
it('reassesses newly occupied sources and preserves only valid choices under an unchanged identity', async () => {
  await mount(); await open(); choose('old', 'move', 'next');
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Automation migration resolutions required', 'Choose a resolution for other.')));
  await confirm(); impact.sources[0].enrolment_count = 8; impact.sources.push(source('other'));
  await reassess();
  expect(dialog().textContent).toContain('8 enrolments');
  expect(document.getElementById('migration-action-old').value).toBe('move');
  expect(document.getElementById('migration-destination-old').value).toBe('next');
  expect(document.getElementById('migration-action-other').value).toBe('');
  expect(button(dialog(), 'Publish').disabled).toBe(true);
  choose('other', 'exit'); await confirm(); expect(axios.post.mock.calls.length).toBe(2);
});
it('drops invalid destinations on reassessment and does not automatically publish after a conflict', async () => {
  await mount(); await open(); choose('old', 'move', 'next');
  impact.destinations = impact.destinations.filter(node => node.node_id !== 'next');
  await reassess(); expect(document.getElementById('migration-action-old').value).toBe('');
  impact.sources = []; await reassess();
  expect(axios.post).not.toHaveBeenCalled(); expect(button(dialog(), 'Publish').disabled).toBe(false);
});
it('shows backend invalid-choice and claim errors and permits reassessment', async () => {
  await mount(); await open(); choose('old', 'exit');
  axios.post.mockImplementationOnce(() => Promise.reject(failure(400, 'Invalid automation migration resolution', 'Destination is not valid.')));
  await confirm(); expect(dialog().textContent).toContain('Destination is not valid.');
  await reassess();
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Execution claims remain', 'Wait for execution.')));
  await confirm(); expect(dialog().textContent).toContain('Wait for execution.');
  impact.blockers = [{code: 'execution_claims', title: 'Claims', description: 'Wait for execution.'}];
  await reassess(); expect(button(dialog(), 'Publish').disabled).toBe(true);
});
[null, 502].forEach(status => {
  it('retries an uncertain ' + status + ' response using identical serialized payload and no Save or assessment', async () => {
    await mount(); await open(); choose('old', 'move', 'exit');
    axios.post.mockImplementationOnce(() => Promise.reject(status ? failure(status, 'Gateway', 'Unknown') : new Error('Network lost')));
    await confirm();
    expect(dialog().textContent).toContain('result is unknown'); expect(dialog().querySelector('.close')).toBe(null);
    controller.close(); expect(dialog()).not.toBe(null);
    const original = axios.post.mock.calls[0][1]; const before = calls.slice();
    const pending = deferred(); axios.post.mockImplementationOnce(() => pending.promise);
    const retry = button(dialog(), 'Retry same publication'); TestUtils.Simulate.click(retry); TestUtils.Simulate.click(retry);
    expect(axios.post.mock.calls.length).toBe(2); expect(axios.post.mock.calls[1][1]).toBe(original);
    expect(calls).toEqual(before); expect(axios.patch.mock.calls.length).toBe(1);
    pending.resolve({data: {...stored, publication_receipt: {outcomes: [{action: 'move', enrolment_count: 7}]}}}); await tick();
    expect(notify.show).toHaveBeenCalledWith('Automation published. 7 enrolments moved; 0 exited immediately.', 'success');
  });
});
it('requires reload after a superseded uncertain attempt and never silently creates a new attempt', async () => {
  await mount(); await open(); choose('old', 'exit');
  axios.post.mockImplementationOnce(() => Promise.reject(new Error('Lost response')));
  await confirm(); const original = axios.post.mock.calls[0][1];
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Automation publish review is stale', 'Reload publish impact.')));
  TestUtils.Simulate.click(button(dialog(), 'Retry same publication')); await tick();
  expect(axios.post.mock.calls[1][1]).toBe(original); expect(dialog().textContent).toContain('earlier uncertain attempt may have committed');
  impact.review.published_revision++; stored.published_revision++; await reassess('Reload and reassess');
  expect(axios.post.mock.calls.length).toBe(2); expect(document.getElementById('migration-action-old').value).toBe('');
});
it('reports successful publication separately from reload failure, and retries only the reload', async () => {
  await mount(); await open(); choose('old', 'exit');
  axios.get.mockImplementation(url => url === base ? Promise.reject(new Error('Reload failed')) : get(url));
  await confirm(); expect(dialog().textContent).toContain('Publication succeeded, but the page could not reload');
  expect(button(dialog(), 'Retry same publication')).toBe(undefined);
  axios.get.mockImplementation(get); TestUtils.Simulate.click(button(dialog(), 'Retry page reload')); await tick();
  expect(axios.post.mock.calls.length).toBe(1); expect(owner.state.data.published_revision).toBe(3);
});
it('uses receipt counts and authoritative paused status without invoking Resume', async () => {
  stored.status = 'paused'; impact.automation_status = 'paused'; await mount(); await open(); choose('old', 'exit'); await confirm();
  expect(owner.state.data.status).toBe('paused'); expect(button(container, 'Resume')).not.toBe(undefined);
  expect(axios.post.mock.calls.map(call => call[0])).toEqual([base + '/publish']);
  expect(notify.show).toHaveBeenCalledWith('Automation published. 0 enrolments moved; 3 exited immediately. Automation remains paused.', 'success');
});

it('preserves exact source IDs that are also JavaScript object property names', async () => {
  impact.sources = [source('__proto__'), source('constructor')];
  await mount(); await open(); choose('__proto__', 'exit'); choose('constructor', 'move', 'next');
  await reassess(); expect(button(dialog(), 'Publish').disabled).toBe(false); await confirm();
  const choices = JSON.parse(axios.post.mock.calls[0][1]).resolutions;
  expect(Object.keys(choices).sort()).toEqual(['__proto__', 'constructor']);
  expect(choices['__proto__']).toEqual({action: 'exit'});
});
it('invalidates a review if canonical node order changes, and ignores a late assessment after that change', async () => {
  const loading = deferred();
  await mount(); axios.get.mockImplementation(url => url.endsWith('/publish-impact') ? loading.promise : get(url));
  await open();
  owner.updateData({draft: {nodes: {$set: owner.state.data.draft.nodes.slice().reverse()}}});
  loading.resolve({data: {...impact, sources: []}}); await tick();
  expect(dialog().textContent).toContain('automation changed while this review');
  expect(axios.post).not.toHaveBeenCalled();
});
it('requires authoritative reload after a committed request-ID conflict', async () => {
  await mount(); await open(); choose('old', 'exit');
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Publication request ID was already used', 'Reload before reviewing another publication.')));
  await confirm();
  expect(dialog().textContent).toContain('Reload before reviewing');
  await reassess('Reload and reassess');
  expect(document.getElementById('migration-action-old').value).toBe('');
  expect(axios.patch.mock.calls.length).toBe(1);
});

it('cancels a pending assessment and ignores its late clear-impact response, even after reopening', async () => {
  const oldAssessment = deferred(); await mount();
  axios.get.mockImplementationOnce(() => oldAssessment.promise);
  await open(); TestUtils.Simulate.click(button(dialog(), 'Keep editing draft'));
  await tick(); await open();
  expect(document.getElementById('migration-action-old').value).toBe('');
  oldAssessment.resolve({data: {...impact, sources: []}}); await tick();
  expect(axios.post).not.toHaveBeenCalled();
  expect(document.getElementById('migration-action-old').value).toBe('');
});
it('cancels before Save finishes without implying that the pending draft save was cancelled', async () => {
  const saving = deferred(); await mount(); axios.patch.mockImplementation(() => saving.promise);
  await open(); TestUtils.Simulate.click(button(dialog(), 'Keep editing draft'));
  saving.resolve({data: stored}); await tick();
  expect(axios.post).not.toHaveBeenCalled(); expect(calls).toEqual([]);
  expect(notify.show).toHaveBeenCalledWith('Publication cancelled. The draft save is still finishing; live publication was not changed.', 'success');
});
it('retains the uncertain payload through a local change and can reload a superseded review', async () => {
  await mount(); await open(); choose('old', 'exit');
  axios.post.mockImplementationOnce(() => Promise.reject(new Error('Lost response')));
  await confirm(); const original = axios.post.mock.calls[0][1];
  owner.updateData({name: {$set: 'Changed locally'}});
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Automation publish review is stale', 'Reload publish impact.')));
  TestUtils.Simulate.click(button(dialog(), 'Retry same publication')); await tick();
  expect(axios.post.mock.calls[1][1]).toBe(original);
  await reassess('Reload and reassess');
  expect(owner.state.data.name).toBe(stored.name);
  expect(document.getElementById('migration-action-old').value).toBe('');
  expect(axios.patch.mock.calls.length).toBe(1);
});

it('keeps a failed stale-review reload actionable even after local invalidation', async () => {
  await mount(); await open(); choose('old', 'exit');
  axios.post.mockImplementationOnce(() => Promise.reject(new Error('Lost response')));
  await confirm(); owner.updateData({name: {$set: 'Changed locally'}});
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Automation publish review is stale', 'Reload publish impact.')));
  TestUtils.Simulate.click(button(dialog(), 'Retry same publication')); await tick();
  axios.get.mockImplementation(url => url === base ? Promise.reject(new Error('Reload unavailable')) : get(url));
  await reassess('Reload and reassess');
  expect(dialog().textContent).toContain('Unable to assess publication');
  expect(button(dialog(), 'Keep editing draft')).not.toBe(undefined);
  axios.get.mockImplementation(get); await reassess('Reload and reassess');
  expect(document.getElementById('migration-action-old').value).toBe('');
  expect(axios.post.mock.calls.length).toBe(2);
});


it('saves exit rules before assessment and requires review even with no node migration', async () => {
  stored.exit_rules = [{type: 'has_tag', tags: ['paid']}];
  impact.sources = []; impact.exit_review_required = true; impact.rule_exits = {enrolment_count: 4, states: {waiting: 4}};
  await mount(); await open();
  expect(axios.patch.mock.calls[0][1].exit_rules).toEqual(stored.exit_rules);
  expect(axios.post).not.toHaveBeenCalled(); expect(dialog().textContent).toContain('4 existing enrolments');
  expect(dialog().textContent).toContain('including paused contacts');
  await confirm();
  expect(JSON.parse(axios.post.mock.calls[0][1]).accept_exit_rules).toBe(true);
  expect(owner.state.data.exit_rules).toEqual(stored.exit_rules);
});
it('cancelled exit-rule review leaves live publication unchanged', async () => {
  impact.sources = []; impact.exit_review_required = true; impact.rule_exits = {enrolment_count: 2};
  await mount(); await open(); TestUtils.Simulate.click(button(dialog(), 'Keep editing draft')); await tick();
  expect(axios.post).not.toHaveBeenCalled(); expect(stored.published_revision).toBe(2);
});
it('invalidates a review when exit rules change', async () => {
  await mount(); await open();
  owner.updateData({exit_rules: {$set: [{type: 'missing_tag', tags: ['eligible']}]}}); await tick();
  expect(dialog().textContent).toContain('automation changed while this review');
  await controller.submit(); expect(axios.post).not.toHaveBeenCalled();
});
it('retries the identical exit acknowledgement without saving and displays actual receipt counts', async () => {
  impact.sources = []; impact.exit_review_required = true; impact.rule_exits = {enrolment_count: 1};
  stored.status = 'paused';
  await mount(); await open();
  axios.post.mockImplementationOnce(() => Promise.reject(new Error('response lost')));
  await confirm(); const original = axios.post.mock.calls[0][1]; const saves = axios.patch.mock.calls.length;
  axios.post.mockImplementationOnce(() => Promise.resolve({data: {...stored, publication_receipt: {outcomes: [], rule_exit_count: 3}}}));
  TestUtils.Simulate.click(button(dialog(), 'Retry same publication')); await tick();
  expect(axios.post.mock.calls[1][1]).toBe(original); expect(axios.patch.mock.calls.length).toBe(saves);
  expect(notify.show).toHaveBeenCalledWith('Automation published. 3 enrolments exited by rule. Automation remains paused.', 'success');
});
it('requires fresh exit review if matches appear after a no-impact assessment', async () => {
  impact.sources = []; impact.exit_review_required = false;
  axios.post.mockImplementationOnce(() => Promise.reject(failure(409, 'Exit-rule publication requires review', 'Review current matches.')));
  await mount(); await open();
  expect(dialog().textContent).toContain('Review current matches.');
  impact.exit_review_required = true; impact.rule_exits = {enrolment_count: 2}; await reassess();
  expect(axios.post.mock.calls.length).toBe(1); expect(dialog().textContent).toContain('2 existing enrolments');
  await confirm(); expect(JSON.parse(axios.post.mock.calls[1][1]).accept_exit_rules).toBe(true);
});
