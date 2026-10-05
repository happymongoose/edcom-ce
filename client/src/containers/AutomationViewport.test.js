import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import AutomationViewport from './AutomationViewport';

let root, view;
const click = text => TestUtils.Simulate.click(Array.from(root.querySelectorAll('button')).find(b => b.textContent === text));
beforeEach(() => {
  root = document.createElement('div'); document.body.appendChild(root);
  view = ReactDOM.render(<AutomationViewport width={1000}>{scale => <div>
    <button>Node</button><div data-preview-node-id="step" draggable="true">Step</div><span>{scale}</span>
  </div>}</AutomationViewport>, root);
  Object.defineProperty(view.viewport, 'clientWidth', {value: 500});
  Object.defineProperty(view.viewport, 'clientHeight', {value: 400});
  Object.defineProperty(view.canvas, 'offsetHeight', {value: 1000});
  view.measure();
});
afterEach(() => {ReactDOM.unmountComponentAtNode(root); root.remove();});
it('selects zoom percentages and fits the full measured graph without changing graph children', () => {
  const select = root.querySelector('[aria-label="Zoom level"]');
  TestUtils.Simulate.change(select, {target: {value: '0.9'}}); expect(view.state.scale).toBe(0.9);
  TestUtils.Simulate.change(select, {target: {value: '1'}}); expect(view.state.scale).toBe(1);
  click('Fit to view'); expect(view.state.scale).toBeCloseTo(0.376);
  expect(Number(select.value)).toBeCloseTo(0.376);
  expect(root.firstChild.lastChild.className).toBe('automation-view-controls');
  expect(root.querySelector('.automation-view-controls').querySelectorAll('button').length).toBe(1);
  expect(root.textContent).not.toContain('Drag empty space');
  expect(view.viewport.scrollTop).toBe(0);
  expect(root.querySelector('[data-preview-node-id="step"]')).not.toBe(null);
  view.zoom(99); expect(view.state.scale).toBe(2);
  view.zoom(0); expect(view.state.scale).toBe(0.01);
});
it('pans blank canvas and ends the gesture on mouseup', () => {
  view.viewport.scrollLeft = 200; view.viewport.scrollTop = 300;
  TestUtils.Simulate.mouseDown(view.viewport, {button: 0, clientX: 100, clientY: 100});
  document.dispatchEvent(new MouseEvent('mousemove', {clientX: 50, clientY: 60}));
  expect(view.viewport.scrollLeft).toBe(250); expect(view.viewport.scrollTop).toBe(340);
  document.dispatchEvent(new MouseEvent('mouseup'));
  expect(view.state.panning).toBe(false);
});
it('leaves buttons, node drags and selection controls to their existing handlers', () => {
  [root.querySelector('.automation-preview-canvas button'), root.querySelector('[draggable]')].forEach(target => {
    TestUtils.Simulate.mouseDown(target, {button: 0, clientX: 100, clientY: 100});
    expect(view.state.panning).toBe(false);
  });
});
it('jumps using current exact IDs and screen coordinates at every zoom without editing children', () => {
  let items = [{id: 'step'}];
  view = ReactDOM.render(<AutomationViewport width={1000} getNavigationItems={() => items}>{() => <div data-preview-node-id="step">Step</div>}</AutomationViewport>, root);
  const target = root.querySelector('[data-preview-node-id]');
  view.viewport.getBoundingClientRect = () => ({left: 10, top: 20, bottom: 420});
  [0.5, 1, 2].forEach(scale => {
    view.zoom(scale); view.viewport.scrollLeft = 100; view.viewport.scrollTop = 100;
    target.getBoundingClientRect = () => ({left: 10 + 800 * scale, top: 20 + 600 * scale, width: 100 * scale, height: 40 * scale});
    expect(view.jumpTo('step')).toBe('');
    expect(view.viewport.scrollLeft).toBe(100 + 850 * scale - 250);
    expect(view.viewport.scrollTop).toBe(100 + 620 * scale - 200);
    expect(document.activeElement).toBe(target); expect(view.state.scale).toBe(scale);
  });
  expect(target.classList.contains('automation-found-step')).toBe(true);
  items = [{id: 'step', ambiguous: true}]; expect(view.jumpTo('step')).toContain('ambiguous');
  items = []; expect(view.jumpTo('step')).toContain('missing');
  view.clearHighlight(); expect(target.hasAttribute('tabindex')).toBe(false);
});
