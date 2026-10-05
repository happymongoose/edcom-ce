import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import Automation from './Automation';
import AutomationWorkflowEditor from './AutomationWorkflowEditor';
import withLoadSave from '../components/LoadSave';
import { automationWaitError, automationWaitInstant } from './AutomationWaitFields';
import moment from 'moment';

jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn()}));
jest.mock('react-select2-wrapper', () => () => null);

const definition = () => ({
  name: 'Wait test', entry: {type: 'manual'}, reentry: 'once',
  draft: {nodes: [
    {id: 'branch', type: 'if_has_tag', label: 'Branch', draft_tag: 'vip', yes_node_id: 'wait', no_node_id: 'exit'},
    {id: 'wait', type: 'wait_duration', label: 'Pause before email', duration: {days: 1, hours: 2, minutes: 5}},
    {id: 'other-wait', type: 'wait_duration', label: 'Other Wait', duration: {days: 0, hours: 0, minutes: 5}},
    {id: 'exit', type: 'exit', label: 'Exit'},
  ]},
});
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(node => node.textContent.trim() === text);
const dialog = () => document.querySelector('[role="dialog"]');
const field = unit => document.getElementById('automation-wait-modal-' + unit);
const change = (unit, value) => TestUtils.Simulate.change(field(unit), {target: {value: value}});

let container, owner, editor, beforeUpdate;
beforeEach(() => {
  beforeUpdate = null;
  container = document.createElement('div');
  document.body.appendChild(container);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  jest.clearAllMocks();
});

async function mount(data = definition()) {
  const Page = props => <AutomationWorkflowEditor
    ref={value => { editor = value; }} nodes={props.data.draft.nodes}
    update={(spec, callback) => {
      if (beforeUpdate) beforeUpdate();
      props.update(spec, callback);
    }} renderNodeContactCount={() => null}
  />;
  const Loaded = withLoadSave({extend: Page, initial: data, get: async () => data});
  owner = ReactDOM.render(<Loaded history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick();
  TestUtils.Simulate.click(button(container, 'Visual preview'));
}
function open() {
  const trigger = container.querySelector('button[aria-label^="Edit Wait step 2:"]');
  trigger.focus();
  TestUtils.Simulate.click(trigger);
  return trigger;
}

it('converts local dates to exact instants and refuses invalid or offset-free deadlines', () => {
  ['', 'not a date', '2030-06-12', '2030-06-12T09:30'].forEach(value => expect(automationWaitError({}, value)).not.toBe(''));
  expect(automationWaitError({}, '2030-06-12T09:30:00+01:00')).toBe('');
  expect(automationWaitInstant('2030-02-30T12:00')).toBe('');
  ['2030-01-12T09:30', '2030-06-12T09:30', '2030-03-31T01:30', '2030-10-27T01:30'].forEach(value => {
    const local = moment(value, 'YYYY-MM-DDTHH:mm', true);
    expect(automationWaitInstant(value)).toBe(local.format('YYYY-MM-DDTHH:mm') === value ? local.toISOString() : '');
  });
});

it('changes to an exact date locally, cancels cleanly and commits only the chosen wait configuration', async () => {
  await mount(); open(); const before = clone(owner.state.data);
  change('mode', 'until');
  expect(button(dialog(), 'Save').disabled).toBe(true);
  change('until', '2030-06-12T09:30');
  expect(dialog().textContent).toContain('Time zone:');
  expect(owner.state.data).toEqual(before);
  TestUtils.Simulate.click(button(dialog(), 'Cancel'));
  expect(owner.state.data).toEqual(before);
  open(); change('mode', 'until'); change('until', '2030-06-12T09:30');
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  const node = owner.state.data.draft.nodes[1];
  expect(node.duration).toBeUndefined();
  expect(node.wait_until).toBe(moment('2030-06-12T09:30').toISOString());
  expect(node.id).toBe('wait');
  expect(owner.state.data.draft.nodes[0]).toEqual(before.draft.nodes[0]);
  expect(container.querySelector('.automation-wait-preview-node').textContent).toContain('2030');
  open(); expect(field('until').value).toBe('2030-06-12T09:30');
  change('mode', 'duration'); TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes[1].wait_until).toBeUndefined();
  expect(owner.state.data.draft.nodes[1].duration.minutes).toBe(5);
});

it('opens only Wait nodes, populates the shared fields, and buffers changes without mutation', async () => {
  await mount();
  const before = owner.state.data;
  expect(container.querySelectorAll('.automation-wait-preview-node').length).toBe(2);
  open();
  expect(dialog().textContent).toContain('Edit Wait step');
  expect(dialog().contains(document.activeElement)).toBe(true);
  expect(dialog().textContent).toContain('Pause before email');
  expect(['days', 'hours', 'minutes'].map(unit => field(unit).value)).toEqual(['1', '2', '5']);
  change('days', '3');
  expect(owner.state.data).toBe(before);
  expect(before.draft.nodes[1].duration.days).toBe(1);
});

['Cancel', 'close', 'Escape'].forEach(action => {
  it(action + ' discards edits and restores focus', async () => {
    await mount();
    const before = owner.state.data;
    const trigger = open();
    change('minutes', '17');
    if (action === 'Escape') {
      const event = document.createEvent('Event');
      event.initEvent('keydown', true, true);
      event.keyCode = 27;
      document.dispatchEvent(event);
    } else {
      TestUtils.Simulate.click(action === 'close' ? dialog().querySelector('.close') : button(dialog(), action));
    }
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(editor.state.nodeEdit).toBe(null);
    expect(owner.state.data).toBe(before);
    expect(document.activeElement).toBe(trigger);
    open();
    expect(field('minutes').value).toBe('5');
  });
});

it('commits once to canonical state, preserving IDs, ordering, branch references, and updating both views', async () => {
  await mount();
  const before = owner.state.data;
  open();
  change('days', '2');
  change('hours', '0');
  change('minutes', '0');
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  editor.saveNodeEditor();
  const after = owner.state.data;
  expect(after.draft.nodes.map(node => node.id)).toEqual(before.draft.nodes.map(node => node.id));
  expect(after.draft.nodes[0]).toBe(before.draft.nodes[0]);
  expect(after.draft.nodes[2]).toBe(before.draft.nodes[2]);
  expect(after.draft.nodes[3]).toBe(before.draft.nodes[3]);
  expect(after.draft.nodes[1]).toEqual({...before.draft.nodes[1], duration: {days: 2, hours: 0, minutes: 0}});
  expect(editor.state.nodeEdit).toBe(null);
  expect(container.querySelector('.automation-wait-preview-node').textContent).toContain('2 days');
  TestUtils.Simulate.click(button(container, 'Edit list'));
  editor.setState({expandedNodeIds: {wait: true}});
  expect(container.querySelector('#wait-wait-days').value).toBe('2');
  TestUtils.Simulate.change(container.querySelector('#wait-wait-hours'), {target: {value: '3'}});
  TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(container.querySelector('.automation-wait-preview-node').textContent).toContain('2 days 3 hours');
});

it('resolves the stable ID after reordering while the dialog is open', async () => {
  await mount();
  open();
  change('days', '4');
  const nodes = owner.state.data.draft.nodes;
  owner.updateData({draft: {nodes: {$set: [nodes[0], nodes[2], nodes[1], nodes[3]]}}});
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['branch', 'other-wait', 'wait', 'exit']);
  expect(owner.state.data.draft.nodes[2].duration.days).toBe(4);
  expect(owner.state.data.draft.nodes[1]).toBe(nodes[2]);
});

['missing', 'type', 'duplicate', 'changed'].forEach(reason => {
  it('rejects a ' + reason + ' target before committing', async () => {
    await mount();
    open();
    const nodes = clone(owner.state.data.draft.nodes);
    if (reason === 'missing') nodes.splice(1, 1);
    if (reason === 'type') nodes[1].type = 'exit';
    if (reason === 'duplicate') nodes.push(clone(nodes[1]));
    if (reason === 'changed') nodes[1].duration.days = 7;
    owner.updateData({draft: {nodes: {$set: nodes}}});
    const before = owner.state.data;
    expect(button(dialog(), 'Save').disabled).toBe(true);
    editor.saveNodeEditor();
    expect(owner.state.data).toBe(before);
    expect(dialog().querySelector('[role="alert"]').textContent).toContain('Wait step');
  });
});

it('fails safely when duplicate IDs already exist on opening', async () => {
  const data = definition();
  data.draft.nodes.push(clone(data.draft.nodes[1]));
  await mount();
  owner.updateData({$set: data});
  open();
  expect(button(dialog(), 'Save').disabled).toBe(true);
  editor.saveNodeEditor();
  expect(owner.state.data).toBe(data);
});

[
  {days: 0, hours: 0, minutes: 4},
  {days: 365, hours: 0, minutes: 1},
  {days: -1, hours: 0, minutes: 5},
  {days: 0, hours: 0.5, minutes: 5},
  {days: '', hours: 0, minutes: 5},
  {days: 'abc', hours: 0, minutes: 5},
].forEach(duration => {
  it('prevents invalid modal commit: ' + JSON.stringify(duration), async () => {
    await mount();
    const before = owner.state.data;
    open();
    Object.keys(duration).forEach(unit => change(unit, String(duration[unit])));
    expect(button(dialog(), 'Save').disabled).toBe(true);
    editor.saveNodeEditor();
    expect(owner.state.data).toBe(before);
    expect(dialog().querySelector('[role="alert"]')).not.toBe(null);
  });
});

it('rechecks canonical state even if props still contain the original target', async () => {
  await mount();
  open();
  change('days', '4');
  const changed = clone(owner.state.data);
  changed.draft.nodes[1].duration.days = 8;
  // Simulate an update arriving after the prop check but before the updater executes.
  beforeUpdate = () => { owner.state.data = changed; };
  editor.saveNodeEditor();
  expect(owner.state.data.draft.nodes[1].duration.days).toBe(8);
  expect(editor.state.nodeEdit).not.toBe(null);
  expect(dialog().querySelector('[role="alert"]')).not.toBe(null);
});

it('accepts exact boundaries and rejects noninteger/nonfinite values', () => {
  expect(automationWaitError({days: 0, hours: 0, minutes: 5})).toBe('');
  expect(automationWaitError({days: 365, hours: 0, minutes: 0})).toBe('');
  [null, undefined, NaN, Infinity, -Infinity, 1.2, -1, '1x', ''].forEach(value => {
    expect(automationWaitError({days: value, hours: 0, minutes: 5})).not.toBe('');
  });
});

[false, true].forEach(absolute => it('uses the real page Save payload and reload path without persisting modal metadata or publishing (' + (absolute ? 'deadline' : 'duration') + ')', async () => {
  let stored = definition();
  stored.id = 'test';
  stored.status = 'draft';
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/automations/test' ? clone(stored) :
    url.indexOf('/enrolments') !== -1 ? {summary: {}} :
    url.indexOf('/preflight') !== -1 ? {} : []}));
  axios.patch.mockImplementation((url, payload) => {
    stored = {...stored, ...clone(payload)};
    return Promise.resolve({data: clone(stored)});
  });
  owner = ReactDOM.render(<Automation history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick();
  editor = TestUtils.findRenderedComponentWithType(owner, AutomationWorkflowEditor);
  TestUtils.Simulate.click(button(container, 'Visual preview'));
  open();
  if (absolute) {change('mode', 'until'); change('until', '2030-06-12T09:30');}
  else change('days', '6');
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(axios.patch.mock.calls.length).toBe(0);
  TestUtils.Simulate.click(button(container, 'Save'));
  await tick();
  expect(axios.patch.mock.calls.length).toBe(1);
  const expected = definition();
  expected.draft.nodes[1].duration.days = 6;
  if (absolute) {delete expected.draft.nodes[1].duration; expected.draft.nodes[1].wait_until = moment('2030-06-12T09:30').toISOString();}
  expect(axios.patch.mock.calls[0]).toEqual(['/api/automations/test', expected]);
  await owner.reloadData();
  expect(owner.state.data.draft.nodes[1]).toEqual(expected.draft.nodes[1]);
  expect(container.querySelector('.automation-wait-preview-node').textContent).toContain(absolute ? '2030' : '6 days');
}));
