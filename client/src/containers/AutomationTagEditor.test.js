import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import $ from 'jquery';
import axios from 'axios';
import Automation from './Automation';
import AutomationWorkflowEditor from './AutomationWorkflowEditor';
import withLoadSave from '../components/LoadSave';
import { automationTagError } from './AutomationTagField';

// The installed Select2 CommonJS build exports an initializer. Use the real
// plugin and wrapper; neither is mocked in this suite.
require('select2')(window, $);
jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn()}));

let actionType = 'add_tag';
const actionLabel = () => actionType === 'remove_tag' ? 'Remove tag' : 'Add tag';

// Share the action contract; keep Select2-specific tests below single-run.
function tagActionTest(name, run) {
  ['add_tag', 'remove_tag'].forEach(type => {
    it((type === 'remove_tag' ? 'Remove tag: ' : '') + name, async () => {
      actionType = type;
      await run();
    });
  });
}

const definition = () => ({name: 'Tag test', entry: {type: 'manual'}, reentry: 'once', draft: {nodes: [
  {id: 'branch', type: 'if_has_tag', label: 'Branch', draft_tag: 'vip', yes_node_id: 'tag', no_node_id: 'exit'},
  {id: 'tag', type: actionType, label: 'Welcome tag', draft_tag: 'welcome'},
  {id: 'other', type: 'add_tag', label: 'Other tag', draft_tag: 'other'},
  {id: 'exit', type: 'exit', label: 'Exit'},
]}});

tagActionTest('edits multiple tags locally, validates duplicates and commits one plural configuration', async () => {
  await mount(); open(); const before = clone(owner.state.data);
  select().trigger({type:'select2:select', params:{data:{id:'welcome'}}});
  expect(chips()).toEqual(['welcome']);
  await choose('existing', false, true);
  expect(chips()).toEqual(['welcome', 'existing']);
  expect(select().val()).toBe('');
  expect(owner.state.data).toEqual(before);
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes[1].draft_tags).toEqual(['welcome','existing']);
  expect(owner.state.data.draft.nodes[1].draft_tag).toBeUndefined();
  expect(container.querySelector('.automation-tag-preview-node').textContent).toContain('welcome, existing');
  TestUtils.Simulate.click(container.querySelector('button[aria-label^="Edit ' + actionLabel() + ' step 2:"]'));
  TestUtils.Simulate.click(dialog().querySelector('button.gray_tag'));
  TestUtils.Simulate.click(button(dialog(), 'Cancel'));
  expect(owner.state.data.draft.nodes[1].draft_tags).toEqual(['welcome','existing']);
});
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(el => el.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const select = () => $('#automation-tag-modal');
const chips = (root = dialog()) => Array.from(root.querySelectorAll('button.gray_tag')).map(node => node.textContent);
let container, owner, editor, beforeUpdate;

beforeEach(() => {
  actionType = 'add_tag';
  beforeUpdate = null;
  container = document.createElement('div'); document.body.appendChild(container);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);
  jest.clearAllMocks();
});
async function mount(data = definition()) {
  const Page = props => <AutomationWorkflowEditor ref={value => {editor = value;}}
    nodes={props.data.draft.nodes} tags={['welcome', 'other', 'existing', 'Legacy TAG']}
    update={(spec, cb) => {if (beforeUpdate) beforeUpdate(); props.update(spec, cb);}}
    renderNodeContactCount={() => null} />;
  const Loaded = withLoadSave({extend: Page, initial: data, get: async () => data});
  owner = ReactDOM.render(<Loaded history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); TestUtils.Simulate.click(button(container, 'Visual preview'));
}
function open() {
  const trigger = container.querySelector('button[aria-label^="Edit ' + actionLabel() + ' step 2:"]');
  trigger.focus(); TestUtils.Simulate.click(trigger);
  expect(dialog().textContent).toContain('Edit ' + actionLabel() + ' step');
  const matches = owner.state.data.draft.nodes.filter(node => node.id === 'tag');
  const original = matches.length === 1 && matches[0].type === actionType ? matches[0] : null;
  expect(select().val()).toBe('');
  if (original) expect(chips()).toEqual((original.draft_tags || [original.draft_tag]).filter(Boolean));
  return trigger;
}
async function dropdown(term) {
  if (!select().data('select2').isOpen()) {
    $(dialog()).find('.select2-selection').trigger($.Event('mousedown', {which: 1}));
  }
  await tick();
  const search = $(dialog()).find('.select2-search__field');
  search.val(term).trigger('input');
  return search;
}
async function choose(term, keyboard = false, append = false) {
  if (!append) Array.from(dialog().querySelectorAll('button.gray_tag')).forEach(node => TestUtils.Simulate.click(node));
  const search = await dropdown(term);
  if (keyboard) {
    search.trigger($.Event('keydown', {which: 13, keyCode: 13}));
  } else {
    const result = $(dialog()).find('.select2-results__option[aria-selected]').filter(function () {
      return $(this).text() === term;
    }).first();
    expect(result.length).toBe(1); result.trigger('mouseup');
  }
}

it('opens the Add tag dialog with the existing value and keeps Select2 inside its focus boundary', async () => {
  await mount(); const before = owner.state.data; open();
  expect(dialog().textContent).toContain('Edit Add tag step');
  expect(chips()).toEqual(['welcome']);
  expect(container.querySelectorAll('.automation-tag-preview-node').length).toBe(2);
  $(dialog()).find('.select2-selection').trigger($.Event('keydown', {which: 13, keyCode: 13}));
  expect(select().data('select2').isOpen()).toBe(true);
  const search = await dropdown('existing');
  search[0].focus();
  expect(dialog().contains(document.activeElement)).toBe(true);
  expect(dialog().contains(document.querySelector('.select2-dropdown'))).toBe(true);
  expect(select().data('select2').options.get('dropdownParent').closest('[role="dialog"]')[0]).toBe(dialog());
  expect(owner.state.data).toBe(before);
});

['Cancel', 'close', 'Escape'].forEach(action => {
  tagActionTest(action + ' discards local changes and tears down the open dropdown', async () => {
    await mount(); const before = owner.state.data; const trigger = open();
    await choose('existing');
    expect(chips()).toEqual(['existing']); expect(owner.state.data).toBe(before);
    await dropdown('other');
    if (action === 'Escape') {
      // Native bubbling reaches React Bootstrap even if the search is focused.
      const event = document.createEvent('Event'); event.initEvent('keydown', true, true); event.keyCode = 27;
      dialog().querySelector('.select2-search__field').dispatchEvent(event);
    } else TestUtils.Simulate.click(action === 'close' ? dialog().querySelector('.close') : button(dialog(), 'Cancel'));
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(document.querySelector('[role="dialog"]')).toBe(null);
    expect(document.querySelector('.select2-dropdown')).toBe(null);
    expect(owner.state.data).toBe(before);
    expect(document.activeElement).toBe(trigger);
    open(); expect(chips()).toEqual(['welcome']);
  });
});

tagActionTest('normalizes a new tag through real Select2 keyboard selection and updates only the canonical tag', async () => {
  await mount(); const before = owner.state.data; open();
  await choose('  New-VIP! #1  ', true);
  expect(chips()).toEqual(['newvip #1']); expect(owner.state.data).toBe(before);
  TestUtils.Simulate.click(button(dialog(), 'Save')); editor.saveNodeEditor();
  const expected = clone(before); expected.draft.nodes[1].draft_tag = 'newvip #1';
  expect(owner.state.data).toEqual(expected);
  expect(owner.state.data.draft.nodes[0]).toBe(before.draft.nodes[0]);
  expect(owner.state.data.draft.nodes[2]).toBe(before.draft.nodes[2]);
  expect(container.querySelector('.automation-tag-preview-node').textContent).toContain('newvip #1');
  TestUtils.Simulate.click(button(container, 'Edit list'));
  editor.setState({expandedNodeIds: {tag: true}});
  expect(chips(container)).toContain('newvip #1');
  TestUtils.Simulate.click(container.querySelector('button[aria-label="Remove tag newvip #1"]'));
  // The list uses the same real tag field and creation behavior.
  $('#node-tag-tag').select2('open');
  const search = $('.select2-search__field'); search.val('  List-New!  ').trigger('input');
  search.trigger($.Event('keydown', {which: 13, keyCode: 13}));
  expect(owner.state.data.draft.nodes[1].draft_tag).toBe('listnew');
  TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(container.querySelector('.automation-tag-preview-node').textContent).toContain('listnew');
});

tagActionTest('preserves an existing tag verbatim rather than renormalizing stored values', async () => {
  await mount(); open(); await choose('Legacy TAG');
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes[1].draft_tag).toBe('Legacy TAG');
});

tagActionTest('commits by ID after reordering without changing branch references or other nodes', async () => {
  await mount(); open(); await choose('existing');
  const nodes = owner.state.data.draft.nodes;
  owner.updateData({draft: {nodes: {$set: [nodes[0], nodes[2], nodes[1], nodes[3]]}}});
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['branch','other','tag','exit']);
  expect(owner.state.data.draft.nodes[2].draft_tag).toBe('existing');
  expect(owner.state.data.draft.nodes[0]).toBe(nodes[0]); expect(owner.state.data.draft.nodes[1]).toBe(nodes[2]);
});

['missing', 'duplicate', 'stale', 'type'].forEach(reason => {
  tagActionTest('rejects a ' + reason + ' target without marking the tag field invalid', async () => {
    await mount(); open(); await choose('existing');
    const nodes = clone(owner.state.data.draft.nodes);
    if (reason === 'missing') nodes.splice(1,1);
    if (reason === 'duplicate') nodes.push(clone(nodes[1]));
    if (reason === 'stale') nodes[1].draft_tag = 'changed';
    if (reason === 'type') nodes[1].type = actionType === 'add_tag' ? 'remove_tag' : 'add_tag';
    owner.updateData({draft: {nodes: {$set: nodes}}}); const before = owner.state.data;
    expect(button(dialog(), 'Save').disabled).toBe(true);
    expect(select().attr('aria-invalid')).not.toBe('true');
    editor.saveNodeEditor(); expect(owner.state.data).toBe(before);
    expect(dialog().querySelector('[role="alert"]').textContent).toContain(actionLabel() + ' step');
  });
});

it('rejects duplicate IDs already present on open and rechecks the canonical array at commit', async () => {
  await mount(); const data = clone(owner.state.data); data.draft.nodes.push(clone(data.draft.nodes[1]));
  owner.updateData({$set:data}); open(); expect(button(dialog(), 'Save').disabled).toBe(true);
  TestUtils.Simulate.click(button(dialog(), 'Cancel'));
  owner.updateData({$set:definition()}); open(); await choose('existing');
  const changed = clone(owner.state.data); changed.draft.nodes[1].draft_tag = 'newer';
  beforeUpdate = () => {owner.state.data = changed;}; editor.saveNodeEditor();
  expect(owner.state.data.draft.nodes[1].draft_tag).toBe('newer');
  expect(dialog().querySelector('[role="alert"]')).not.toBe(null);
});

tagActionTest('prevents empty tags, rejects empty normalized creations, and enforces the existing schema length', async () => {
  const data = definition(); data.draft.nodes[1].draft_tag = ''; await mount(data); open();
  expect(button(dialog(), 'Save').disabled).toBe(true);
  await dropdown('!!!'); expect($(dialog()).find('.select2-results__option[aria-selected]').length).toBe(0);
  editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
  await choose('x'.repeat(1025), true);
  expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
  expect(automationTagError('x'.repeat(1024))).toBe('');
});

[false, true].forEach(plural => tagActionTest('uses the real page Save payload and reload without persisting modal state (' + (plural ? 'multiple tags' : 'single tag') + ')', async () => {
  let stored = {...definition(), id:'test', status:'draft'};
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/automations/test' ? clone(stored) :
    url.indexOf('/enrolments') !== -1 ? {summary:{}} : url.indexOf('/preflight') !== -1 ? {} : []}));
  axios.patch.mockImplementation((url,payload) => {stored={...stored,...clone(payload)};return Promise.resolve({data:clone(stored)});});
  owner=ReactDOM.render(<Automation history={{location:{search:''}}} match={{params:{id:'test'}}}/>,container);
  await tick(); editor=TestUtils.findRenderedComponentWithType(owner,AutomationWorkflowEditor);
  TestUtils.Simulate.click(button(container,'Visual preview')); open(); await choose('  New-Tag! ',true);
  if (plural) {
    await choose('other', false, true);
  }
  TestUtils.Simulate.click(button(dialog(),'Save')); expect(axios.patch.mock.calls.length).toBe(0);
  TestUtils.Simulate.click(button(container,'Save')); await tick();
  const expected=definition();expected.draft.nodes[1].draft_tag='newtag';
  if (plural) {delete expected.draft.nodes[1].draft_tag; expected.draft.nodes[1].draft_tags = ['newtag', 'other'];}
  expect(axios.patch.mock.calls).toEqual([['/api/automations/test',expected]]);
  await owner.reloadData(); expect(owner.state.data.draft.nodes[1]).toEqual(expected.draft.nodes[1]);
  expect(container.querySelector('.automation-tag-preview-node').textContent).toContain('newtag');
}));
