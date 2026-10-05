import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import Automation from './Automation';
import AutomationWorkflowEditor from './AutomationWorkflowEditor';
import withLoadSave from '../components/LoadSave';

jest.mock('../utils/notify', () => ({show: jest.fn()}));
jest.mock('axios', () => ({get: jest.fn(), patch: jest.fn()}));

const definition = () => ({name: 'Email test', entry: {type: 'manual'}, reentry: 'once', draft: {nodes: [
  {id: 'branch', type: 'if_has_tag', draft_tag: 'vip', yes_node_id: 'email', no_node_id: 'exit'},
  {id: 'email', type: 'send_email', label: 'Welcome step', automation_email_id: 'welcome'},
  {id: 'other', type: 'send_email', automation_email_id: 'welcome'},
  {id: 'exit', type: 'exit'},
]}});
const emails = () => [
  {id: 'welcome', automation_id: 'test', name: 'Welcome email', subject: 'Hello', editor_type: 'html'},
  {id: 'followup', automation_id: 'test', name: 'Follow up email', subject: 'Next', editor_type: 'html'},
];
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(el => el.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const select = () => document.getElementById('automation-email-modal');
let container, owner, editor, availableEmails, beforeUpdate;
beforeEach(() => {
  availableEmails = emails(); beforeUpdate = null;
  container = document.createElement('div'); document.body.appendChild(container);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container); jest.clearAllMocks();
});
async function mount(data = definition()) {
  const Page = props => <AutomationWorkflowEditor ref={value => {editor = value;}}
    nodes={props.data.draft.nodes} emails={availableEmails}
    update={(spec, cb) => {if (beforeUpdate) beforeUpdate(); props.update(spec, cb);}}
    renderNodeContactCount={() => null} />;
  const Loaded = withLoadSave({extend: Page, initial: data, get: async () => data});
  owner = ReactDOM.render(<Loaded history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); TestUtils.Simulate.click(button(container, 'Visual preview'));
}
function open() {
  const trigger = container.querySelector('button[aria-label^="Edit Send email step 2:"]');
  trigger.focus(); TestUtils.Simulate.click(trigger);
  expect(dialog().textContent).toContain('Edit Send email step');
  return trigger;
}
function choose(value) {
  TestUtils.Simulate.change(select(), {target: {id: 'automation-email-modal', value}});
}

it('populates the current email using only supplied options, with no content editor or additional load', async () => {
  await mount(); const before = owner.state.data; open();
  expect(select().value).toBe('welcome');
  expect(Array.from(select().options).map(option => option.value)).toEqual(['', 'welcome', 'followup']);
  expect(dialog().querySelector('textarea')).toBe(null);
  choose('followup'); expect(select().value).toBe('followup'); expect(owner.state.data).toBe(before);
  expect(axios.get.mock.calls.length).toBe(0);
});

['Cancel', 'close', 'Escape'].forEach(action => {
  it(action + ' discards changes and returns focus', async () => {
    await mount(); const before = owner.state.data; const trigger = open(); choose('followup');
    if (action === 'Escape') {
      const event = document.createEvent('Event'); event.initEvent('keydown', true, true); event.keyCode = 27;
      select().dispatchEvent(event);
    } else TestUtils.Simulate.click(action === 'close' ? dialog().querySelector('.close') : button(dialog(), 'Cancel'));
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(dialog()).toBe(null); expect(owner.state.data).toBe(before); expect(document.activeElement).toBe(trigger);
    open(); expect(select().value).toBe('welcome');
  });
});

it('saves only the email reference once, preserves structure, and synchronizes both editor views', async () => {
  await mount(); const before = owner.state.data; open(); choose('followup');
  const update = jest.fn(); beforeUpdate = update;
  TestUtils.Simulate.click(button(dialog(), 'Save')); editor.saveNodeEditor();
  expect(update.mock.calls.length).toBe(1);
  const expected = clone(before); expected.draft.nodes[1].automation_email_id = 'followup';
  expect(owner.state.data).toEqual(expected);
  [0,2,3].forEach(index => expect(owner.state.data.draft.nodes[index]).toBe(before.draft.nodes[index]));
  expect(container.querySelector('.automation-email-preview-node').textContent).toContain('Follow up email');
  TestUtils.Simulate.click(button(container, 'Edit list')); editor.setState({expandedNodeIds: {email: true}});
  const field = container.querySelector('#automation_email_id'); expect(field.value).toBe('followup');
  TestUtils.Simulate.change(field, {target: {id: 'automation_email_id', value: 'welcome'}});
  expect(owner.state.data.draft.nodes[1].automation_email_id).toBe('welcome');
  TestUtils.Simulate.click(button(container, 'Visual preview'));
  expect(container.querySelector('.automation-email-preview-node').textContent).toContain('Welcome email');
});

it('resolves the stable ID after reordering', async () => {
  await mount(); open(); choose('followup'); const nodes = owner.state.data.draft.nodes;
  owner.updateData({draft: {nodes: {$set: [nodes[0], nodes[2], nodes[1], nodes[3]]}}});
  TestUtils.Simulate.click(button(dialog(), 'Save'));
  expect(owner.state.data.draft.nodes).toEqual([nodes[0], nodes[2], {...nodes[1], automation_email_id: 'followup'}, nodes[3]]);
});

['missing', 'duplicate', 'stale', 'type'].forEach(reason => {
  it('fails safely for a ' + reason + ' node target', async () => {
    await mount(); open(); choose('followup'); const nodes = clone(owner.state.data.draft.nodes);
    if (reason === 'missing') nodes.splice(1, 1);
    if (reason === 'duplicate') nodes.push(clone(nodes[1]));
    if (reason === 'stale') nodes[1].automation_email_id = 'newer';
    if (reason === 'type') nodes[1].type = 'exit';
    owner.updateData({draft: {nodes: {$set: nodes}}}); const before = owner.state.data;
    expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor();
    expect(owner.state.data).toBe(before); expect(dialog().querySelector('[role="alert"]').textContent).toContain('Send email step');
    expect(select().getAttribute('aria-invalid')).not.toBe('true');
  });
});

it('rechecks the canonical node inside the commit operation', async () => {
  await mount(); open(); choose('followup'); const changed = clone(owner.state.data);
  changed.draft.nodes[1].automation_email_id = 'newer';
  beforeUpdate = () => {owner.state.data = changed;}; editor.saveNodeEditor();
  expect(owner.state.data.draft.nodes[1].automation_email_id).toBe('newer');
  expect(dialog().querySelector('[role="alert"]')).not.toBe(null);
});

['', 'deleted'].forEach(value => {
  it('preserves an incomplete reference (' + value + ') until an explicit valid replacement is saved', async () => {
    const data = definition(); data.draft.nodes[1].automation_email_id = value;
    await mount(data); open(); expect(select().value).toBe(value);
    if (value) expect(select().options[select().selectedIndex].textContent).toBe('Selected email not found');
    expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
    choose('foreign-email'); editor.saveNodeEditor(); expect(owner.state.data).toBe(data);
    choose('followup'); TestUtils.Simulate.click(button(dialog(), 'Save'));
    expect(owner.state.data.draft.nodes[1].automation_email_id).toBe('followup');
  });
});

it('rejects an email removed from the loaded options while editing and explains an empty library', async () => {
  await mount(); open(); choose('followup'); const before = owner.state.data;
  availableEmails = []; owner.forceUpdate();
  expect(select().value).toBe('followup'); expect(dialog().textContent).toContain('No automation emails are available');
  expect(button(dialog(), 'Save').disabled).toBe(true); editor.saveNodeEditor(); expect(owner.state.data).toBe(before);
});

it('uses the scoped page email load and normal Save payload/reload without persisting modal state', async () => {
  let stored = {...definition(), id: 'test', status: 'draft'};
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/automations/test' ? clone(stored) :
    url === '/api/automations/test/emails' ? emails() :
    url.indexOf('/enrolments') !== -1 ? {summary: {}} : url.indexOf('/preflight') !== -1 ? {} : []}));
  axios.patch.mockImplementation((url, payload) => {stored = {...stored, ...clone(payload)}; return Promise.resolve({data: clone(stored)});});
  owner = ReactDOM.render(<Automation history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); editor = TestUtils.findRenderedComponentWithType(owner, AutomationWorkflowEditor);
  TestUtils.Simulate.click(button(container, 'Visual preview')); open();
  expect(Array.from(select().options).map(option => option.value)).toEqual(['', 'welcome', 'followup']);
  choose('followup'); TestUtils.Simulate.click(button(dialog(), 'Save')); expect(axios.patch.mock.calls.length).toBe(0);
  TestUtils.Simulate.click(button(container, 'Save')); await tick();
  const expected = definition(); expected.draft.nodes[1].automation_email_id = 'followup';
  expect(axios.patch.mock.calls).toEqual([['/api/automations/test', expected]]);
  await owner.reloadData(); expect(owner.state.data.draft.nodes[1].automation_email_id).toBe('followup');
  expect(container.querySelector('.automation-email-preview-node').textContent).toContain('Follow up email');
});

it('cancels a replacement without repairing the original stale reference', async () => {
  const data = definition(); data.draft.nodes[1].automation_email_id = 'deleted';
  await mount(data); open();
  expect(select().value).toBe('deleted');
  expect(select().options[select().selectedIndex].textContent).toBe('Selected email not found');
  expect(button(dialog(), 'Save').disabled).toBe(true);
  expect(owner.state.data).toBe(data);
  choose('followup'); expect(button(dialog(), 'Save').disabled).toBe(false);
  TestUtils.Simulate.click(button(dialog(), 'Cancel'));
  await new Promise(resolve => setTimeout(resolve, 350));
  expect(dialog()).toBe(null); expect(owner.state.data).toBe(data);
  expect(container.querySelector('.automation-email-preview-node').textContent).toContain('Selected email not found');
  open(); expect(select().value).toBe('deleted');
  expect(button(dialog(), 'Save').disabled).toBe(true);
});
