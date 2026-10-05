import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import {MemoryRouter} from 'react-router-dom';
import axios from 'axios';
import AutomationEmail from './AutomationEmail';
jest.mock('axios', () => ({get: jest.fn(), post: jest.fn(), patch: jest.fn()}));
jest.mock('../components/TemplateEditor', () => () => null);
jest.mock('../components/TemplateRawEditor', () => () => null);
jest.mock('../components/TemplateWYSIWYGEditor', () => () => null);
jest.mock('../components/TemplateBeefreeEditor', () => () => null);
jest.mock('../components/TestButton', () => () => null);
jest.mock('../utils/notify', () => ({show: jest.fn()}));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
it('loads and starts subject tests with IDs from the real LoadSave email page', async () => {
  const root = document.createElement('div'); document.body.appendChild(root);
  const base = '/api/automations/automation-owned/emails/email-owned';
  axios.get.mockImplementation(url => Promise.resolve({data: url === base ? {
    id: 'email-owned', automation_id: 'automation-owned', name: 'Fixture', subject: 'Baseline', type: 'raw', rawText: '<p>Fixture</p>'
  } : []}));
  axios.patch.mockImplementation(() => Promise.resolve({data: {}}));
  axios.post.mockImplementation(() => Promise.resolve({data: {}}));
  try {
    ReactDOM.render(<MemoryRouter><AutomationEmail history={{location: {search: ''}, push: jest.fn()}} match={{params: {automation_id: 'automation-owned', email_id: 'email-owned'}}} user={{fullname: "Fixture", username: "fixture@example.invalid"}} /></MemoryRouter>, root);
    await tick(); await tick();
    expect(axios.get).toHaveBeenCalledWith(base + '/subject-tests');
    expect(axios.get.mock.calls.some(([url]) => url.indexOf('undefined') >= 0)).toBe(false);
    ['Control', 'Challenger'].forEach((value, i) => TestUtils.Simulate.change(root.querySelector('[aria-label="Test subject ' + (i + 1) + '"]'), {target: {value}}));
    const start = Array.from(root.querySelectorAll('button')).find(b => b.textContent === 'Start experiment');
    TestUtils.Simulate.click(start); await tick();
    const confirm = Array.from(document.querySelectorAll('.modal button')).find(b => b.textContent === 'Confirm');
    TestUtils.Simulate.click(confirm); await tick(); await tick();
    expect(axios.patch.mock.calls[0][0]).toBe(base);
    expect(axios.post.mock.calls[0][0]).toBe(base + '/subject-tests');
  } finally {ReactDOM.unmountComponentAtNode(root); document.body.removeChild(root); jest.resetAllMocks();}
});
