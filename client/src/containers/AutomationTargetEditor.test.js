import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import Automation from './Automation';
import AutomationWorkflowEditor, {createAutomationNode, automationNodeSummary, automationNodeSummaryWarning} from './AutomationWorkflowEditor';
import {automationTargetOptions, automationTargetError} from './AutomationTargetField';
import withLoadSave from '../components/LoadSave';

jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn()}));

['enrol_automation', 'remove_automation'].forEach(action => describe(action + ' editor', () => {
const actionLabel = action === 'remove_automation' ? 'Remove from another automation' : 'Enrol in another automation';
const target = (id, name, status = 'published') => ({id, name, status, published: {nodes: [{id: 'end', type: 'exit'}]}});
const targets = () => [
  target('a', 'Alpha'), target('b', 'Beta', 'paused'), target('test', 'Self'),
  target('draft', 'Draft', 'draft'), {...target('empty', 'Empty'), published: null},
];
const definition = () => ({name: 'Enrolment editor test', entry: {type: 'manual'}, reentry: 'once', draft: {nodes: [
  {id: 'branch', label: 'Branch', type: 'if_has_tag', draft_tag: 'vip', yes_node_id: 'enrol', no_node_id: 'end'},
  {id: 'enrol', label: 'Start another', type: action, automation_id: 'a'},
  {id: 'wait', label: 'Continue here', type: 'wait_duration', duration: {days: 1, hours: 0, minutes: 0}},
  {id: 'end', label: 'End', type: 'exit'},
]}});
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, label) => Array.from(root.querySelectorAll('button')).find(el => el.textContent.trim() === label);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const field = () => document.getElementById('automation-target-modal');
const click = el => TestUtils.Simulate.click(el);
let container, owner, editor, options, beforeUpdate;
beforeEach(() => {
  options = targets(); beforeUpdate = null;
  container = document.createElement('div'); document.body.appendChild(container);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container); jest.clearAllMocks();
});
async function mount(data = definition()) {
  const Page = props => <AutomationWorkflowEditor ref={value => {editor = value;}}
    automationId="test" nodes={props.data.draft.nodes} automations={options}
    update={(spec, cb) => {if (beforeUpdate) beforeUpdate(); props.update(spec, cb);}}
    renderNodeContactCount={() => null} />;
  const Loaded = withLoadSave({extend: Page, initial: data, get: async () => data});
  owner = ReactDOM.render(<Loaded history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick();
}
function open() {
  const trigger = container.querySelector('button[aria-label^="Edit ' + actionLabel + ' step 2:"]');
  trigger.focus(); click(trigger);
  expect(dialog().textContent).toContain('Edit ' + actionLabel + ' step');
  return trigger;
}
function choose(value) {TestUtils.Simulate.change(field(), {target: {id: 'automation-target-modal', value}});}

it('populates only eligible loaded options and keeps edits temporary without another request', async () => {
  await mount(); const before = owner.state.data; open();
  expect(field().value).toBe('a');
  expect(Array.from(field().options).map(option => option.value)).toEqual(['', 'a', 'b']);
  expect(dialog().textContent).toContain('this automation continues');
  expect(dialog().textContent).toContain('Beta (paused)');
  choose('b'); expect(owner.state.data).toBe(before); expect(axios.get).not.toHaveBeenCalled();
});

['Cancel', 'close', 'Escape'].forEach(action => {
  ['a', 'deleted'].forEach(reference => {
    it(action + ' discards replacement of ' + reference + ' and returns focus', async () => {
      const data = definition(); data.draft.nodes[1].automation_id = reference;
      await mount(data); const before = owner.state.data; const trigger = open(); choose('b');
      if (action === 'Escape') {
        const event = document.createEvent('Event'); event.initEvent('keydown', true, true); event.keyCode = 27;
        field().dispatchEvent(event);
      } else click(action === 'close' ? dialog().querySelector('.close') : button(dialog(), 'Cancel'));
      await new Promise(resolve => setTimeout(resolve, 350));
      expect(dialog()).toBe(null); expect(owner.state.data).toBe(before); expect(document.activeElement).toBe(trigger);
      open(); expect(field().value).toBe(reference);
    });
  });
});

it('commits only automation_id once and synchronizes Visual and Edit list in both directions', async () => {
  await mount(); const before = owner.state.data; open(); choose('b');
  const update = jest.fn(); beforeUpdate = update; click(button(dialog(), 'Save')); editor.saveNodeEditor();
  expect(update.mock.calls.length).toBe(1);
  const expected = clone(before); expected.draft.nodes[1].automation_id = 'b';
  expect(owner.state.data).toEqual(expected);
  [0,2,3].forEach(index => expect(owner.state.data.draft.nodes[index]).toBe(before.draft.nodes[index]));
  expect(container.querySelector('.automation-target-preview-node').textContent).toContain('Beta');
  click(button(container, 'Edit list')); editor.setState({expandedNodeIds: {enrol: true}});
  const select = container.querySelector('#automation_id'); expect(select.value).toBe('b');
  TestUtils.Simulate.change(select, {target: {id: 'automation_id', value: 'a'}});
  click(button(container, 'Visual preview'));
  expect(container.querySelector('.automation-target-preview-node').textContent).toContain('Alpha');
});

it('re-resolves stable IDs after reordering', async () => {
  await mount(); open(); choose('b'); const nodes = owner.state.data.draft.nodes;
  owner.updateData({draft: {nodes: {$set: [nodes[0], nodes[2], nodes[1], nodes[3]]}}});
  click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes).toEqual([nodes[0], nodes[2], {...nodes[1], automation_id: 'b'}, nodes[3]]);
});

['missing', 'duplicate', 'stale', 'type'].forEach(reason => {
  it('rejects ' + reason + ' canonical nodes', async () => {
    await mount(); open(); choose('b'); const nodes = clone(owner.state.data.draft.nodes);
    if (reason === 'missing') nodes.splice(1, 1);
    if (reason === 'duplicate') nodes.push(clone(nodes[1]));
    if (reason === 'stale') nodes[1].automation_id = 'newer';
    if (reason === 'type') nodes[1].type = 'exit';
    owner.updateData({draft: {nodes: {$set: nodes}}}); const before = owner.state.data;
    expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor();
    expect(owner.state.data).toBe(before); expect(dialog().querySelector('[role="alert"]')).not.toBe(null);
  });
});

it('rechecks canonical configuration inside the commit', async () => {
  await mount(); open(); choose('b'); const changed = clone(owner.state.data);
  changed.draft.nodes[1].automation_id = 'newer';
  beforeUpdate = () => {owner.state.data = changed;}; editor.saveNodeEditor();
  expect(owner.state.data.draft.nodes[1].automation_id).toBe('newer');
  expect(dialog().querySelector('[role="alert"]')).not.toBe(null);
});

['', 'deleted', 'test', 'draft'].forEach(reference => {
  it('preserves unavailable reference ' + reference + ' until a deliberate valid replacement', async () => {
    const data = definition(); data.draft.nodes[1].automation_id = reference;
    await mount(data); open(); expect(field().value).toBe(reference);
    if (reference) expect(field().options[field().selectedIndex].textContent).toBe('Selected automation unavailable');
    expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
    choose('foreign'); editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
    choose('b'); click(button(dialog(), 'Save')); expect(owner.state.data.draft.nodes[1].automation_id).toBe('b');
  });
});

it('rejects targets removed from the options while the modal is open', async () => {
  await mount(); open(); choose('b'); const before = owner.state.data;
  options = []; owner.forceUpdate();
  expect(field().value).toBe('b'); expect(dialog().textContent).toContain('No other published automations');
  expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor(); expect(owner.state.data).toBe(before);
});

it('uses exact string IDs, excludes self/draft/empty targets, and rejects ambiguous options', () => {
  expect(automationTargetOptions(targets(), 'test', action).map(option => option.id)).toEqual(['a', 'b']);
  expect(automationTargetError(7, [{id: '7'}])).toBeTruthy();
  expect(automationTargetError('7', [{id: '7'}])).toBe('');
  expect(automationTargetError('a', [{id: 'a'}, {id: 'a'}])).toBeTruthy();
  expect(createAutomationNode(action, {generateId: () => 'new'})).toEqual({
    id: 'new', type: action, label: actionLabel, automation_id: '',
  });
});

it('distinguishes cross-automation actions in the collapsed List summary', () => {
  const summary = automationNodeSummary(definition().draft.nodes[1], {automations: targets(), automationId: 'test'});
  expect(summary).toBe(actionLabel + ': Alpha');
  expect(automationNodeSummaryWarning(automationNodeSummary({...definition().draft.nodes[1], automation_id: ''}))).toBe(true);
});

it('creates through the drawer only after valid selection and retains source continuation', async () => {
  await mount(); const before = owner.state.data;
  click(container.querySelector('[aria-label="Add after step 2"]'));
  click(dialog().querySelector('[data-node-type="' + action + '"]'));
  const select = dialog().querySelector('#automation_id'); expect(select.value).toBe('');
  expect(button(dialog(), 'Save step').disabled).toBe(true); expect(owner.state.data).toBe(before);
  TestUtils.Simulate.change(select, {target: {id: 'automation_id', value: 'b'}});
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes.length).toBe(5);
  expect(owner.state.data.draft.nodes[2].automation_id).toBe('b');
  expect(owner.state.data.draft.nodes[3]).toEqual(before.draft.nodes[2]);
  expect(axios.patch).not.toHaveBeenCalled();
});

it('loads account targets through the page and persists only the canonical draft on normal Save/reload', async () => {
  let stored = {...definition(), id: 'test', status: 'draft'};
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/automations/test' ? clone(stored) :
    url === '/api/automations' ? targets() :
    url.indexOf('/enrolments') !== -1 ? {summary: {}} : url.indexOf('/preflight') !== -1 ? {} : []}));
  axios.patch.mockImplementation((url, payload) => {stored = {...stored, ...clone(payload)}; return Promise.resolve({data: clone(stored)});});
  owner = ReactDOM.render(<Automation history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); editor = TestUtils.findRenderedComponentWithType(owner, AutomationWorkflowEditor);
  open(); choose('b'); click(button(dialog(), 'Save')); expect(axios.patch).not.toHaveBeenCalled();
  click(button(container, 'Save')); await tick();
  const expected = definition(); expected.draft.nodes[1].automation_id = 'b';
  expect(axios.patch.mock.calls).toEqual([['/api/automations/test', expected]]);
  expect(axios.get.mock.calls.filter(call => call[0] === '/api/automations').length).toBe(1);
  await owner.reloadData(); expect(owner.state.data.draft.nodes[1].automation_id).toBe('b');
  expect(container.querySelector('.automation-target-preview-node').textContent).toContain('Beta');
});

}));
