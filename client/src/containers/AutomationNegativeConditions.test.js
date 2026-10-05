import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import $ from 'jquery';
import axios from 'axios';
import AutomationWorkflowEditor from './AutomationWorkflowEditor';
import withLoadSave from '../components/LoadSave';

require('select2')(window, $);
jest.mock('axios', () => ({get: jest.fn()}));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const click = node => TestUtils.Simulate.click(node);
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(node => node.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const change = (id, value) => TestUtils.Simulate.change(dialog().querySelector('#' + id), {target: {id, value}});
const lists = [{id: 'list-a', name: 'Customers'}, {id: 'list-b', name: 'Paid'}];
const emails = [{id: 'email-a', name: 'Welcome'}, {id: 'email-b', name: 'Follow up'}];
let container, owner, stored;
beforeEach(() => {
  container = document.createElement('div'); document.body.appendChild(container);
  axios.get.mockReset();
  axios.get.mockImplementation(() => Promise.resolve({data: {links: []}}));
});
afterEach(() => {ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);});
async function mount(item) {
  stored = {draft: {nodes: [
    {id: 'condition', type: 'if_conditions', label: 'Check', condition: {mode: 'all', items: [item]}, yes_node_id: 'yes', no_node_id: 'no'},
    {id: 'yes', type: 'exit', label: 'Yes end'}, {id: 'no', type: 'exit', label: 'No end'},
  ]}};
  const Page = props => <AutomationWorkflowEditor automationId="automation-a" nodes={props.data.draft.nodes}
    emails={emails} lists={lists} tags={[]} update={props.update} renderNodeContactCount={() => '0 live contacts'} />;
  const Loaded = withLoadSave({extend: Page, initial: stored, get: async () => stored,
    patch: async ({data}) => {stored = JSON.parse(JSON.stringify(data)); return stored;}});
  owner = ReactDOM.render(<Loaded history={{location: {search: ''}}} match={{params: {id: 'automation-a'}}} />, container);
  await tick();
  click(container.querySelector('button.automation-condition-preview-node'));
}

['in_list', 'not_in_list'].forEach(type => it(type + ' selects multiple lists with no default, buffers, persists and shares the canonical condition', async () => {
  await mount({type, list_ids: []});
  const before = owner.state.data;
  expect(dialog().textContent).toContain(type === 'in_list' ? 'Is in any of these lists' : 'Not in any of these lists');
  expect(dialog().querySelector('#condition-list-picker').value).toBe('');
  expect(button(dialog(), 'Save step').disabled).toBe(true);
  change('condition-list-picker', 'list-a'); change('condition-list-picker', 'list-b');
  expect(owner.state.data).toBe(before);
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes[0]).toEqual({...before.draft.nodes[0], condition: {mode: 'all', items: [{type, list_ids: ['list-a', 'list-b']}]}});
  expect(owner.state.data.draft.nodes.slice(1)).toEqual(before.draft.nodes.slice(1));
  expect(container.textContent).toContain('in any of these lists: Customers, Paid');
  await owner.saveData(); await owner.reloadData();
  click(button(container, 'Edit list'));
  expect(container.textContent).toContain('Customers, Paid');
}));

['cancel', 'close', 'escape'].forEach(method => it('preserves singular legacy selections on ' + method, async () => {
  await mount({type: 'not_in_list', list_id: 'list-a'});
  const before = owner.state.data;
  change('condition-list-picker', 'list-b');
  if (method === 'cancel') click(button(dialog(), 'Cancel'));
  if (method === 'close') click(dialog().querySelector('.close'));
  if (method === 'escape') document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 27, bubbles: true}));
  await new Promise(resolve => setTimeout(resolve, 350));
  expect(dialog()).toBe(null);
  expect(owner.state.data).toBe(before);
}));

['has_tag', 'missing_tag'].forEach(type => it(type + ' uses tag chips and existing normalization for multiple tags', async () => {
  await mount({type, tag: 'legacy'});
  const before = owner.state.data;
  const picker = $('#condition-tags-0-0');
  const tag = picker.data('select2').options.get('createTag')({term: ' New Tag '});
  picker.trigger({type: 'select2:select', params: {data: tag}});
  expect(owner.state.data).toBe(before);
  expect(dialog().querySelector('[aria-label="Remove tag new tag"]')).not.toBe(null);
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes[0].condition.items[0]).toEqual({type, tags: ['legacy', 'new tag']});
}));

it('orders the condition choices alphabetically by their displayed labels', async () => {
  await mount({type: 'has_tag', tag: 'legacy'});
  const labels = Array.from(dialog().querySelector('#type').options).map(option => option.textContent);
  expect(labels.length).toBe(8);
  expect(labels).toEqual(labels.slice().sort((a, b) => a.localeCompare(b)));
});

['opened_email', 'not_opened_email', 'clicked_email', 'not_clicked_email'].forEach(type => {
  it('edits ' + type + ' through the shared email/link controls', async () => {
    await mount({type: 'has_tag', tag: 'old'});
    const before = owner.state.data;
    change('type', type);
    change('automation_email_id', 'email-b');
    if (type.includes('clicked')) {
      change('click_match', 'url_exact');
      expect(button(dialog(), 'Save step').disabled).toBe(true);
      change('link_url', 'https://example.com/offer');
      await tick();
      expect(axios.get).toHaveBeenCalled();
    }
    expect(dialog().textContent).toContain('current enrolment only');
    expect(owner.state.data).toBe(before);
    click(button(dialog(), 'Save step'));
    const item = owner.state.data.draft.nodes[0].condition.items[0];
    expect(item.type).toBe(type); expect(item.automation_email_id).toBe('email-b');
    expect(item.tag).toBe(undefined);
    expect(container.textContent).toContain('Follow up');
  });
});

it('keeps a stale email explicit and invalid until deliberately replaced', async () => {
  await mount({type: 'not_opened_email', automation_email_id: 'deleted'});
  const before = owner.state.data;
  expect(dialog().textContent).toContain('Selected email not found');
  expect(dialog().querySelector('#automation_email_id').value).toBe('deleted');
  expect(button(dialog(), 'Save step').disabled).toBe(true);
  expect(owner.state.data).toBe(before);
  change('automation_email_id', 'email-a'); click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes[0].condition.items[0].automation_email_id).toBe('email-a');
});

it('requires removal or replacement of a stale list without coercing its ID', async () => {
  await mount({type: 'not_in_list', list_ids: ['missing', 1]});
  expect(dialog().textContent).toContain('Selected list not found');
  expect(button(dialog(), 'Save step').disabled).toBe(true);
  click(dialog().querySelector('[aria-label="Remove list missing"]'));
  click(dialog().querySelector('[aria-label="Remove list 1"]'));
  change('condition-list-picker', 'list-a'); click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes[0].condition.items[0].list_ids).toEqual(['list-a']);
});
