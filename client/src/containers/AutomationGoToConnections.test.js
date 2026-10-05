import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import AutomationGoToConnections from './AutomationGoToConnections';

let container, component;
const nodes = [{id: 'go', type: 'go_to', target_node_id: 'target'}, {id: 'target', type: 'wait_duration', label: 'Same label'}];
const render = (data = nodes, disabled = false, scale = 1) => {
  component = ReactDOM.render(<AutomationGoToConnections nodes={data} disabled={disabled} scale={scale}>
    <div data-preview-node-id="go"><button>Go to</button></div>
    <div data-preview-node-id="other">Same label</div>
    <div data-preview-node-id="target">Same label</div>
    <div data-preview-node-id="target">Shared occurrence</div>
  </AutomationGoToConnections>, container);
  component.root.getBoundingClientRect = () => ({left: 10, top: 20});
  const anchors = container.querySelectorAll('[data-preview-node-id]');
  Array.from(anchors).forEach((element, index) => {element.getBoundingClientRect = () => ({right: 350 + index * 50, top: 40 + index * 100, width: 340, height: 80});});
};
beforeEach(() => {container = document.createElement('div'); document.body.appendChild(container);});
afterEach(() => {ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);});

it('traces exact IDs on hover and keyboard focus without changing canonical data', () => {
  const before = JSON.stringify(nodes); render();
  const button = container.querySelector('button');
  TestUtils.Simulate.mouseOver(button); component.measure();
  expect(container.querySelector('svg').getAttribute('aria-label')).toBe('Go to destination: Same label');
  expect(container.querySelectorAll('.automation-jump-destination').length).toBe(1);
  expect(container.querySelector('.automation-jump-destination').getAttribute('data-preview-node-id')).toBe('target');
  expect(container.querySelector('svg').lastChild.getAttribute('d')).toBe('M 340 60 H 456 V 260 H 440');
  TestUtils.Simulate.mouseLeave(component.root); component.measure();
  expect(container.querySelector('svg')).not.toBe(null);
  TestUtils.Simulate.mouseOver(container.querySelector('[data-preview-node-id="other"]'));
  window.dispatchEvent(new Event('scroll')); component.measure();
  expect(container.querySelector('svg')).not.toBe(null);
  TestUtils.Simulate.focus(button); component.measure();
  expect(container.querySelector('svg')).not.toBe(null);
  TestUtils.Simulate.blur(button, {relatedTarget: null}); component.measure();
  expect(container.querySelector('svg')).not.toBe(null);
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); component.measure();
  expect(container.querySelector('svg')).toBe(null);
  TestUtils.Simulate.mouseOver(button); component.measure();
  document.body.dispatchEvent(new MouseEvent('click', {bubbles: true})); component.measure();
  expect(container.querySelector('svg')).toBe(null);
  expect(JSON.stringify(nodes)).toBe(before);
});

it('converts screen endpoints into canvas coordinates at different zoom levels', () => {
  render(nodes, false, 0.5);
  TestUtils.Simulate.focus(container.querySelector('button')); component.measure();
  expect(container.querySelector('svg').lastChild.getAttribute('d')).toBe('M 680 120 H 896 V 520 H 880');
  render(nodes, false, 2); component.measure();
  expect(container.querySelector('svg').lastChild.getAttribute('d')).toBe('M 170 30 H 236 V 130 H 220');
});

it('remeasures backwards/cross-branch destinations and clears missing or ambiguous targets', () => {
  render(); const button = container.querySelector('button');
  TestUtils.Simulate.focus(button);
  container.querySelector('[data-preview-node-id="target"]').getBoundingClientRect = () => ({right: 120, top: 0, width: 100, height: 20});
  component.measure();
  expect(container.querySelector('svg').lastChild.getAttribute('d')).toBe('M 340 60 H 356 V -10 H 110');
  render([nodes[0]]); component.measure();
  expect(container.querySelector('svg')).toBe(null);
  render(nodes.concat(nodes[1])); component.measure();
  expect(container.querySelector('svg')).toBe(null);
  render(nodes, true); component.measure();
  expect(container.querySelector('.automation-jump-destination')).toBe(null);
});
