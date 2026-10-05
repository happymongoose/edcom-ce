import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import AutomationStepFinder from './AutomationStepFinder';

let root, items, getItems, jump;
const change = (label, value) => TestUtils.Simulate.change(root.querySelector('[aria-label="' + label + '"]'), {target: {value}});
const results = () => root.querySelectorAll('[data-find-node-id]');
const open = () => TestUtils.Simulate.click(root.querySelector('button'));
beforeEach(() => {
  root = document.createElement('div'); document.body.appendChild(root);
  items = [
    {id: 'a', label: 'Wait', type: 'Wait', step: 1, count: 2},
    {id: 'b', label: 'Wait', type: 'Wait', step: 2, count: 0, warning: 'Invalid duration'},
    {id: 'c', label: 'Exit', type: 'Exit', step: 3, count: null, detached: true},
  ];
  getItems = jest.fn(() => items); jump = jest.fn(() => '');
  ReactDOM.render(<AutomationStepFinder getItems={getItems} onJump={jump} />, root);
});
afterEach(() => {ReactDOM.unmountComponentAtNode(root); root.remove();});
it('builds results lazily, distinguishes repeated labels and searches exact IDs', () => {
  expect(getItems).not.toHaveBeenCalled(); open();
  expect(document.activeElement).toBe(root.querySelector('input'));
  expect(root.textContent).toContain('Draft step 1'); expect(root.textContent).toContain('Draft step 2');
  change('Search draft steps', 'c'); expect(results().length).toBe(1);
  TestUtils.Simulate.click(results()[0]); expect(jump).toHaveBeenCalledWith('c');
  expect(root.querySelector('section')).toBe(null);
});
it('filters contacts, validation warnings and unexpanded steps without inventing counts', () => {
  open(); expect(root.textContent).toContain('Live count unavailable');
  change('Filter draft steps', 'contacts'); expect(results()[0].getAttribute('data-find-node-id')).toBe('a'); expect(results().length).toBe(1);
  change('Filter draft steps', 'warnings'); expect(results()[0].textContent).toContain('Invalid duration');
  expect(root.textContent).toContain('Frontend checks only');
  change('Filter draft steps', 'other'); expect(results()[0].getAttribute('data-find-node-id')).toBe('c');
});
it('restores focus on Escape and displays safe navigation failures', () => {
  open(); jump.mockImplementation(() => 'Step no longer exists');
  TestUtils.Simulate.click(results()[0]); expect(root.querySelector('[role="alert"]').textContent).toBe('Step no longer exists');
  TestUtils.Simulate.keyDown(root.querySelector('input'), {key: 'Escape'});
  expect(root.querySelector('section')).toBe(null); expect(document.activeElement).toBe(root.querySelector('button'));
});
it('bounds large result lists and disables ambiguous IDs', () => {
  items = Array.from({length: 1000}, (_, index) => ({id: 'id-' + index, label: 'Wait', step: index + 1, ambiguous: index === 0}));
  open(); expect(results().length).toBe(50); expect(results()[0].disabled).toBe(true);
  expect(root.textContent).toContain('1000 matching draft steps');
  change('Search draft steps', 'id-999'); expect(results().length).toBe(1);
});
