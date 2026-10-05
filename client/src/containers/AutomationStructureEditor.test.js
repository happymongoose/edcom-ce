import React from 'react';
import ReactDOM from 'react-dom';
import TestUtils from 'react-dom/test-utils';
import $ from 'jquery';
import AutomationWorkflowEditor from './AutomationWorkflowEditor';
import withLoadSave from '../components/LoadSave';

require('select2')(window, $);
jest.mock('axios', () => ({get: jest.fn()}));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const wait = id => ({id, label: id, type: 'wait_duration', duration: {days: 1, hours: 0, minutes: 0}});
const exit = id => ({id, label: id, type: 'exit'});
const definition = () => ({draft: {nodes: [wait('a'), wait('b'), exit('end')]}});
const button = (root, text) => Array.from(root.querySelectorAll('button')).find(node => node.textContent.trim() === text);
const dialog = () => document.querySelector('.modal[role="dialog"]');
const click = node => TestUtils.Simulate.click(node);
const change = (id, value) => id === 'visual-step-type' ? click(dialog().querySelector('[data-node-type="' + value + '"]')) :
  TestUtils.Simulate.change(dialog().querySelector('#' + id), {target: {id, value}});
let container, owner, editor, beforeUpdate, stored, patch;
beforeEach(() => {
  container = document.createElement('div'); document.body.appendChild(container);
  beforeUpdate = null;
});
afterEach(() => {ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);});
async function mount(data = definition(), publishedNodes = data.draft.nodes, counts) {
  stored = JSON.parse(JSON.stringify(data));
  patch = jest.fn(async ({data}) => {stored = JSON.parse(JSON.stringify(data)); return stored;});
  const Page = props => <AutomationWorkflowEditor ref={value => {editor = value;}}
    nodes={props.data.draft.nodes} publishedNodes={publishedNodes}
    publishedRevision={1} moveDecisions={props.data.draft.moves || {}}
    nodeContactCount={counts ? node => counts[node.id] : undefined}
    update={(spec, cb) => {if (beforeUpdate) beforeUpdate(); props.update(spec, cb);}}
    renderNodeContactCount={() => '0 live contacts'} />;
  const Loaded = withLoadSave({extend: Page, initial: data, get: async () => stored, patch});
  owner = ReactDOM.render(<Loaded history={{location: {search: ''}}} match={{params: {id: 'test'}}} />, container);
  await tick(); click(button(container, 'Visual preview'));
}
function addAfterFirst() {
  const trigger = container.querySelector('[aria-label="Add after step 1"]');
  trigger.focus(); click(trigger); change('visual-step-type', 'wait_duration');
  return trigger;
}

const findFilter = value => TestUtils.Simulate.change(container.querySelector('[aria-label="Filter draft steps"]'), {target: {value}});
const findSearch = value => TestUtils.Simulate.change(container.querySelector('[aria-label="Search draft steps"]'), {target: {value}});

it('locates occupied steps using exact live IDs and refreshes counts without changing the draft', async () => {
  const counts = {a: 3, b: 0, end: null};
  await mount(definition(), definition().draft.nodes, counts);
  const before = owner.state.data;
  click(button(container, 'Find step')); findFilter('contacts');
  expect(container.querySelectorAll('[data-find-node-id]').length).toBe(1);
  expect(container.querySelector('[data-find-node-id="a"]').textContent).toContain('3 live contacts');
  click(container.querySelector('[data-find-node-id="a"]'));
  expect(document.activeElement.getAttribute('data-preview-node-id')).toBe('a');
  counts.a = 0; counts.b = 2;
  editor.forceUpdate(); click(button(container, 'Find step'));
  expect(container.querySelectorAll('[data-find-node-id]').length).toBe(1);
  expect(container.querySelector('[data-find-node-id="b"]').textContent).toContain('2 live contacts');
  findFilter('all');
  expect(container.querySelector('[data-find-node-id="end"]').textContent).toContain('Live count unavailable');
  expect(owner.state.data).toBe(before); expect(patch).not.toHaveBeenCalled();
});

it('uses actual editor validation to locate invalid waits and stale list or Go to references', async () => {
  const nodes = [wait('valid'), {...wait('short'), duration: {days: 0, hours: 0, minutes: 1}},
    {id: 'list', label: 'Missing list', type: 'add_to_list', list_id: 'deleted'},
    {id: 'jump', label: 'Broken jump', type: 'go_to', target_node_id: 'deleted'}, exit('end')];
  await mount({draft: {nodes}}); const before = owner.state.data;
  click(button(container, 'Find step')); findFilter('warnings');
  expect(Array.from(container.querySelectorAll('[data-find-node-id]')).map(el => el.getAttribute('data-find-node-id'))).toEqual(['short', 'list', 'jump']);
  expect(container.querySelector('[data-find-node-id="list"]').textContent).toContain('not available');
  click(container.querySelector('[data-find-node-id="short"]'));
  expect(document.activeElement.getAttribute('data-preview-node-id')).toBe('short');
  expect(dialog()).toBe(null); expect(owner.state.data).toBe(before); expect(patch).not.toHaveBeenCalled();
});

['balanced', 'deep'].forEach(shape => it('keeps every stable ID discoverable in a large ' + shape + ' condition graph', async () => {
  const nodes = [];
  const build = (depth, id) => {
    if (!depth) {nodes.push(exit(id)); return id;}
    const node = {id, label: 'Repeated condition', type: 'if_has_tag', draft_tag: 'test', yes_node_id: id + 'y', no_node_id: id + 'n'};
    nodes.push(node); build(depth - 1, node.yes_node_id); build(shape === 'balanced' ? depth - 1 : 0, node.no_node_id);
    return id;
  };
  build(shape === 'balanced' ? 8 : 45, 'root');
  await mount({draft: {nodes}}); const before = owner.state.data;
  const rendered = Array.from(container.querySelectorAll('[data-preview-node-id]')).map(el => el.getAttribute('data-preview-node-id'));
  expect(rendered.length).toBe(nodes.length); expect(new Set(rendered).size).toBe(nodes.length);
  click(button(container, 'Find step'));
  expect(container.querySelectorAll('[data-find-node-id]').length).toBe(50);
  expect(container.querySelector('[role="status"]').textContent).toContain(nodes.length + ' matching draft steps');
  const leaf = nodes.find(node => node.type === 'exit').id;
  if (shape === 'deep') {
    findFilter('other');
    expect(container.querySelectorAll('[data-find-node-id]').length).toBeGreaterThan(0);
  }
  findSearch(leaf);
  click(container.querySelector('[data-find-node-id="' + leaf + '"]'));
  expect(document.activeElement.getAttribute('data-preview-node-id')).toBe(leaf);
  expect(owner.state.data).toBe(before); expect(patch).not.toHaveBeenCalled();
}));

it('finds unexpanded Go to destinations by stable ID without editing the canonical draft', async () => {
  await mount({draft: {nodes: [{id: 'go', type: 'go_to', label: 'Jump', target_node_id: 'b'}, wait('b'), exit('end')]}});
  const before = owner.state.data;
  click(container.querySelector('[aria-label="Show destination of step 1"]'));
  expect(document.activeElement.getAttribute('data-preview-node-id')).toBe('b');
  expect(dialog()).toBe(null);
  click(button(container, 'Find step'));
  TestUtils.Simulate.change(container.querySelector('[aria-label="Filter draft steps"]'), {target: {value: 'other'}});
  const result = container.querySelector('[data-find-node-id="end"]');
  expect(result).not.toBe(null); click(result);
  expect(document.activeElement.getAttribute('data-preview-node-id')).toBe('end');
  expect(owner.state.data).toBe(before);
});

it('finds steps beyond the traversal limit and refreshes positions after canonical reordering', async () => {
  const nodes = Array.from({length: 120}, (_, index) => wait('wait-' + index)).concat(exit('end'));
  await mount({draft: {nodes}});
  const before = owner.state.data;
  click(button(container, 'Find step'));
  expect(container.querySelectorAll('[data-find-node-id]').length).toBe(50);
  TestUtils.Simulate.change(container.querySelector('[aria-label="Search draft steps"]'), {target: {value: 'wait-119'}});
  click(container.querySelector('[data-find-node-id="wait-119"]'));
  expect(document.activeElement.getAttribute('data-preview-node-id')).toBe('wait-119');
  expect(owner.state.data).toBe(before);
  editor.props.update({draft: {nodes: {$set: [nodes[119]].concat(nodes.filter(node => node.id !== 'wait-119'))}}});
  click(button(container, 'Find step'));
  expect(container.querySelector('[data-find-node-id="wait-119"]').textContent).toContain('Draft step 1');
});

it('keeps zoom local while insertion and move selection remain available', async () => {
  await mount(); const before = owner.state.data;
  TestUtils.Simulate.change(container.querySelector('[aria-label="Zoom level"]'), {target: {value: '0.9'}});
  expect(container.querySelector('[aria-label="Zoom level"]').value).toBe('0.9');
  expect(owner.state.data).toBe(before);
  addAfterFirst(); click(button(dialog(), 'Cancel'));
  click(container.querySelector('[aria-label="Move step 1"]'));
  expect(container.querySelector('[aria-label="Move here: Add after step 2"]')).not.toBe(null);
  expect(owner.state.data).toBe(before);
});

it('confirms a draft-only deletion without a contact or replacement decision', async () => {
  await mount({draft: {nodes: [{id:'if', type:'if_has_tag', label:'If', draft_tag:'vip', yes_node_id:'a', no_node_id:'end'}, wait('a'), wait('b'), exit('end')]}}, []);
  click(container.querySelector('[aria-label="Delete step 2"]'));
  expect(dialog().textContent).toContain('new to the draft and has no live contacts');
  expect(dialog().querySelector('#delete-replacement')).toBe(null);
  expect(button(dialog(), 'Delete step').disabled).toBe(false);
  click(button(dialog(), 'Delete step'));
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['if','b','end']);
  expect(owner.state.data.draft.nodes[0].yes_node_id).toBe('b');
});

it('moves by explicit drop choice, preserves stable configuration and persists the publication decision', async () => {
  await mount(); const before = owner.state.data;
  click(container.querySelector('[aria-label="Move step 1"]'));
  click(container.querySelector('[aria-label="Move here: Add after step 2"]'));
  expect(owner.state.data).toBe(before);
  expect(button(dialog(), 'Save step').disabled).toBe(true);
  change('move-contact-action', 'follow');
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['b', 'a', 'end']);
  expect(owner.state.data.draft.nodes[1]).toEqual(before.draft.nodes[0]);
  expect(owner.state.data.draft.moves.a.action).toBe('follow');
  await owner.saveData(); await owner.reloadData();
  expect(owner.state.data.draft.moves.a.published_revision).toBe(1);
});

it('cancels a proposed move without changing canonical order or decisions', async () => {
  await mount(); const before = owner.state.data;
  click(container.querySelector('[aria-label="Move step 1"]'));
  click(container.querySelector('[aria-label="Move here: Add after step 2"]'));
  change('move-contact-action', 'exit'); click(button(dialog(), 'Cancel'));
  expect(owner.state.data).toBe(before);
});

it('opens visual Go to selection without a dialog or pencil', async () => {
  await mount({draft: {nodes: [{id: 'go', type: 'go_to', label: 'Go to', target_node_id: 'end'}, exit('end')]}});
  click(container.querySelector('.automation-condition-preview-node'));
  expect(dialog()).toBe(null);
  expect(container.textContent).toContain('Select which node to go to');
  expect(container.querySelector('[aria-label="Edit step 1"]')).toBe(null);
  click(button(container, 'Cancel'));
});

const goToDraft = () => ({draft: {nodes: [wait('before'),
  {id: 'go', type: 'go_to', label: 'Jump', target_node_id: 'b'}, wait('b'), exit('end')]}});
const targetChoice = id => container.querySelector('[data-target-node-id="' + id + '"]');

it('describes a replaced implicit ending without counting it as a deleted action', async () => {
  await mount({draft: {nodes: [wait('a'), exit('end')]}}, []);
  click(container.querySelector('[aria-label="Add after step 1"]'));
  change('visual-step-type', 'go_to');
  TestUtils.Simulate.change(targetChoice('a'));
  const prompt = container.querySelector('.automation-go-to-prompt');
  expect(prompt.textContent).toContain('replaces the “Automation ends” ending');
  expect(prompt.textContent).not.toContain('remove 1 step');
  expect(prompt.querySelector('ul')).toBe(null);
  click(button(container, 'Cancel'));
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['a', 'end']);
});

it('adds Go to through immediate visual selection and commits insertion and removal together', async () => {
  await mount(); const before = owner.state.data;
  click(container.querySelector('[aria-label="Add after step 1"]'));
  change('visual-step-type', 'go_to');
  expect(dialog()).toBe(null);
  expect(owner.state.data).toBe(before);
  expect(button(container, 'Confirm').disabled).toBe(true);
  TestUtils.Simulate.change(targetChoice('end'));
  expect(container.textContent).toContain('remove 1 step');
  expect(owner.state.data).toBe(before);
  click(button(container, 'Confirm'));
  expect(owner.state.data.draft.nodes.map(node => node.type)).toEqual(['wait_duration', 'go_to', 'exit']);
  expect(owner.state.data.draft.nodes[1].target_node_id).toBe('end');
  expect(container.querySelector('[data-node-id="b"].automation-pending-removal')).not.toBe(null);
});

it('cancels a provisional Go to without adding or deleting canonical nodes', async () => {
  await mount(); const before = owner.state.data;
  click(container.querySelector('[aria-label="Add after step 1"]')); change('visual-step-type', 'go_to');
  TestUtils.Simulate.change(targetChoice('end'));
  click(button(container, 'Cancel'));
  expect(owner.state.data).toBe(before);
});

it('visually selects earlier actions as well as Wait nodes with runtime loop protection', async () => {
  await mount(goToDraft()); click(container.querySelector('.automation-condition-preview-node'));
  TestUtils.Simulate.change(targetChoice('before'));
  expect(button(container, 'Confirm').disabled).toBe(false);
  click(button(container, 'Confirm'));
  expect(owner.state.data.draft.nodes.find(node => node.id === 'go').target_node_id).toBe('before');
  editor.props.update({draft: {nodes: {0: {$set: {id: 'before', type: 'add_tag', label: 'Action', draft_tag: 'vip'}}}}});
  click(container.querySelector('.automation-condition-preview-node'));
  expect(button(container, 'Confirm').disabled).toBe(false);
  expect(container.textContent).toContain('held before the action repeats');
  click(button(container, 'Confirm'));
  expect(owner.state.data.draft.nodes.find(node => node.id === 'go').target_node_id).toBe('before');
});

it('selects one destination and confirms exclusive path removal, then persists and shares it with Edit list', async () => {
  await mount(goToDraft()); const before = owner.state.data;
  const trigger = container.querySelector('.automation-condition-preview-node');
  trigger.focus(); click(trigger);
  expect(targetChoice('go')).toBe(null);
  expect(targetChoice('before').disabled).toBe(false);
  expect(targetChoice('b').checked).toBe(true);
  TestUtils.Simulate.change(targetChoice('end'));
  expect(targetChoice('b').checked).toBe(false);
  expect(targetChoice('end').checked).toBe(true);
  expect(owner.state.data).toBe(before);
  expect(container.textContent).toContain('remove 1 step');
  expect(container.querySelector('.automation-visual-card-tools')).toBe(null);
  click(button(container, 'Confirm'));
  expect(owner.state.data.draft.nodes).toEqual(before.draft.nodes.filter(node => node.id !== 'b').map(node => node.id === 'go' ? {...node, target_node_id: 'end'} : node));
  expect(document.activeElement).toBe(trigger);
  await owner.saveData(); await owner.reloadData();
  click(button(container, 'Edit list')); editor.setState({expandedNodeIds: {go: true}});
  expect(container.querySelector('#target_node_id').value).toBe('end');
});

['cancel', 'escape'].forEach(method => {
  it('discards temporary Go to selection on ' + method, async () => {
    await mount(goToDraft()); const before = owner.state.data;
    click(container.querySelector('.automation-condition-preview-node'));
    TestUtils.Simulate.change(targetChoice('end'));
    if (method === 'cancel') click(button(container, 'Cancel'));
    else {const event = new window.Event('keydown', {bubbles: true}); event.keyCode = 27; document.dispatchEvent(event);}
    expect(owner.state.data).toBe(before);
    expect(container.querySelector('.automation-go-to-prompt')).toBe(null);
  });
});

it('requires a valid replacement for a missing Go to target without silently selecting one', async () => {
  const data = goToDraft(); data.draft.nodes[1].target_node_id = 'missing';
  await mount(data); click(container.querySelector('.automation-condition-preview-node'));
  expect(container.querySelectorAll('.automation-go-to-choice input:checked').length).toBe(0);
  expect(button(container, 'Confirm').disabled).toBe(true);
  TestUtils.Simulate.change(targetChoice('end'));
  expect(button(container, 'Confirm').disabled).toBe(false);
});

it('refuses a Go to commit after a concurrent workflow change', async () => {
  await mount(goToDraft()); click(container.querySelector('.automation-condition-preview-node'));
  TestUtils.Simulate.change(targetChoice('end'));
  editor.props.update({draft: {nodes: {$apply: nodes => nodes.filter(node => node.id !== 'end')}}});
  editor.confirmGoToSelection();
  expect(owner.state.data.draft.nodes.find(node => node.id === 'go').target_node_id).toBe('b');
  expect(container.textContent).toContain('workflow changed');
});

it('hides condition targets in visual configuration but retains them in Edit list', async () => {
  await mount({draft: {nodes: [{id: 'if', label: 'Check', type: 'if_conditions', condition: {mode: 'all', items: [{type: 'has_tag', tag: 'vip'}]}, yes_node_id: 'a', no_node_id: 'end'}, wait('a'), exit('end')]}});
  click(container.querySelector('.automation-condition-preview-node'));
  expect(dialog().querySelector('#yes_node_id')).toBe(null);
  expect(dialog().querySelector('#no_node_id')).toBe(null);
  click(button(dialog(), 'Cancel')); click(button(container, 'Edit list'));
  editor.setState({expandedNodeIds: {if: true}});
  expect(container.querySelector('#yes_node_id')).not.toBe(null);
  expect(container.querySelector('#no_node_id')).not.toBe(null);
});

it('defaults to the visual editor without visible step numbers', async () => {
  await mount();
  expect(editor.state.workflowView).toBe('preview');
  expect(container.querySelector('.automation-visual-card').textContent).not.toMatch(/Step 1|STEP 1/);
});

it('asks again on a subsequent move and overwrites the earlier contact decision', async () => {
  await mount();
  click(container.querySelector('[aria-label="Move step 1"]'));
  click(container.querySelector('[aria-label="Move here: Add after step 2"]'));
  change('move-contact-action', 'follow'); click(button(dialog(), 'Save step'));
  click(container.querySelector('[aria-label="Move step 2"]'));
  click(container.querySelector('[aria-label="Move here: Add before first step"]'));
  expect(dialog().querySelector('#move-contact-action').value).toBe('');
  change('move-contact-action', 'exit'); click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.moves.a.action).toBe('exit');
  expect(owner.state.data.draft.moves.a.placement.previous).toBe(null);
});

it('supports native drag/drop and rejects a concurrent canonical change', async () => {
  await mount(); const before = owner.state.data;
  const dataTransfer = {setData: jest.fn()};
  TestUtils.Simulate.dragStart(container.querySelector('.automation-visual-card'), {dataTransfer});
  expect(dataTransfer.setData).toHaveBeenCalledWith('text/plain', 'a');
  TestUtils.Simulate.drop(container.querySelector('[aria-label="Move here: Add after step 2"]'));
  change('move-contact-action', 'follow');
  editor.props.update({draft: {nodes: {0: {label: {$set: 'Concurrent change'}}}}});
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(before.draft.nodes.map(node => node.id));
  expect(dialog().textContent).toContain('workflow changed');
});

['yes', 'no', 'both'].forEach(choice => {
  it('requires an explicit condition deletion choice: ' + choice, async () => {
    await mount({draft: {nodes: [{id: 'if', label: 'If', type: 'if_has_tag', draft_tag: 'vip', yes_node_id: 'a', no_node_id: 'b'}, wait('a'), exit('ae'), wait('b'), exit('be')]}});
    const before = owner.state.data;
    click(container.querySelector('[aria-label="Delete step 1"]'));
    expect(button(dialog(), 'Delete step').disabled).toBe(true);
    change('condition-delete-choice', choice);
    expect(owner.state.data).toBe(before);
    click(button(dialog(), 'Delete step'));
    expect(owner.state.data.draft.nodes.some(node => node.id === 'a')).toBe(choice === 'yes');
    expect(owner.state.data.draft.nodes.some(node => node.id === 'b')).toBe(choice === 'no');
  });
});

it('adds through shared controls with temporary state, then shares and persists canonical nodes in both views', async () => {
  await mount(); const before = owner.state.data;
  addAfterFirst();
  const id = editor.state.structureEdit.id;
  change('wait-' + id + '-days', '3');
  expect(owner.state.data).toBe(before);
  click(button(dialog(), 'Save step'));
  editor.saveStructureEditor();
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['a', id, 'b', 'end']);
  expect(owner.state.data.draft.nodes[1].duration.days).toBe(3);
  expect(container.textContent).toContain('3 days');
  click(button(container, 'Edit list'));
  editor.setState({expandedNodeIds: {[id]: true}});
  expect(container.querySelector('#wait-' + id + '-days').value).toBe('3');
  expect(patch.mock.calls.length).toBe(0);
  await owner.saveData(); await owner.reloadData();
  expect(patch.mock.calls.length).toBe(1);
  expect(stored.draft.nodes[1].id).toBe(id);
  expect(Object.keys(stored)).toEqual(['draft']);
  expect(owner.state.data.draft.nodes[1].duration.days).toBe(3);
});

['cancel', 'close', 'escape'].forEach(method => {
  it('discards an insertion on ' + method + ' and returns focus', async () => {
    await mount(); const before = owner.state.data;
    const trigger = addAfterFirst();
    if (method === 'cancel') click(button(dialog(), 'Cancel'));
    if (method === 'close') click(dialog().querySelector('.close'));
    if (method === 'escape') {
      const event = new window.Event('keydown', {bubbles: true}); event.keyCode = 27; document.dispatchEvent(event);
    }
    expect(owner.state.data).toBe(before);
    expect(editor.state.structureEdit).toBe(null);
    await new Promise(resolve => setTimeout(resolve, 350));
    expect(document.activeElement).toBe(trigger);
  });
});

it('rejects invalid wait values without silently truncating fractions', async () => {
  await mount(); const before = owner.state.data; addAfterFirst();
  change('wait-' + editor.state.structureEdit.id + '-days', '1.5');
  expect(button(dialog(), 'Save step').disabled).toBe(true);
  editor.saveStructureEditor();
  expect(owner.state.data).toBe(before);
  expect(dialog().textContent).toContain('whole numbers');
});

it('adds a nested condition on Yes with separate explicit boundaries and leaves No untouched', async () => {
  const nodes = [{id: 'outer', type: 'if_has_tag', label: 'Outer', draft_tag: 'vip', yes_node_id: 'yes-end', no_node_id: 'no-end'}, exit('yes-end'), exit('no-end')];
  await mount({draft: {nodes}});
  click(container.querySelector('[aria-label="Add on Yes path of step 1"]'));
  change('visual-step-type', 'if_conditions');
  const local = editor.state.structureEdit;
  const tag = $('#condition-tags-' + local.nodes.findIndex(node => node.id === local.id) + '-0');
  tag.select2('open');
  expect(tag.data('select2').options.get('dropdownParent').closest('[role="dialog"]')[0]).toBe(dialog());
  const search = $(dialog()).find('.select2-search__field');
  search.val('paid').trigger('input');
  search.trigger($.Event('keydown', {which: 13, keyCode: 13}));
  expect(dialog().querySelector('[aria-label="Remove tag paid"]')).not.toBe(null);
  click(button(dialog(), 'Save step'));
  const updated = owner.state.data.draft.nodes;
  const nested = updated.find(node => node.id === updated[0].yes_node_id);
  expect(updated[0].no_node_id).toBe('no-end');
  expect(nested.type).toBe('if_conditions');
  expect(nested.yes_node_id).not.toBe(nested.no_node_id);
  expect(container.querySelectorAll('button[aria-label^="Add on Yes path"]').length).toBe(2);
  expect(container.querySelectorAll('button[aria-label^="Add on No path"]').length).toBe(2);
});

it('requires explicit incoming-target repair for deletion and keeps descendants and published data', async () => {
  const nodes = [{id: 'if', type: 'if_has_tag', label: 'If', draft_tag: 'vip', yes_node_id: 'a', no_node_id: 'end'}, wait('a'), wait('b'), exit('end')];
  await mount({draft: {nodes}});
  click(container.querySelector('[aria-label="Delete step 2"]'));
  expect(button(dialog(), 'Delete step').disabled).toBe(true);
  expect(dialog().textContent).toContain('downstream steps remain');
  change('delete-replacement', 'b');
  click(button(dialog(), 'Delete step'));
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['if', 'b', 'end']);
  expect(owner.state.data.draft.nodes[0].yes_node_id).toBe('b');
  expect(nodes[0].yes_node_id).toBe('a');
  expect(container.querySelector('.automation-pending-removal').getAttribute('data-node-id')).toBe('a');
});

it('cancels deletion without changing references, nodes or published occupancy', async () => {
  await mount(); const before = owner.state.data;
  click(container.querySelector('[aria-label="Delete step 2"]'));
  click(button(dialog(), 'Cancel'));
  expect(owner.state.data).toBe(before);
  expect(container.querySelector('.automation-pending-removal')).toBe(null);
});

it('edits compound conditions through the existing shared controls without changing node identity', async () => {
  const condition = {id: 'if', label: 'Combined', type: 'if_conditions', condition: {mode: 'all', items: [
    {type: 'has_tag', tag: 'vip'}, {type: 'missing_tag', tag: 'blocked'},
  ]}, yes_node_id: 'yes', no_node_id: 'no'};
  await mount({draft: {nodes: [condition, exit('yes'), exit('no')]}});
  expect(button(container, 'Configure If conditions')).toBe(undefined);
  const trigger = container.querySelector('button.automation-condition-preview-node');
  expect(trigger.querySelector('button')).toBe(null);
  trigger.focus(); click(trigger);
  const before = owner.state.data;
  change('mode', 'any');
  expect(owner.state.data).toBe(before);
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes[0]).toEqual({...condition, condition: {...condition.condition, mode: 'any'}});
  expect(owner.state.data.draft.nodes.slice(1)).toEqual(before.draft.nodes.slice(1));
});

it('allows an explicit condition target to an earlier action', async () => {
  const condition = {id: 'if', label: 'If', type: 'if_has_tag', draft_tag: 'vip', yes_node_id: 'yes', no_node_id: 'no'};
  await mount({draft: {nodes: [{id: 'entry', label: 'Action', type: 'add_tag', draft_tag: 'vip'}, condition, exit('yes'), exit('no')]}});
  click(button(container, 'Edit list'));
  editor.openStructureEditor('edit', 'if');
  const before = owner.state.data;
  change('yes_node_id', 'entry');
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes[1].yes_node_id).toBe('entry');
  expect(owner.state.data.draft.nodes[0]).toEqual(before.draft.nodes[0]);
  expect(dialog()).toBe(null);
});

['reorder', 'remove', 'change', 'duplicate', 'during-update'].forEach(reason => {
  it('rejects stale structural editing after ' + reason, async () => {
    await mount(); addAfterFirst();
    const nodes = owner.state.data.draft.nodes;
    const changed = reason === 'reorder' ? [nodes[1], nodes[0], nodes[2]] : reason === 'remove' ? nodes.slice(1) :
      reason === 'duplicate' ? nodes.concat(nodes[0]) : [{...nodes[0], label: 'Changed'}, ...nodes.slice(1)];
    if (reason === 'during-update') beforeUpdate = () => {owner.state.data = {draft: {nodes: changed}};};
    else owner.updateData({draft: {nodes: {$set: changed}}});
    editor.saveStructureEditor();
    expect(owner.state.data.draft.nodes).toEqual(changed);
    expect(editor.state.structureEdit).not.toBe(null);
    expect(dialog().textContent).toContain('workflow changed');
  });
});

it('constructs a first step without offering Exit in the visual drawer', async () => {
  await mount({draft: {nodes: []}});
  click(container.querySelector('[aria-label="Add first step"]'));
  expect(dialog().querySelector('[data-node-type="exit"]')).toBe(null);
  change('visual-step-type', 'wait_duration');
  click(button(dialog(), 'Save step'));
  expect(owner.state.data.draft.nodes[0].type).toBe('wait_duration');
  expect(container.textContent).toContain('Automation ends');
});

it('retains explicit Exit in Edit list and exposes steps beyond an Exit without executable connectors', async () => {
  await mount({draft: {nodes: [exit('end'), wait('unconnected')]}});
  const other = container.querySelector('[aria-label="Other draft steps"]');
  expect(other.textContent).toContain('No execution order is implied');
  expect(other.querySelector('[aria-label="Delete step 2"]')).not.toBe(null);
  click(button(container, 'Edit list'));
  click(button(container, 'Add Node'));
  const choice = Array.from(container.querySelectorAll('[role="menuitem"]')).find(el => el.textContent.trim() === 'Exit automation');
  expect(choice).toBeTruthy();
  click(choice);
  expect(owner.state.data.draft.nodes[2].type).toBe('exit');
});

it('keeps delete icons inside action cards, insertion controls on connectors, and ends read-only', async () => {
  await mount();
  const card = container.querySelector('.automation-visual-card');
  expect(card.querySelector('[aria-label="Delete step 1"]')).not.toBe(null);
  expect(card.querySelector('.automation-path-add')).toBe(null);
  const add = container.querySelector('[aria-label="Add after step 2"]');
  expect($(add).closest('.automation-path-insertion').length).toBe(1);
  expect(add.textContent).toBe('+');
  const end = container.querySelector('.automation-path-end-label');
  expect(end.textContent).toContain('Automation ends');
  expect(end.querySelectorAll('button,input,select').length).toBe(0);
  expect(container.querySelector('[aria-label="Delete step 3"]')).toBe(null);
});

it('opens the side drawer then the shared details dialog without changing the draft', async () => {
  await mount(); const before = owner.state.data;
  click(container.querySelector('[aria-label="Add after step 1"]'));
  expect(dialog().classList.contains('automation-node-drawer')).toBe(true);
  expect(dialog().textContent).toContain('Add a step');
  expect(dialog().textContent).not.toContain('Insert after');
  expect(dialog().querySelector('[data-node-type="if_has_tag"]')).toBe(null);
  expect(dialog().querySelector('[data-node-type="send_email"]').disabled).toBe(true);
  click(dialog().querySelector('[data-node-type="wait_duration"]'));
  expect(dialog().classList.contains('automation-node-drawer')).toBe(false);
  expect(dialog().querySelector('input[aria-label="days"]')).not.toBe(null);
  expect(owner.state.data).toBe(before);
});

it('shows an implied, non-editable end after the last insertion control without adding a canonical Exit', async () => {
  await mount({draft: {nodes: [wait('last')]}});
  const end = container.querySelector('.automation-path-end-label');
  expect(end.textContent).toBe(' Automation ends');
  expect(end.previousSibling.classList.contains('automation-path-insertion')).toBe(true);
  expect(owner.state.data.draft.nodes.map(node => node.id)).toEqual(['last']);
});
