// These operations edit the existing ordered workflow, never a visual model.
export const isBranch = node => /^if_/.test(node.type);
export const fallsThrough = node => node && node.type !== 'exit' && node.type !== 'go_to' && !isBranch(node);
export const targetFields = node => isBranch(node) ? ['yes_node_id', 'no_node_id'] : node.type === 'go_to' ? ['target_node_id'] : [];
export const movableNode = node => ['add_tag', 'remove_tag', 'add_to_list', 'remove_from_list', 'send_email', 'wait_duration'].includes(node.type);
export const incomingTargets = (nodes, id) => nodes.filter(node => node.id !== id)
  .reduce((refs, node) => refs.concat(targetFields(node).filter(field => node[field] === id)
    .map(field => ({id: node.id, label: node.label, field}))), []);

export function branchFallsIntoSibling(nodes, source, field) {
  const start = source[field];
  const sibling = source[field === 'yes_node_id' ? 'no_node_id' : 'yes_node_id'];
  if (!start || start === sibling) return false; // Explicit shared destination.
  let index = nodes.findIndex(node => node.id === start);
  while (index >= 0 && fallsThrough(nodes[index]) && nodes[index + 1]) {
    index += 1;
    if (nodes[index].id === sibling) return true;
  }
  return false;
}

export function uniqueNode(nodes, id) {
  const matches = nodes.filter(node => node.id === id);
  if (matches.length !== 1) throw new Error('The selected step is missing or its ID is ambiguous. Close and reopen the editor.');
  return matches[0];
}

export function insertOnPath(nodes, location, type, create) {
  const result = nodes.slice();
  const ids = new Set(nodes.map(node => node.id));
  if (ids.size !== nodes.length) throw new Error('Duplicate step IDs must be repaired in Edit list first.');
  const make = kind => {
    const node = create(kind);
    if (!node.id || ids.has(node.id)) throw new Error('Could not create a unique step ID. Please try again.');
    ids.add(node.id);
    return node;
  };
  const added = make(type);
  let continuation;
  let routing = false;
  if (!nodes.length) {
    result.push(added);
  } else {
    const source = uniqueNode(nodes, location.id);
    if (location.field === 'before') {
      continuation = source;
      result.splice(nodes.indexOf(source), 0, added);
      result.forEach((node, index) => {
        const patch = {};
        targetFields(node).forEach(field => { if (node[field] === source.id) patch[field] = added.id; });
        if (Object.keys(patch).length) result[index] = {...node, ...patch};
      });
    } else if (location.field === 'entry') {
      if (nodes[0].id !== source.id) throw new Error('The first step changed. Reopen the editor.');
      continuation = source;
      result.unshift(added);
    } else if (location.field) {
      if (!targetFields(source).includes(location.field)) throw new Error('This path is no longer available.');
      const target = nodes.find(node => node.id === source[location.field]);
      if (target) {
        const index = nodes.indexOf(target);
        const additions = [];
        // Preserve entry and any existing fall-through into the shared target.
        if (index === 0 || fallsThrough(nodes[index - 1])) {
          const bypass = make('go_to');
          bypass.target_node_id = target.id;
          bypass.label = 'Preserve shared path';
          additions.push(bypass);
          routing = true;
        }
        additions.push(added);
        result.splice(index, 0, ...additions);
        continuation = target;
      } else {
        continuation = make('exit');
        result.splice(nodes.indexOf(source) + 1, 0, added, continuation);
      }
      const sourceIndex = result.findIndex(node => node.id === source.id);
      result[sourceIndex] = {...source, [location.field]: added.id};
    } else {
      if (!fallsThrough(source)) throw new Error('Choose a Yes, No or Go to path to insert here.');
      const index = nodes.indexOf(source);
      continuation = nodes[index + 1];
      result.splice(index + 1, 0, added);
    }
  }
  if (isBranch(added) && continuation && continuation.type === 'exit') {
    // An existing terminal is already a path boundary: retain its stable ID
    // for Yes and create a separate No terminal, rather than routing through
    // generated Go tos which hide the continuation from the tree preview.
    const noEnd = make('exit');
    added.yes_node_id = continuation.id;
    added.no_node_id = noEnd.id;
    result.splice(result.indexOf(continuation) + 1, 0, noEnd);
  } else if (isBranch(added)) {
    // Each new lane has its own explicit boundary. Never let array order
    // make the Yes lane fall into the No lane.
    const ends = ['yes_node_id', 'no_node_id'].map(field => {
      const end = make(continuation ? 'go_to' : 'exit');
      if (continuation) end.target_node_id = continuation.id;
      added[field] = end.id;
      return end;
    });
    result.splice(result.indexOf(added) + 1, 0, ...ends);
  } else if (added.type === 'go_to' && !continuation) {
    continuation = make('exit');
    result.splice(result.indexOf(added) + 1, 0, continuation);
  }
  if (added.type === 'go_to') added.target_node_id = continuation.id;
  return {nodes: result, id: added.id, routing};
}

export function removeStep(nodes, id, replacement) {
  const selected = uniqueNode(nodes, id);
  const index = nodes.indexOf(selected);
  if ((selected.type === 'exit' || selected.type === 'go_to') && fallsThrough(nodes[index - 1]) && nodes[index + 1]) {
    throw new Error('Deleting this path boundary would make the preceding step run into the next path. Keep an Exit or Go to boundary; use Edit list for explicit restructuring.');
  }
  const incoming = incomingTargets(nodes, id);
  if (incoming.length) {
    if (replacement === id) throw new Error('Choose a different replacement step.');
    uniqueNode(nodes, replacement);
  }
  return nodes.filter(node => node.id !== id).map(node => {
    const patch = {};
    targetFields(node).forEach(field => { if (node[field] === id) patch[field] = replacement; });
    return Object.keys(patch).length ? {...node, ...patch} : node;
  });
}

export function movePlacement(nodes, id) {
  const index = nodes.findIndex(node => node.id === id);
  return {previous: index > 0 ? nodes[index - 1].id : null,
    next: nodes[index + 1] ? nodes[index + 1].id : null,
    incoming: incomingTargets(nodes, id).map(ref => ({id: ref.id, field: ref.field}))
      .sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : a.field < b.field ? -1 : a.field > b.field ? 1 : 0)};
}

export function moveOnPath(nodes, id, location, create) {
  const node = uniqueNode(nodes, id);
  if (!movableNode(node)) throw new Error('Only actions and Wait steps can be moved.');
  if (location.id === id) throw new Error('Choose a different insertion point.');
  const index = nodes.indexOf(node);
  let next = nodes[index + 1];
  let remaining = nodes.filter(item => item.id !== id);
  if (!next && incomingTargets(nodes, id).length) {
    next = create('exit');
    if (nodes.some(item => item.id === next.id)) throw new Error('Could not create a unique path boundary. Try again.');
    remaining.push(next);
  }
  remaining = remaining.map(item => {
    const patch = {};
    targetFields(item).forEach(field => {if (item[field] === id) patch[field] = next.id;});
    return Object.keys(patch).length ? {...item, ...patch} : item;
  });
  let inserted = false;
  const result = insertOnPath(remaining, location, node.type, type => {
    if (!inserted) {inserted = true; return node;}
    return create(type);
  });
  const error = structureError(result.nodes);
  if (error) throw new Error(error);
  return result;
}

export function deleteCondition(nodes, id, choice, create) {
  const condition = uniqueNode(nodes, id);
  if (!isBranch(condition) || !['yes', 'no', 'both'].includes(choice)) throw new Error('Choose which condition paths to keep.');
  const edges = node => fallsThrough(node) ? (nodes[nodes.indexOf(node) + 1] ? [nodes[nodes.indexOf(node) + 1].id] : []) : targetFields(node).map(field => node[field]);
  const reachable = start => {
    const found = new Set();
    const queue = [start];
    while (queue.length) {
      const next = queue.pop();
      if (!next || next === id || found.has(next)) continue;
      const node = nodes.find(item => item.id === next);
      if (!node) continue;
      found.add(next); edges(node).forEach(target => queue.push(target));
    }
    return found;
  };
  const yes = reachable(condition.yes_node_id), no = reachable(condition.no_node_id);
  const candidates = new Set();
  if (choice !== 'yes') yes.forEach(target => {if (!no.has(target)) candidates.add(target);});
  if (choice !== 'no') no.forEach(target => {if (!yes.has(target)) candidates.add(target);});
  // Preserve shared continuations and anything entered from outside the removed
  // branch. Reachability follows canonical edges, including nested conditions.
  const protectedIds = new Set();
  nodes.filter(node => node.id !== id && !candidates.has(node.id)).forEach(node => edges(node).forEach(target => {
    if (candidates.has(target)) reachable(target).forEach(value => protectedIds.add(value));
  }));
  if (nodes[0] && candidates.has(nodes[0].id)) reachable(nodes[0].id).forEach(value => protectedIds.add(value));
  const removed = nodes.filter(node => node.id === id || (candidates.has(node.id) && !protectedIds.has(node.id)));
  const removedIds = new Set(removed.map(node => node.id));
  const index = nodes.indexOf(condition);
  let remaining = nodes.filter(node => !removedIds.has(node.id));
  const position = nodes.slice(0, index).filter(node => !removedIds.has(node.id)).length;
  const make = type => {
    const node = create(type);
    if (nodes.some(item => item.id === node.id)) throw new Error('Could not create a unique path boundary. Try again.');
    return node;
  };
  let target;
  if (choice === 'both') {
    target = make('exit'); remaining.splice(position, 0, target);
  } else {
    target = uniqueNode(remaining, condition[choice === 'yes' ? 'yes_node_id' : 'no_node_id']);
    if (remaining.indexOf(target) < position) throw new Error('Keeping this earlier target requires explicit restructuring in Edit list. Nothing was deleted.');
    if (!remaining[position] || remaining[position].id !== target.id) {
      const route = make('go_to'); route.target_node_id = target.id; remaining.splice(position, 0, route);
    }
  }
  remaining = remaining.map(node => {
    const patch = {};
    targetFields(node).forEach(field => {if (node[field] === id) patch[field] = target.id;});
    return Object.keys(patch).length ? {...node, ...patch} : node;
  });
  const error = structureError(remaining);
  if (error) throw new Error(error);
  return {nodes: remaining, removed, preserved: nodes.filter(node => candidates.has(node.id) && protectedIds.has(node.id))};
}

// Local structural feedback only. Backend publishing remains authoritative.
// Unrelated incomplete draft targets remain editable in the list view.
export function structureError(nodes) {
  const ids = new Set(nodes.map(node => node.id));
  if (ids.size !== nodes.length) return 'Step IDs must be unique.';
  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    if (targetFields(node).some(field => node[field] === node.id)) {
      return 'A step cannot target itself.';
    }
  }
  return '';
}

// Remove only the abandoned, exclusive continuation. Shared or independently
// referenced steps remain; array position alone never determines deletion.
export function retargetGoTo(nodes, id, target) {
  const source = uniqueNode(nodes, id);
  uniqueNode(nodes, target);
  if (source.type !== 'go_to' || id === target) throw new Error('Choose a different destination node.');
  const changed = nodes.map(node => node.id === id ? {...node, target_node_id: target} : node);
  const edges = (workflow, node) => fallsThrough(node) ?
    (workflow[workflow.indexOf(node) + 1] ? [workflow[workflow.indexOf(node) + 1].id] : []) : targetFields(node).map(field => node[field]);
  const reachable = (workflow, start) => {
    const found = new Set(), queue = [start];
    while (queue.length) {
      const next = queue.pop();
      if (!next || found.has(next)) continue;
      const node = workflow.find(item => item.id === next);
      if (!node) continue;
      found.add(next); edges(workflow, node).forEach(value => queue.push(value));
    }
    return found;
  };
  const retained = reachable(changed, changed[0].id);
  reachable(changed, target).forEach(value => retained.add(value));
  retained.add(id);
  const candidates = new Set();
  reachable(nodes, source.target_node_id).forEach(value => {if (!retained.has(value)) candidates.add(value);});
  changed.filter(node => !candidates.has(node.id)).forEach(node => edges(changed, node).forEach(destination => {
    if (candidates.has(destination)) reachable(changed, destination).forEach(value => retained.add(value));
  }));
  const removed = changed.filter(node => candidates.has(node.id) && !retained.has(node.id));
  const removedIds = new Set(removed.map(node => node.id));
  const result = changed.filter(node => !removedIds.has(node.id));
  const error = structureError(result);
  if (error) throw new Error(error);
  return {nodes: result, removed};
}
