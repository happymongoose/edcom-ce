import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import AutomationExitRules from './AutomationExitRules';
import $ from 'jquery';
require('select2')(window, $);

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(el => el.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
let container, value, onChange, editing;
const lists = [{id: 'AbC', name: 'Customers'}, {id: 'abc', name: 'Prospects'}];
function render() {
  ReactDOM.render(<AutomationExitRules value={value} lists={lists} tags={[{id: 'paid', text: 'paid'}]}
    onChange={next => {onChange(next); value = next; render();}} onEditingChange={editing} />, container);
}
function choose(type) {TestUtils.Simulate.change(document.getElementById('exit-rule-type'), {target: {value: type}});}
function selectTag() {$('#exit-rule-tags').trigger({type: 'select2:select', params: {data: {id: 'paid'}}});}
beforeEach(() => {
  container = document.createElement('div'); document.body.appendChild(container);
  value = []; onChange = jest.fn(); editing = jest.fn(); render();
});
afterEach(() => {ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);});
it('starts unselected and saves only a valid temporary rule', async () => {
  TestUtils.Simulate.click(button(container, 'Add exit rule')); await tick();
  expect(document.getElementById('exit-rule-type').value).toBe('');
  expect(button(dialog(), 'Save rule').disabled).toBe(true);
  choose('has_tag'); await tick(); selectTag();
  expect(onChange).not.toHaveBeenCalled(); expect(value).toEqual([]);
  TestUtils.Simulate.click(button(dialog(), 'Save rule'));
  expect(value).toEqual([{type: 'has_tag', tags: ['paid']}]);
  expect(container.textContent).toContain('Has any of these tags: paid');
  expect(onChange.mock.calls.length).toBe(1); expect(editing).toHaveBeenLastCalledWith(false);
});
['cancel', 'close', 'Escape'].forEach(method => it('discards temporary changes on ' + method, async () => {
  value = [{type: 'has_tag', tags: ['original']}]; render();
  TestUtils.Simulate.click(button(container, 'Edit rule 1')); await tick(); selectTag();
  if (method === 'cancel') TestUtils.Simulate.click(button(dialog(), 'Cancel'));
  else if (method === 'close') TestUtils.Simulate.click(dialog().querySelector('.close'));
  else {const event = new window.Event('keydown', {bubbles: true}); event.keyCode = 27; document.dispatchEvent(event);}
  await tick();
  expect(onChange).not.toHaveBeenCalled(); expect(value[0].tags).toEqual(['original']);
  expect(editing).toHaveBeenLastCalledWith(false);
}));
it('reuses the multi-list selector and preserves case-sensitive IDs', async () => {
  TestUtils.Simulate.click(button(container, 'Add exit rule')); choose('in_list');
  TestUtils.Simulate.change(document.getElementById('exit-rule-lists'), {target: {value: 'AbC'}});
  TestUtils.Simulate.click(button(dialog(), 'Add another list'));
  expect(button(dialog(), 'Save rule').disabled).toBe(true);
  TestUtils.Simulate.change(document.getElementById('exit-rule-lists-1'), {target: {value: 'abc'}});
  TestUtils.Simulate.click(button(dialog(), 'Save rule'));
  expect(value).toEqual([{type: 'in_list', list_ids: ['AbC', 'abc']}]);
  expect(container.textContent).toContain('Customers, Prospects');
});
it('shows missing list references without replacing them and requires valid replacement', async () => {
  value = [{type: 'not_in_list', list_ids: ['missing']}]; render();
  TestUtils.Simulate.click(button(container, 'Edit rule 1')); await tick();
  expect(dialog().textContent).toContain('Selected list not found');
  expect(dialog().textContent).toContain('never had');
  expect(button(dialog(), 'Save rule').disabled).toBe(true);
  expect(value[0].list_ids).toEqual(['missing']);
  TestUtils.Simulate.change(document.getElementById('exit-rule-lists'), {target: {value: 'AbC'}});
  TestUtils.Simulate.click(button(dialog(), 'Save rule')); expect(value[0].list_ids).toEqual(['AbC']);
});
it('rejects saving over concurrently changed rules', async () => {
  TestUtils.Simulate.click(button(container, 'Add exit rule')); choose('has_tag'); await tick(); selectTag();
  value = [{type: 'has_tag', tags: ['other']}]; render();
  TestUtils.Simulate.click(button(dialog(), 'Save rule'));
  expect(dialog().textContent).toContain('changed while this editor was open'); expect(onChange).not.toHaveBeenCalled();
});
it('removes a rule only from the supplied draft and offers all four types', async () => {
  value = [{type: 'missing_tag', tags: ['paid']}]; render();
  TestUtils.Simulate.click(button(container, 'Remove rule 1')); expect(value).toEqual([]);
  TestUtils.Simulate.click(button(container, 'Add exit rule'));
  expect(Array.from(document.getElementById('exit-rule-type').options).map(option => option.text)).toEqual([
    'Choose a rule', 'Has any of these tags', 'Has none of these tags', 'Is in any of these lists', 'Is in none of these lists']);
});
