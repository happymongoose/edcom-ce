import React from 'react';
import ReactDOM from 'react-dom';
import AutomationViewport from './AutomationViewport';
import AutomationWorkflowEditor, {
  automationWorkflowPreviewFlow, automationPreviewBranchWidth, automationPreviewPathWidth,
} from './AutomationWorkflowEditor';

// Every binary nesting shape up to three conditions deep, including both sides
// expanding and asymmetric trees. Each leaf is an explicit terminal branch.
const shapes = depth => depth ? [null, ...shapes(depth - 1).reduce((all, left) =>
  all.concat(shapes(depth - 1).map(right => [left, right])), [])] : [null];
function workflow(shape) {
  const nodes = [];
  function add(tree) {
    const id = 'node-' + nodes.length;
    const node = tree ? {id, label: 'If conditions', type: 'if_conditions',
      condition: {mode: 'all', items: [{type: 'has_tag', tag: 'vip'}]}} : {id, type: 'exit', label: 'Exit'};
    nodes.push(node);
    if (tree) { node.yes_node_id = add(tree[0]); node.no_node_id = add(tree[1]); }
    return id;
  }
  add(shape);
  return nodes;
}
const leafCount = shape => shape ? leafCount(shape[0]) + leafCount(shape[1]) : 1;

shapes(3).forEach((shape, index) => {
  it('reserves nonoverlapping horizontal space for nesting permutation ' + index, () => {
    const nodes = workflow(shape);
    const original = JSON.stringify(nodes);
    const flow = automationWorkflowPreviewFlow(nodes);
    const leaves = leafCount(shape);
    expect(automationPreviewBranchWidth(flow.branch)).toBe(leaves * 340 + (leaves - 1) * 32);
    function verify(branch) {
      if (!branch) return;
      const widths = branch.lanes.map(lane => automationPreviewPathWidth(lane.blocks));
      expect(automationPreviewBranchWidth(branch)).toBe(widths[0] + widths[1] + 32);
      branch.lanes.forEach((lane, laneIndex) => lane.blocks.forEach(block => {
        expect(automationPreviewBranchWidth(block.branch)).toBeLessThanOrEqual(widths[laneIndex]);
        verify(block.branch);
      }));
    }
    verify(flow.branch);
    expect(JSON.stringify(nodes)).toBe(original);
  });
});

it('renders nested Yes and No subtrees at their reserved widths without changing draft data', () => {
  const container = document.createElement('div'); document.body.appendChild(container);
  const nodes = workflow([[null, [null, null]], [[null, null], null]]);
  const update = jest.fn();
  try {
    ReactDOM.render(<AutomationWorkflowEditor nodes={nodes} update={update}
      renderNodeContactCount={() => '0 live contacts'} />, container);
    const canvas = container.querySelector('.automation-preview-canvas');
    expect(canvas.style.width).toBe((6 * 340 + 5 * 32) + 'px');
    const subtrees = Array.from(container.querySelectorAll('.automation-branch-subtree'));
    expect(subtrees.length).toBe(5);
    subtrees.forEach(subtree => {
      const grid = Array.from(subtree.querySelectorAll('div')).find(el => el.style.gridTemplateColumns);
      const widths = grid.style.gridTemplateColumns.split(' ').map(parseFloat);
      expect(parseFloat(subtree.style.width)).toBe(widths[0] + widths[1] + 32);
      expect(grid.style.gridTemplateColumns).not.toContain('auto-fit');
    });
    expect(update).not.toHaveBeenCalled();
  } finally {
    ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);
  }
});

it('keeps shared targets and backward jumps finite instead of duplicating subtrees', () => {
  const nodes = workflow([[null, null], null]);
  nodes[1].no_node_id = nodes[0].no_node_id;
  const last = nodes[nodes.length - 1];
  last.type = 'go_to'; last.target_node_id = nodes[0].id;
  const flow = automationWorkflowPreviewFlow(nodes);
  expect(automationPreviewBranchWidth(flow.branch)).toBe(1084);
  expect(flow.branch.lanes[1].blocks[0].kind).toBe('reference');
});

it('starts centred and preserves user scrolling on ordinary updates and subtree expansion', () => {
  const editor = new AutomationViewport({width: 2152});
  const viewport = document.createElement('div');
  Object.defineProperty(viewport, 'clientWidth', {value: 1000});
  editor.viewport = viewport;
  editor.align();
  expect(viewport.scrollLeft).toBe(600);
  viewport.scrollLeft = 800;
  editor.align();
  expect(viewport.scrollLeft).toBe(800);
  editor.props = {width: 2552};
  editor.align();
  expect(viewport.scrollLeft).toBe(1000);
});
