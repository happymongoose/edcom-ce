import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import Automation from './Automation';
import AutomationWorkflowEditor from './AutomationWorkflowEditor';
import withLoadSave from '../components/LoadSave';

jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn()}));

// Both actions share the same field, lifecycle and guarded-commit contract.
['add_to_list', 'remove_from_list'].forEach(actionType => {
const actionLabel = actionType === 'add_to_list' ? 'Add to list' : 'Remove from list';
describe(actionLabel, () => {
const definition = () => ({name: 'List test', entry: {type: 'manual'}, reentry: 'once', draft: {nodes: [
  {id: 'branch', type: 'if_has_tag', draft_tag: 'vip', yes_node_id: 'list', no_node_id: 'exit'},
  {id: 'list', type: actionType, label: 'Welcome step', list_id: 'welcome'},
  {id: 'other', type: actionType === 'add_to_list' ? 'remove_from_list' : 'add_to_list', list_id: 'welcome'},
  {id: 'exit', type: 'exit'},
]}});
const lists = () => [
  {id: 'welcome', name: 'Welcome list', count: 10},
  {id: 'followup', name: 'Follow up list', count: 20},
];
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(el => el.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const select = () => document.getElementById('automation-list-modal');
let container, owner, editor, availableLists, beforeUpdate;
beforeEach(() => {
  availableLists = lists(); beforeUpdate = null;
  container = document.createElement('div'); document.body.appendChild(container);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container); jest.clearAllMocks();
});
async function mount(data = definition()) {
  const Page = props => <AutomationWorkflowEditor ref={value => {editor = value;}}
    nodes={props.data.draft.nodes} lists={availableLists}
    update={(spec, cb) => {if (beforeUpdate) beforeUpdate(); props.update(spec, cb);}}
    renderNodeContactCount={() => null} />;
  const Loaded = withLoadSave({extend: Page, initial: data, get: async () => data});
  owner = ReactDOM.render(<Loaded history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); TestUtils.Simulate.click(button(container, 'Visual preview'));
}
function open() {
  const trigger = container.querySelector('button[aria-label^="Edit ' + actionLabel + ' step 2:"]');
  trigger.focus(); TestUtils.Simulate.click(trigger);
  expect(dialog().textContent).toContain('Edit ' + actionLabel + ' step');
  return trigger;
}
function choose(value) {
  TestUtils.Simulate.change(select(), {target: {id: 'automation-list-modal', value}});
}

it('populates the current list using only supplied options, without an additional load or enabling other node types', async () => {
  await mount(); const before = owner.state.data; open();
  expect(select().value).toBe('welcome');
  expect(Array.from(select().options).map(option => option.value)).toEqual(['', 'welcome', 'followup']);
  expect(container.querySelectorAll('.automation-list-preview-node').length).toBe(2);
  expect(container.querySelector('button[aria-label*="step 1:"]')).toBe(null);
  choose('followup'); expect(select().value).toBe('followup'); expect(owner.state.data).toBe(before);
  expect(axios.get.mock.calls.length).toBe(0);
});

['welcome', 'deleted'].forEach(reference => ['Cancel', 'close', 'Escape'].forEach(action => {
  it(action + ' discards changes and returns focus for ' + reference, async () => {
    const data = definition(); data.draft.nodes[1].list_id = reference;
    await mount(data); const before = owner.state.data; const trigger = open(); choose('followup');
    if (action === 'Escape') {
      const event = document.createEvent('Event'); event.initEvent('keydown', true, true); event.keyCode = 27;
      select().dispatchEvent(event);
    } else TestUtils.Simulate.click(action === 'close' ? dialog().querySelector('.close') : button(dialog(), 'Cancel'));
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(dialog()).toBe(null); expect(owner.state.data).toBe(before); expect(document.activeElement).toBe(trigger);
    open(); expect(select().value).toBe(reference === 'deleted' ? '' : reference);
    if (reference === 'deleted') expect(select().options[select().selectedIndex].textContent).toBe('Selected list not found');
  });
}));

it('edits multiple lists locally, rejects duplicates and saves canonical plural references in both views', async () => {
  await mount(); const before = owner.state.data; open();
  TestUtils.Simulate.click(button(dialog(), 'Add another list'));
  expect(button(dialog(), 'Save').disabled).toBe(true);
  const extra = dialog().querySelector('#automation-list-modal-1');
  TestUtils.Simulate.change(extra, {target: {value: 'welcome'}});
  expect(dialog().textContent).toContain('Select each list only once');
  expect(button(dialog(), 'Save').disabled).toBe(true);
  TestUtils.Simulate.change(extra, {target: {value: 'followup'}});
  expect(owner.state.data).toBe(before);
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes[1]).toEqual({...before.draft.nodes[1], list_id: undefined, list_ids: ['welcome', 'followup']});
  expect(Object.prototype.hasOwnProperty.call(owner.state.data.draft.nodes[1], 'list_id')).toBe(false);
  expect(container.querySelector('.automation-list-preview-node').textContent).toContain('Welcome list (10 contacts), Follow up list (20 contacts)');
  TestUtils.Simulate.click(button(container, 'Edit list')); editor.setState({expandedNodeIds: {list: true}});
  expect(container.querySelector('#list_id-1').value).toBe('followup');
  TestUtils.Simulate.click(container.querySelector('[aria-label="Remove selected list 2"]'));
  expect(owner.state.data.draft.nodes[1].list_id).toBe('welcome');
  expect(owner.state.data.draft.nodes[1].list_ids).toBe(undefined);
});

it('preserves plural stale references on cancel', async () => {
  const data = definition(); delete data.draft.nodes[1].list_id; data.draft.nodes[1].list_ids = ['welcome', 'deleted'];
  await mount(data); open();
  expect(dialog().textContent).toContain('Selected list not found');
  expect(button(dialog(), 'Save').disabled).toBe(true);
  TestUtils.Simulate.change(dialog().querySelector('#automation-list-modal-1'), {target: {value: 'followup'}});
  TestUtils.Simulate.click(button(dialog(), 'Cancel'));
  await new Promise(resolve => setTimeout(resolve, 350));
  expect(owner.state.data).toBe(data);
});

it('saves only the list reference once, preserves structure, and synchronizes both editor views', async () => {
  await mount(); const before = owner.state.data; open(); choose('followup');
  const update = jest.fn(); beforeUpdate = update;
  TestUtils.Simulate.click(button(dialog(), 'Save')); editor.saveNodeEditor();
  expect(update.mock.calls.length).toBe(1);
  const expected = clone(before); expected.draft.nodes[1].list_id = 'followup';
  expect(owner.state.data).toEqual(expected);
  [0,2,3].forEach(index => expect(owner.state.data.draft.nodes[index]).toBe(before.draft.nodes[index]));
  expect(container.querySelector('.automation-list-preview-node').textContent).toContain('Follow up list');
  TestUtils.Simulate.click(button(container, 'Edit list')); editor.setState({expandedNodeIds: {list: true}});
  const field = container.querySelector('#list_id'); expect(field.value).toBe('followup');
  TestUtils.Simulate.change(field, {target: {id: 'list_id', value: 'welcome'}});
  expect(owner.state.data.draft.nodes[1].list_id).toBe('welcome');
  TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(container.querySelector('.automation-list-preview-node').textContent).toContain('Welcome list');
});

it('resolves the stable ID after reordering', async () => {
  await mount(); open(); choose('followup'); const nodes = owner.state.data.draft.nodes;
  owner.updateData({draft: {nodes: {$set: [nodes[0], nodes[2], nodes[1], nodes[3]]}}});
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes).toEqual([nodes[0], nodes[2], {...nodes[1], list_id: 'followup'}, nodes[3]]);
});

['missing', 'duplicate', 'stale', 'type'].forEach(reason => {
  it('fails safely for a ' + reason + ' node target', async () => {
    await mount(); open(); choose('followup'); const nodes = clone(owner.state.data.draft.nodes);
    if (reason === 'missing') nodes.splice(1, 1);
    if (reason === 'duplicate') nodes.push(clone(nodes[1]));
    if (reason === 'stale') nodes[1].list_id = 'newer';
    if (reason === 'type') nodes[1].type = actionType === 'add_to_list' ? 'remove_from_list' : 'add_to_list';
    owner.updateData({draft: {nodes: {$set: nodes}}}); const before = owner.state.data;
    expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor();
    expect(owner.state.data).toBe(before); expect(dialog().querySelector('[role="alert"]').textContent).toContain(actionLabel + ' step');
    expect(select().getAttribute('aria-invalid')).not.toBe('true');
  });
});

it('rechecks the canonical node inside the commit operation', async () => {
  await mount(); open(); choose('followup'); const changed = clone(owner.state.data);
  changed.draft.nodes[1].list_id = 'newer';
  beforeUpdate = () => {owner.state.data = changed;}; editor.saveNodeEditor();
  expect(owner.state.data.draft.nodes[1].list_id).toBe('newer');
  expect(dialog().querySelector('[role="alert"]')).not.toBe(null);
});

['', 'deleted'].forEach(value => {
  it('preserves an incomplete reference (' + value + ') until an explicit valid replacement is saved', async () => {
    const data = definition(); data.draft.nodes[1].list_id = value;
    await mount(data); open(); expect(select().value).toBe('');
    if (value) expect(select().options[select().selectedIndex].textContent).toBe('Selected list not found');
    expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
    choose('foreign-list'); editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
    choose('followup'); TestUtils.Simulate.click(button(dialog(), 'Save'));
    expect(owner.state.data.draft.nodes[1].list_id).toBe('followup');
  });
});

it('rejects a list removed from the loaded options while editing and explains an empty library', async () => {
  await mount(); open(); choose('followup'); const before = owner.state.data;
  availableLists = []; owner.forceUpdate();
  expect(select().value).toBe('');
  expect(select().options[select().selectedIndex].textContent).toBe('Selected list not found');
  expect(dialog().textContent).toContain('No contact lists are available');
  expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor(); expect(owner.state.data).toBe(before);
});

it('uses the scoped page list load and normal Save payload/reload without persisting modal state', async () => {
  let stored = {...definition(), id: 'test', status: 'draft'};
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/automations/test' ? clone(stored) :
    url === '/api/lists' ? lists() :
    url.indexOf('/enrolments') !== -1 ? {summary: {}} : url.indexOf('/preflight') !== -1 ? {} : []}));
  axios.patch.mockImplementation((url, payload) => {stored = {...stored, ...clone(payload)}; return Promise.resolve({data: clone(stored)});});
  owner = ReactDOM.render(<Automation history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); editor = TestUtils.findRenderedComponentWithType(owner, AutomationWorkflowEditor);
  TestUtils.Simulate.click(button(container, 'Visual preview')); open();
  expect(Array.from(select().options).map(option => option.value)).toEqual(['', 'followup', 'welcome']);
  choose('followup'); TestUtils.Simulate.click(button(dialog(), 'Save')); expect(axios.patch.mock.calls.length).toBe(0);
  TestUtils.Simulate.click(button(container, 'Save')); await tick();
  const expected = definition(); expected.draft.nodes[1].list_id = 'followup';
  expect(axios.patch.mock.calls).toEqual([['/api/automations/test', expected]]);
  await owner.reloadData(); expect(owner.state.data.draft.nodes[1].list_id).toBe('followup');
  expect(container.querySelector('.automation-list-preview-node').textContent).toContain('Follow up list');
});

it('cancels a replacement without repairing the original stale reference', async () => {
  const data = definition(); data.draft.nodes[1].list_id = 'deleted';
  await mount(data); open();
  expect(select().value).toBe('');
  expect(select().options[select().selectedIndex].textContent).toBe('Selected list not found');
  expect(button(dialog(), 'Save').disabled).toBe(true);
  expect(owner.state.data).toBe(data);
  choose('followup'); expect(button(dialog(), 'Save').disabled).toBe(false);
  TestUtils.Simulate.click(button(dialog(), 'Cancel'));
  await new Promise(resolve => setTimeout(resolve, 350));
  expect(dialog()).toBe(null); expect(owner.state.data).toBe(data);
  expect(container.querySelector('.automation-list-preview-node').textContent).toContain('Selected list not found');
  open(); expect(select().value).toBe('');
  expect(button(dialog(), 'Save').disabled).toBe(true);
});

it('persists plural references through the established page Save and reload path', async () => {
  let stored = {...definition(), id: 'test', status: 'draft'};
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/automations/test' ? clone(stored) :
    url === '/api/lists' ? lists() : url.indexOf('/enrolments') !== -1 ? {summary: {}} : url.indexOf('/preflight') !== -1 ? {} : []}));
  axios.patch.mockImplementation((url, payload) => {stored = {...stored, ...clone(payload)}; return Promise.resolve({data: clone(stored)});});
  owner = ReactDOM.render(<Automation history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); editor = TestUtils.findRenderedComponentWithType(owner, AutomationWorkflowEditor);
  open(); TestUtils.Simulate.click(button(dialog(), 'Add another list'));
  TestUtils.Simulate.change(dialog().querySelector('#automation-list-modal-1'), {target: {value: 'followup'}});
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(axios.patch).not.toHaveBeenCalled();
  TestUtils.Simulate.click(button(container, 'Save')); await tick();
  expect(axios.patch.mock.calls[0][1].draft.nodes[1].list_ids).toEqual(['welcome', 'followup']);
  expect(axios.patch.mock.calls[0][1].draft.nodes[1].list_id).toBe(undefined);
  await owner.reloadData(); open();
  expect(select().value).toBe('welcome'); expect(dialog().querySelector('#automation-list-modal-1').value).toBe('followup');
});

it('does not coerce a malformed numeric reference into a valid string list ID', async () => {
  availableLists = [{id: '7', name: 'Seven'}, {id: '007', name: 'Leading zeros'}];
  const data = definition(); data.draft.nodes[1].list_id = 7;
  await mount(data); open();
  expect(select().value).toBe('');
  expect(select().options[select().selectedIndex].textContent).toBe('Selected list not found');
  expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor();
  expect(owner.state.data).toBe(data); expect(owner.state.data.draft.nodes[1].list_id).toBe(7);
  choose('007'); TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes[1].list_id).toBe('007');
});

});
});
