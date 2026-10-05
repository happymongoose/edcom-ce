import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import axios from 'axios';
import ContactsAll from './ContactsAll';
import Contacts from './Contacts';
import notify from '../utils/notify';

jest.mock('axios', () => ({get: jest.fn()}));
jest.mock('../components/MenuNavbar', () => ({children}) => <div>{children}</div>);
jest.mock('../utils/notify', () => ({show: jest.fn()}));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
let container;
beforeEach(() => {container = document.createElement('div'); document.body.appendChild(container);});
afterEach(() => {ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container); jest.clearAllMocks();});
const submit = value => {
  TestUtils.Simulate.change(container.querySelector('input'), {target: {value}});
  TestUtils.Simulate.submit(container.querySelector('form'));
};

it('hides the list overview for results and restores it with Back to lists', async () => {
  axios.get.mockImplementation(url => Promise.resolve({data: url === '/api/contacts' ?
    {contacts: [{email: 'alice@example.com', name: 'Alice'}], total: 1} : []}));
  ReactDOM.render(<Contacts history={{location: {search: ''}}} match={{params: {}}} />, container);
  await tick();
  expect(container.textContent).toContain('No contact lists yet!');
  submit('Alice'); await tick();
  expect(container.textContent).toContain('alice@example.com');
  expect(container.textContent).not.toContain('No contact lists yet!');
  TestUtils.Simulate.click(Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Back to lists'));
  expect(container.textContent).toContain('No contact lists yet!');
  expect(container.textContent).not.toContain('alice@example.com');
  expect(container.querySelector('input').value).toBe('');
});

it('hides lists even for zero matches and restores them on a search error', async () => {
  const visibility = jest.fn();
  axios.get.mockImplementation(() => Promise.resolve({data: {contacts: [], total: 0}}));
  ReactDOM.render(<ContactsAll embedded onResultsVisibilityChange={visibility} />, container);
  submit('missing'); await tick();
  expect(visibility).toHaveBeenLastCalledWith(true);
  axios.get.mockImplementation(() => Promise.reject(new Error('offline')));
  submit('another'); await tick();
  expect(visibility).toHaveBeenLastCalledWith(false);
});

it('searches all lists by email or name on submission and links to the contact editor', async () => {
  axios.get.mockImplementation(() => Promise.resolve({data: {contacts: [{contact_id: 7, email: 'alice+one@example.com', name: 'Alice Smith'}], total: 1, page: 1}}));
  ReactDOM.render(<ContactsAll embedded />, container);
  expect(axios.get).not.toHaveBeenCalled();
  expect(container.querySelector('input').type).toBe('search');
  submit('  Alice Smith  '); await tick();
  expect(axios.get).toHaveBeenCalledWith('/api/contacts', {params: {page: 1, page_size: 50, search: 'Alice Smith', include_unlisted: true}});
  expect(container.textContent).toContain('Alice Smith');
  expect(container.querySelector('tbody a').getAttribute('href')).toBe('/contacts/editcontact?id=alice%2Bone%40example.com');
  submit('alice+one@example.com'); await tick();
  expect(axios.get.mock.calls[1][1].params.search).toBe('alice+one@example.com');
});

it('keeps search criteria through pagination and resets the page for a new search', async () => {
  axios.get.mockImplementation(() => Promise.resolve({data: {contacts: [], total: 60, page: 1, total_pages: 2}}));
  ReactDOM.render(<ContactsAll embedded />, container);
  submit('Smith'); await tick();
  TestUtils.Simulate.click(Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Next'));
  await tick();
  expect(axios.get.mock.calls[1][1].params).toEqual({page: 2, page_size: 50, search: 'Smith', include_unlisted: true});
  submit('Jones'); await tick();
  expect(axios.get.mock.calls[2][1].params.page).toBe(1);
});

it('shows empty results and errors without displaying stale matches', async () => {
  axios.get.mockImplementation(() => Promise.resolve({data: {contacts: [], total: 0}}));
  ReactDOM.render(<ContactsAll embedded />, container);
  submit('missing'); await tick();
  expect(container.textContent).toContain('No contacts match this search.');
  axios.get.mockImplementation(() => Promise.reject(new Error('offline')));
  submit('another'); await tick();
  expect(notify.show).toHaveBeenCalledWith('Unable to load contacts', 'error');
  expect(container.querySelector('tbody')).toBe(null);
});
