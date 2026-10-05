import {createAutomationNode, automationWorkflowPreviewFlow} from './AutomationWorkflowEditor';
import {insertOnPath, removeStep, structureError, targetFields, fallsThrough, branchFallsIntoSibling, moveOnPath, deleteCondition, retargetGoTo} from './automationStructure';

const wait = id => ({id, type: 'wait_duration', label: id, duration: {days: 1, hours: 0, minutes: 0}});
const exit = id => ({id, type: 'exit', label: id});
const branch = (id, yes, no) => ({id, label: id, type: 'if_has_tag', draft_tag: 'vip', yes_node_id: yes, no_node_id: no});
let serial;
const create = type => createAutomationNode(type, {generateId: () => 'new-' + (++serial)});
beforeEach(() => {serial = 0;});

const reachableTargets = nodes => {
  const reachable = new Set();
  const visit = id => {
    if (reachable.has(id)) return;
    reachable.add(id);
    const node = nodes.find(item => item.id === id);
    targetFields(node).forEach(key => visit(node[key]));
  };
  visit(nodes[0].id);
  return reachable;
};

it('repeatedly nests both Yes and No conditions at terminal paths without generated jumps or orphans', () => {
  ['yes_node_id', 'no_node_id'].forEach(field => {
    let result = insertOnPath([], {}, 'if_conditions', create);
    let id = result.id;
    for (let depth = 0; depth < 8; depth += 1) {
      result = insertOnPath(result.nodes, {id, field}, 'if_conditions', create);
      id = result.id;
      expect(result.nodes.some(node => node.type === 'go_to')).toBe(false);
      expect(reachableTargets(result.nodes).size).toBe(result.nodes.length);
      expect(automationWorkflowPreviewFlow(result.nodes).branch).toBeTruthy();
    }
  });
});

['yes', 'no', 'both'].forEach(choice => {
  it('deletes a condition with explicit ' + choice + ' path handling', () => {
    const nodes = [branch('if', 'a', 'b'), wait('a'), exit('ae'), wait('b'), exit('be')];
    const original = JSON.stringify(nodes);
    const result = deleteCondition(nodes, 'if', choice, create);
    expect(result.nodes.some(node => node.id === 'if')).toBe(false);
    expect(result.nodes.some(node => node.id === 'a')).toBe(choice === 'yes');
    expect(result.nodes.some(node => node.id === 'b')).toBe(choice === 'no');
    expect(structureError(result.nodes)).toBe('');
    expect(JSON.stringify(nodes)).toBe(original);
  });
});

it('preserves shared downstream nodes when deleting both condition paths', () => {
  const nodes = [branch('if', 'a', 'b'), wait('a'), {id: 'go', type: 'go_to', target_node_id: 'end'}, wait('b'), exit('end')];
  expect(deleteCondition(nodes, 'if', 'both', create).nodes.some(node => node.id === 'end')).toBe(true);
});

it('moves a stable node while bypassing its old incoming references', () => {
  const nodes = [branch('if', 'a', 'b'), wait('a'), exit('ae'), wait('b'), exit('be')];
  const result = moveOnPath(nodes, 'a', {id: 'b'}, create);
  expect(result.nodes[0].yes_node_id).toBe('ae');
  expect(result.nodes.find(node => node.id === 'a')).toEqual(nodes[1]);
  expect(nodes[0].yes_node_id).toBe('a');
  expect(structureError(result.nodes)).toBe('');
});
const path = (nodes, start) => {
  const result = [];
  const positions = new Map(nodes.map((node, index) => [node.id, index]));
  let id = start;
  while (id) {
    if (result.includes(id)) throw new Error('cycle');
    result.push(id);
    const index = positions.get(id);
    const node = nodes[index];
    id = node.type === 'go_to' ? node.target_node_id : fallsThrough(node) && nodes[index + 1] ? nodes[index + 1].id : '';
  }
  return result;
};

it('inserts after an ordinary step without changing IDs, other references or its input', () => {
  const nodes = [branch('if', 'a', 'end'), wait('a'), exit('end')];
  const before = JSON.stringify(nodes);
  const added = insertOnPath(nodes, {id: 'a'}, 'wait_duration', create);
  expect(added.nodes.map(node => node.id)).toEqual(['if', 'a', added.id, 'end']);
  expect(added.nodes[0]).toBe(nodes[0]);
  expect(JSON.stringify(nodes)).toBe(before);
});

it('can add before an entry Exit without changing surviving node identities', () => {
  const nodes = [exit('end')];
  const added = insertOnPath(nodes, {id: 'end', field: 'entry'}, 'wait_duration', create);
  expect(path(added.nodes, added.id)).toEqual([added.id, 'end']);
  expect(added.nodes[1]).toBe(nodes[0]);
});

it('inserts before a detached Exit and preserves its terminal identity and all incoming paths', () => {
  const nodes = [branch('if', 'end', 'end'), exit('end')];
  const added = insertOnPath(nodes, {id: 'end', field: 'before'}, 'wait_duration', create);
  expect(added.nodes[0].yes_node_id).toBe(added.id);
  expect(added.nodes[0].no_node_id).toBe(added.id);
  expect(path(added.nodes, added.id)).toEqual([added.id, 'end']);
  expect(added.nodes[2]).toBe(nodes[1]);
  expect(nodes[0].yes_node_id).toBe('end');
});

it('isolates insertion into a shared branch target from ordinary fall-through and the other branch', () => {
  const nodes = [branch('if', 'end', 'end'), wait('other'), exit('end')];
  const added = insertOnPath(nodes, {id: 'if', field: 'yes_node_id'}, 'wait_duration', create);
  expect(added.routing).toBe(true);
  expect(added.nodes[0].yes_node_id).toBe(added.id);
  expect(added.nodes[0].no_node_id).toBe('end');
  expect(path(added.nodes, 'other')).not.toContain(added.id);
  expect(path(added.nodes, added.id)).toEqual([added.id, 'end']);
  expect(structureError(added.nodes)).toBe('');
});

it('starts a new condition with separate explicit Exit boundaries', () => {
  const added = insertOnPath([], {}, 'if_has_tag', create);
  const condition = added.nodes[0];
  expect(condition.yes_node_id).not.toBe(condition.no_node_id);
  expect(added.nodes.slice(1).map(node => node.type)).toEqual(['exit', 'exit']);
  ['yes_node_id', 'no_node_id'].forEach(field => {
    const withWait = insertOnPath(added.nodes, {id: condition.id, field}, 'wait_duration', create);
    const first = withWait.nodes.find(node => node.id === condition.id)[field];
    const other = condition[field === 'yes_node_id' ? 'no_node_id' : 'yes_node_id'];
    expect(path(withWait.nodes, first)).not.toContain(other);
    expect(withWait.nodes.find(node => node.id === path(withWait.nodes, first).pop()).type).toBe('exit');
  });
});

it('preserves a continuation explicitly using separate Go to boundaries when inserting a condition', () => {
  const added = insertOnPath([wait('a'), wait('b'), exit('end')], {id: 'a'}, 'if_conditions', create);
  const condition = added.nodes.find(node => node.id === added.id);
  targetFields(condition).forEach(field => {
    const boundary = added.nodes.find(node => node.id === condition[field]);
    expect(boundary.type).toBe('go_to');
    expect(boundary.target_node_id).toBe('b');
    expect(path(added.nodes, boundary.id)).toEqual([boundary.id, 'b', 'end']);
  });
  expect(structureError(added.nodes)).toBe('');
});

it('adds to an incomplete path with an explicit Exit and keeps the other path unchanged', () => {
  const nodes = [branch('if', '', 'end'), exit('end')];
  const added = insertOnPath(nodes, {id: 'if', field: 'yes_node_id'}, 'wait_duration', create);
  expect(added.nodes[0].no_node_id).toBe('end');
  expect(path(added.nodes, added.id)).not.toContain('end');
  expect(added.nodes.find(node => node.id === path(added.nodes, added.id).pop()).type).toBe('exit');
});

it('requires an explicit replacement for incoming paths and never deletes descendants', () => {
  const nodes = [branch('if', 'a', 'b'), wait('a'), wait('b'), exit('end')];
  expect(() => removeStep(nodes, 'a', '')).toThrow();
  const next = removeStep(nodes, 'a', 'end');
  expect(next.map(node => node.id)).toEqual(['if', 'b', 'end']);
  expect(next[0].yes_node_id).toBe('end');
  expect(next[0].no_node_id).toBe('b');
  expect(next[1]).toBe(nodes[2]);
});

it('refuses deletion of a boundary that would run a branch into its neighbour', () => {
  expect(() => removeStep([wait('yes'), exit('yes-end'), wait('no'), exit('no-end')], 'yes-end')).toThrow(/boundary/);
});

it('reports existing accidental fall-through without silently changing executable semantics', () => {
  const condition = branch('if', 'yes', 'no');
  const nodes = [condition, wait('yes'), wait('no'), exit('end')];
  expect(branchFallsIntoSibling(nodes, condition, 'yes_node_id')).toBe(true);
  expect(branchFallsIntoSibling(nodes, condition, 'no_node_id')).toBe(false);
  const separated = insertOnPath(nodes, {id: 'yes'}, 'exit', create);
  expect(branchFallsIntoSibling(separated.nodes, condition, 'yes_node_id')).toBe(false);
  expect(condition.no_node_id).toBe('no');
});

it('rejects duplicate IDs, stale insertion sources and direct self targets', () => {
  expect(() => insertOnPath([wait('a'), wait('a')], {id: 'a'}, 'exit', create)).toThrow(/Duplicate/);
  expect(() => insertOnPath([wait('a')], {id: 'missing'}, 'exit', create)).toThrow(/missing/);
  expect(structureError([branch('a', 'a', 'end'), exit('end')])).toMatch(/itself/);
  expect(structureError([{id: 'a', type: 'add_tag'}, {id: 'b', type: 'go_to', target_node_id: 'a'}])).toBe('');
});

it('allows backward cross-branch jumps and loops guarded by a wait', () => {
  expect(structureError([branch('if', 'yes', 'no'), wait('yes'), exit('end'), {id: 'no', type: 'go_to', target_node_id: 'yes'}])).toBe('');
  expect(structureError([wait('a'), {id: 'go', type: 'go_to', target_node_id: 'a'}])).toBe('');
});

it('allows a loop with a bypass around its wait for the runtime visit guard', () => {
  expect(structureError([branch('if', 'wait', 'go'), wait('wait'), {id: 'go', type: 'go_to', target_node_id: 'if'}])).toBe('');
});

it('prunes only the exclusive continuation and keeps the destination and input unchanged', () => {
  const nodes = [wait('a'), {id: 'go', type: 'go_to', target_node_id: 'b'}, wait('b'), wait('c'), exit('end')];
  const before = JSON.stringify(nodes);
  const result = retargetGoTo(nodes, 'go', 'c');
  expect(result.removed.map(node => node.id)).toEqual(['b']);
  expect(result.nodes.map(node => node.id)).toEqual(['a', 'go', 'c', 'end']);
  expect(JSON.stringify(nodes)).toBe(before);
});

it('preserves shared and independently referenced continuations', () => {
  const nodes = [branch('if', 'go', 'b'), {id: 'go', type: 'go_to', target_node_id: 'b'}, wait('b'), exit('end')];
  expect(retargetGoTo(nodes, 'go', 'end').removed).toEqual([]);
  const detached = [wait('a'), {id: 'go', type: 'go_to', target_node_id: 'b'}, wait('b'), exit('end'), {id: 'other', type: 'go_to', target_node_id: 'b'}];
  expect(retargetGoTo(detached, 'go', 'end').removed).toEqual([]);
});

it('renders nested conditions with bounded, unique cards for converging paths', () => {
  const nodes = [branch('outer', 'inner', 'end'), branch('inner', 'a', 'end'), wait('a'), exit('end')];
  const flow = automationWorkflowPreviewFlow(nodes);
  const ids = flow.main.map(block => block.item.id);
  const visit = lanes => lanes.forEach(lane => lane.blocks.forEach(block => {
    if (block.kind === 'node') ids.push(block.item.id);
    if (block.branch) visit(block.branch.lanes);
  }));
  visit(flow.branch.lanes);
  expect(ids).toEqual(['outer', 'inner', 'a', 'end']);
  expect(new Set(ids).size).toBe(ids.length);
  const limited = automationWorkflowPreviewFlow(nodes, {maxDepth: 2});
  expect(limited.branch.lanes[0].blocks[0].branch.lanes[0].blocks[0].warning).toBe(true);
});
