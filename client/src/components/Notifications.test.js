import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import Notifications from './Notifications';
import notify from '../utils/notify';

let root;
const card = () => root.querySelector('.app-toast');
const close = () => root.querySelector('button');
beforeEach(() => {
  jest.useFakeTimers();
  notify.dismiss(notify.current);
  root = document.createElement('div');
  document.body.appendChild(root);
  ReactDOM.render(<Notifications />, root);
});
afterEach(() => {
  ReactDOM.unmountComponentAtNode(root);
  root.remove();
  notify.dismiss(notify.current);
  jest.clearAllTimers();
  jest.useRealTimers();
});

test('existing API displays safe text, severity and a keyboard-accessible close button', () => {
  notify.show('<img src=x onerror=alert(1)>', 'success');
  expect(card().textContent).toContain('Success');
  expect(card().textContent).toContain('<img');
  expect(card().querySelector('img')).toBe(null);
  expect(close().getAttribute('aria-label')).toBe('Dismiss notification');
  expect(card().parentNode.getAttribute('role')).toBe('status');
  TestUtils.Simulate.click(close());
  expect(card()).toBe(null);
});

test('supports React messages and announces errors without stealing focus', () => {
  const input = document.createElement('input'); document.body.appendChild(input); input.focus();
  notify.show(<strong>Unable to save</strong>, 'error');
  expect(card().parentNode.getAttribute('role')).toBe('alert');
  expect(card().querySelector('.app-toast__message strong').textContent).toBe('Unable to save');
  expect(document.activeElement).toBe(input);
  input.remove();
});

test('one card replaces previous messages and an old timer cannot close the replacement', () => {
  notify.show('First', 'success', 1000);
  const first = notify.current;
  jest.runTimersToTime(500);
  notify.show('Second', 'warning', 3000);
  notify.dismiss(first);
  jest.runTimersToTime(500);
  expect(root.querySelectorAll('.app-toast').length).toBe(1);
  expect(card().textContent).toContain('Second');
  jest.runTimersToTime(2500);
  expect(card()).toBe(null);
});

test('defaults to seven seconds and respects explicit duration', () => {
  notify.show('Saved');
  jest.runTimersToTime(6999); expect(card()).not.toBe(null);
  jest.runTimersToTime(1); expect(card()).toBe(null);
  notify.show('Long message', 'info', 15000);
  jest.runTimersToTime(14999); expect(card()).not.toBe(null);
  jest.runTimersToTime(1); expect(card()).toBe(null);
});

test('hover and keyboard focus each prevent dismissal; leaving restarts the reading time', () => {
  notify.show('Read this', 'warning', 1000);
  TestUtils.Simulate.mouseEnter(card());
  TestUtils.Simulate.focus(close());
  jest.runTimersToTime(2000); expect(card()).not.toBe(null);
  TestUtils.Simulate.mouseLeave(card());
  jest.runTimersToTime(2000); expect(card()).not.toBe(null);
  TestUtils.Simulate.blur(close(), {relatedTarget: null});
  jest.runTimersToTime(999); expect(card()).not.toBe(null);
  jest.runTimersToTime(1); expect(card()).toBe(null);
});

test('Escape on close dismisses the toast without escaping an underlying dialog', () => {
  notify.show('Saved', 'success');
  const stopPropagation = jest.fn();
  TestUtils.Simulate.keyDown(close(), {key: 'Escape', stopPropagation});
  expect(stopPropagation).toHaveBeenCalled();
  expect(card()).toBe(null);
});

test('unmount removes subscription and timer; messages before mount are retained', () => {
  notify.show('Old', 'success', 1000);
  ReactDOM.unmountComponentAtNode(root);
  expect(notify.listeners.length).toBe(0);
  notify.show('Before mount', 'error');
  jest.runTimersToTime(1000);
  ReactDOM.render(<Notifications />, root);
  expect(card().textContent).toContain('Before mount');
});

test('replacing a focused card in a different live region does not leave its timer paused', () => {
  notify.show('Success', 'success', 1000);
  TestUtils.Simulate.focus(close());
  notify.show('Error', 'error', 1000);
  jest.runTimersToTime(1000);
  expect(card()).toBe(null);
});
