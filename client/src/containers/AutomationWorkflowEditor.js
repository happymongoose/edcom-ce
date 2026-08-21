import React, { Component } from "react";
import axios from "axios";
import { Button, ButtonGroup, DropdownButton, FormControl, MenuItem } from "react-bootstrap";
import _ from "underscore";
import shortid from "shortid";
import Select2 from "react-select2-wrapper";
import { SelectLabel } from "../components/FormControls";
import { EDFormBox } from "../components/EDDOM";
import fixTag from "../utils/fixtag";
import getvalue from "../utils/getvalue";

export function automationNodeTypeLabel(type) {
  if (type === 'add_tag') {
    return 'Add tag';
  }
  if (type === 'remove_tag') {
    return 'Remove tag';
  }
  if (type === 'add_to_list') {
    return 'Add to list';
  }
  if (type === 'remove_from_list') {
    return 'Remove from list';
  }
  if (type === 'wait_duration') {
    return 'Wait';
  }
  if (type === 'if_has_tag') {
    return 'If has tag';
  }
  if (type === 'if_missing_tag') {
    return 'If missing tag';
  }
  if (type === 'if_opened_email') {
    return 'If opened email';
  }
  if (type === 'if_clicked_email') {
    return 'If clicked email';
  }
  if (type === 'if_conditions') {
    return 'If conditions';
  }
  if (type === 'go_to') {
    return 'Go to';
  }
  if (type === 'send_email') {
    return 'Send email';
  }
  return 'Exit';
}

export function automationEditorTypeLabel(type) {
  if (type === 'beefree') {
    return 'BeeFree';
  }
  if (type === 'wysiwyg') {
    return 'WYSIWYG';
  }
  if (type === 'raw') {
    return 'HTML';
  }
  return 'Legacy';
}

export function automationEmailOptions(emails) {
  return _.map(emails || [], email => ({
    id: email.id,
    name: (email.name || 'Untitled email') +
      ' - ' +
      (email.subject || 'No subject') +
      ' (' +
      automationEditorTypeLabel(email.type) +
      ')',
  }));
}

export function automationClickMatchValue(node) {
  if ((node || {}).click_match === 'url') {
    return 'url_exact';
  }
  return (node || {}).click_match || 'any';
}

export function automationListOptions(lists) {
  return _.map(lists || [], list => ({
    id: list.id,
    name: (list.name || 'Untitled list') +
      (list.count !== undefined && list.count !== null ? ' (' + list.count + ' contacts)' : ''),
  }));
}

export function automationNodeTargetOptions(nodes, node) {
  return _.chain(nodes || [])
    .map((target, index) => ({
      target: target,
      step: index + 1,
    }))
    .filter(option => option.target.id !== node.id)
    .map(option => ({
      id: option.target.id,
      name: 'Step ' + option.step + ' - ' +
        (option.target.label || automationNodeTypeLabel(option.target.type)) +
        ' (' + automationNodeTypeLabel(option.target.type) + ')',
    }))
    .value();
}

export function automationAddNodeMenuItems(hasEmails, hasLists) {
  return _.sortBy([
    {type: 'add_tag', label: 'Add Tag Node'},
    {type: 'add_to_list', label: 'Add To List Node', disabled: !hasLists},
    {type: 'exit', label: 'Add Exit Node'},
    {type: 'go_to', label: 'Go To Node'},
    {type: 'if_clicked_email', label: 'If Clicked Email Node', disabled: !hasEmails},
    {type: 'if_conditions', label: 'If Conditions Node'},
    {type: 'if_missing_tag', label: 'If Contact Does Not Have Tag Node'},
    {type: 'if_has_tag', label: 'If Has Tag Node'},
    {type: 'if_opened_email', label: 'If Opened Email Node', disabled: !hasEmails},
    {type: 'remove_from_list', label: 'Remove From List Node', disabled: !hasLists},
    {type: 'remove_tag', label: 'Remove Tag Node'},
    {type: 'send_email', label: 'Send Email Node', disabled: !hasEmails},
    {type: 'wait_duration', label: 'Wait Duration Node'},
  ], item => item.label.toLowerCase());
}

export function automationConditionItemTypeLabel(type) {
  if (type === 'has_tag') {
    return 'Has tag';
  }
  if (type === 'missing_tag') {
    return 'Missing tag';
  }
  if (type === 'opened_email') {
    return 'Opened email';
  }
  if (type === 'clicked_email') {
    return 'Clicked email';
  }
  if (type === 'in_list') {
    return 'In list';
  }
  if (type === 'not_in_list') {
    return 'Not in list';
  }
  return 'Unsupported condition';
}

export function createAutomationConditionItem(type, options) {
  const opts = options || {};
  const emails = opts.emails || [];
  const lists = opts.lists || [];
  if (type === 'opened_email') {
    return {type: type, automation_email_id: emails.length ? emails[0].id : ''};
  }
  if (type === 'clicked_email') {
    return {
      type: type,
      automation_email_id: emails.length ? emails[0].id : '',
      click_match: 'any',
      link_url: '',
    };
  }
  if (type === 'in_list' || type === 'not_in_list') {
    return {type: type, list_id: lists.length ? lists[0].id : ''};
  }
  return {type: type, tag: ''};
}

function optionName(options, id) {
  const option = _.findWhere(options || [], {id: id});
  return option ? option.name : '';
}

function targetSummary(nodes, node, id) {
  if (!id) {
    return 'Target missing';
  }
  const option = _.findWhere(automationNodeTargetOptions(nodes, node), {id: id});
  return option ? option.name : 'Target missing';
}

function durationSummary(duration) {
  const parts = [];
  const days = parseInt((duration || {}).days, 10) || 0;
  const hours = parseInt((duration || {}).hours, 10) || 0;
  const minutes = parseInt((duration || {}).minutes, 10) || 0;
  if (days) {
    parts.push(days + ' ' + (days === 1 ? 'day' : 'days'));
  }
  if (hours) {
    parts.push(hours + ' ' + (hours === 1 ? 'hour' : 'hours'));
  }
  if (minutes) {
    parts.push(minutes + ' ' + (minutes === 1 ? 'minute' : 'minutes'));
  }
  return parts.length ? parts.join(' ') : 'Wait duration incomplete';
}

function conditionItemSummary(item, options) {
  const opts = options || {};
  const emailOptions = automationEmailOptions(opts.emails || []);
  const listOptions = automationListOptions(opts.lists || []);
  if (item.type === 'has_tag') {
    return 'has tag ' + (item.tag || 'No tag selected');
  }
  if (item.type === 'missing_tag') {
    return 'missing tag ' + (item.tag || 'No tag selected');
  }
  if (item.type === 'opened_email') {
    return 'opened ' + (item.automation_email_id ? (optionName(emailOptions, item.automation_email_id) || 'Selected email not found') : 'No email selected');
  }
  if (item.type === 'clicked_email') {
    const clickMatch = automationClickMatchValue(item);
    let clickSummary = 'any link';
    if (clickMatch === 'url_exact') {
      clickSummary = 'exact URL ' + (item.link_url || 'No URL entered');
    } else if (clickMatch === 'url_prefix') {
      clickSummary = 'URL starts with ' + (item.link_url || 'No URL entered');
    }
    return 'clicked ' + clickSummary + ' in ' + (item.automation_email_id ? (optionName(emailOptions, item.automation_email_id) || 'Selected email not found') : 'No email selected');
  }
  if (item.type === 'in_list') {
    return 'in list ' + (item.list_id ? (optionName(listOptions, item.list_id) || 'Selected list not found') : 'No list selected');
  }
  if (item.type === 'not_in_list') {
    return 'not in list ' + (item.list_id ? (optionName(listOptions, item.list_id) || 'Selected list not found') : 'No list selected');
  }
  return 'Unsupported condition';
}

export function automationNodeSummary(node, options) {
  const opts = options || {};
  const nodes = opts.nodes || [];
  const emailOptions = automationEmailOptions(opts.emails || []);
  const listOptions = automationListOptions(opts.lists || []);

  if (node.type === 'send_email') {
    if (!node.automation_email_id) {
      return 'No email selected';
    }
    return 'Send email: ' + (optionName(emailOptions, node.automation_email_id) || 'Selected email not found');
  }
  if (node.type === 'add_tag') {
    return node.draft_tag ? 'Add tag: ' + node.draft_tag : 'No tag selected';
  }
  if (node.type === 'remove_tag') {
    return node.draft_tag ? 'Remove tag: ' + node.draft_tag : 'No tag selected';
  }
  if (node.type === 'add_to_list') {
    if (!node.list_id) {
      return 'No list selected';
    }
    return 'Add to list: ' + (optionName(listOptions, node.list_id) || 'Selected list not found');
  }
  if (node.type === 'remove_from_list') {
    if (!node.list_id) {
      return 'No list selected';
    }
    return 'Remove from list: ' + (optionName(listOptions, node.list_id) || 'Selected list not found');
  }
  if (node.type === 'wait_duration') {
    return 'Wait: ' + durationSummary(node.duration || {});
  }
  if (node.type === 'if_has_tag') {
    return 'If has tag: ' + (node.draft_tag || 'No tag selected') +
      ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
      ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
  }
  if (node.type === 'if_missing_tag') {
    return 'If missing tag: ' + (node.draft_tag || 'No tag selected') +
      ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
      ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
  }
  if (node.type === 'if_opened_email') {
    return 'If opened: ' + (node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected') +
      ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
      ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
  }
  if (node.type === 'if_clicked_email') {
    const clickMatch = automationClickMatchValue(node);
    let clickSummary = 'any link';
    if (clickMatch === 'url_exact') {
      clickSummary = 'exact URL: ' + (node.link_url || 'No URL entered');
    } else if (clickMatch === 'url_prefix') {
      clickSummary = 'URL starts with: ' + (node.link_url || 'No URL entered');
    }
    return 'If clicked ' + clickSummary + ': ' + (node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected') +
      ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
      ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
  }
  if (node.type === 'if_conditions') {
    const condition = node.condition || {};
    const items = condition.items || [];
    const mode = condition.mode === 'any' ? 'Any' : 'All';
    if (!items.length) {
      return mode + ' of 0 conditions: No conditions configured' +
        ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
        ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
    }
    const preview = _.map(items.slice(0, 2), item => conditionItemSummary(item, opts)).join(' | ');
    return mode + ' of ' + items.length + ' condition' + (items.length === 1 ? '' : 's') +
      ': ' + preview + (items.length > 2 ? ' | ...' : '') +
      ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
      ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
  }
  if (node.type === 'go_to') {
    return 'Go to: ' + targetSummary(nodes, node, node.target_node_id);
  }
  return 'Exit automation';
}

export function automationNodeSummaryWarning(summary) {
  return summary.indexOf('No ') === 0 ||
    summary.indexOf('No tag selected') !== -1 ||
    summary.indexOf('No email selected') !== -1 ||
    summary.indexOf('No list selected') !== -1 ||
    summary.indexOf('No conditions configured') !== -1 ||
    summary.indexOf('No URL entered') !== -1 ||
    summary.indexOf('Selected email not found') !== -1 ||
    summary.indexOf('Selected list not found') !== -1 ||
    summary.indexOf('Target missing') !== -1 ||
    summary.indexOf('Wait duration incomplete') !== -1;
}

function automationBranchNode(type) {
  return _.contains([
    'if_has_tag',
    'if_missing_tag',
    'if_opened_email',
    'if_clicked_email',
    'if_conditions',
  ], type);
}

function automationPreviewTarget(nodes, id) {
  if (!id) {
    return {
      id: '',
      missing: true,
      label: 'Target missing',
      step: null,
      type_label: '',
    };
  }
  const targetIndex = _.findIndex(nodes || [], node => node.id === id);
  if (targetIndex === -1) {
    return {
      id: id,
      missing: true,
      label: 'Target missing',
      step: null,
      type_label: '',
    };
  }
  const target = nodes[targetIndex];
  return {
    id: target.id,
    missing: false,
    label: 'Step ' + (targetIndex + 1) + ' - ' +
      (target.label || automationNodeTypeLabel(target.type)),
    step: targetIndex + 1,
    type_label: automationNodeTypeLabel(target.type),
  };
}

export function automationWorkflowPreviewItems(nodes, options) {
  const workflowNodes = nodes || [];
  const opts = {
    ...(options || {}),
    nodes: workflowNodes,
  };

  return _.map(workflowNodes, (node, index) => {
    const summary = automationNodeSummary(node, opts);
    const item = {
      id: node.id,
      node: node,
      step: index + 1,
      type: node.type,
      type_label: automationNodeTypeLabel(node.type),
      summary: summary,
      warning: automationNodeSummaryWarning(summary),
      connections: [],
      linear_continuation: false,
      terminal_label: '',
    };

    if (node.type === 'exit') {
      item.terminal_label = 'Terminal exit';
    } else if (node.type === 'go_to') {
      item.connections.push({
        kind: 'go_to',
        label: 'Go to',
        target: automationPreviewTarget(workflowNodes, node.target_node_id),
      });
    } else if (automationBranchNode(node.type)) {
      item.connections.push({
        kind: 'branch',
        label: 'Yes',
        target: automationPreviewTarget(workflowNodes, node.yes_node_id),
      });
      item.connections.push({
        kind: 'branch',
        label: 'No',
        target: automationPreviewTarget(workflowNodes, node.no_node_id),
      });
    } else if (workflowNodes[index + 1]) {
      item.connections.push({
        kind: 'linear',
        label: 'Next',
        target: automationPreviewTarget(workflowNodes, workflowNodes[index + 1].id),
      });
      item.linear_continuation = true;
    } else {
      item.terminal_label = 'Completes automation';
    }

    if (_.some(item.connections, connection => connection.target.missing)) {
      item.warning = true;
    }

    return item;
  });
}

function automationPreviewTargetStepSummary(nodes, id) {
  const target = automationPreviewTarget(nodes, id);
  if (target.missing) {
    return 'Target missing';
  }
  return 'Step ' + target.step;
}

function automationWorkflowPreviewSummary(node, options) {
  const opts = options || {};
  const nodes = opts.nodes || [];
  const emailOptions = automationEmailOptions(opts.emails || []);
  const listOptions = automationListOptions(opts.lists || []);
  const branchSummary = ' | Yes -> ' + automationPreviewTargetStepSummary(nodes, node.yes_node_id) +
    ' | No -> ' + automationPreviewTargetStepSummary(nodes, node.no_node_id);

  if (node.type === 'send_email') {
    if (!node.automation_email_id) {
      return 'No email selected';
    }
    return optionName(emailOptions, node.automation_email_id) || 'Selected email not found';
  }
  if (node.type === 'add_tag' || node.type === 'remove_tag') {
    return node.draft_tag || 'No tag selected';
  }
  if (node.type === 'add_to_list' || node.type === 'remove_from_list') {
    if (!node.list_id) {
      return 'No list selected';
    }
    return optionName(listOptions, node.list_id) || 'Selected list not found';
  }
  if (node.type === 'wait_duration') {
    return durationSummary(node.duration || {});
  }
  if (node.type === 'if_has_tag' || node.type === 'if_missing_tag') {
    return (node.draft_tag || 'No tag selected') + branchSummary;
  }
  if (node.type === 'if_opened_email') {
    return (node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected') +
      branchSummary;
  }
  if (node.type === 'if_clicked_email') {
    const clickMatch = automationClickMatchValue(node);
    let clickSummary = 'any link';
    if (clickMatch === 'url_exact') {
      clickSummary = 'exact URL: ' + (node.link_url || 'No URL entered');
    } else if (clickMatch === 'url_prefix') {
      clickSummary = 'URL starts with: ' + (node.link_url || 'No URL entered');
    }
    return clickSummary + ' in ' +
      (node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected') +
      branchSummary;
  }
  if (node.type === 'if_conditions') {
    const condition = node.condition || {};
    const items = condition.items || [];
    const mode = condition.mode === 'any' ? 'Any' : 'All';
    if (!items.length) {
      return 'No conditions configured' + branchSummary;
    }
    if (items.length === 1) {
      return conditionItemSummary(items[0], opts) + branchSummary;
    }
    const preview = _.map(items.slice(0, 2), item => conditionItemSummary(item, opts)).join(' | ');
    return mode + ' of ' + items.length + ' conditions: ' +
      preview + (items.length > 2 ? ' | ...' : '') + branchSummary;
  }
  if (node.type === 'go_to') {
    return automationPreviewTargetStepSummary(nodes, node.target_node_id);
  }
  if (node.type === 'exit') {
    return '';
  }
  return automationNodeSummary(node, opts);
}

function automationWorkflowPreviewItemForNode(workflowNodes, node, options) {
  const index = _.findIndex(workflowNodes || [], candidate => candidate.id === node.id);
  const opts = {
    ...(options || {}),
    nodes: workflowNodes || [],
  };
  const summary = automationWorkflowPreviewSummary(node, opts);
  const item = {
    id: node.id,
    node: node,
    step: index + 1,
    type: node.type,
    type_label: node.type === 'exit' ? 'Exit automation' : automationNodeTypeLabel(node.type),
    summary: summary,
    warning: automationNodeSummaryWarning(summary),
    connections: [],
    terminal_label: '',
    nested_branch_stop: false,
  };

  if (node.type === 'exit') {
    item.terminal_label = '';
  } else if (node.type === 'go_to') {
    item.connections.push({
      kind: 'go_to',
      label: 'Go to',
      target: automationPreviewTarget(workflowNodes, node.target_node_id),
    });
  } else if (automationBranchNode(node.type)) {
    item.connections.push({
      kind: 'branch',
      label: 'Yes',
      target: automationPreviewTarget(workflowNodes, node.yes_node_id),
    });
    item.connections.push({
      kind: 'branch',
      label: 'No',
      target: automationPreviewTarget(workflowNodes, node.no_node_id),
    });
  }

  if (_.some(item.connections, connection => connection.target.missing)) {
    item.warning = true;
  }

  return item;
}

function automationWorkflowPreviewMissingBlock(workflowNodes, targetId) {
  return {
    kind: 'missing',
    warning: true,
    target: automationPreviewTarget(workflowNodes, targetId),
  };
}

function automationWorkflowPreviewReferenceBlock(workflowNodes, nodeId, label) {
  return {
    kind: 'reference',
    target: automationPreviewTarget(workflowNodes, nodeId),
    label: label || 'Continues at',
  };
}

function automationWorkflowPreviewNodeIndex(workflowNodes, nodeId) {
  for (let i = 0; i < (workflowNodes || []).length; i += 1) {
    if (workflowNodes[i].id === nodeId) {
      return i;
    }
  }
  return -1;
}

function automationWorkflowPreviewPath(workflowNodes, startId, options, visited, depth) {
  const opts = options || {};
  const maxDepth = opts.maxDepth || 40;
  const blocks = [];
  let nodeId = startId;
  let currentVisited = {...(visited || {})};
  let currentDepth = depth || 0;

  if (!nodeId) {
    return [automationWorkflowPreviewMissingBlock(workflowNodes, nodeId)];
  }

  while (nodeId) {
    if (currentDepth >= maxDepth) {
      blocks.push({
        kind: 'reference',
        warning: true,
        label: 'Preview depth limit reached at',
        target: automationPreviewTarget(workflowNodes, nodeId),
      });
      return blocks;
    }

    const nodeIndex = automationWorkflowPreviewNodeIndex(workflowNodes, nodeId);
    if (nodeIndex === -1) {
      blocks.push(automationWorkflowPreviewMissingBlock(workflowNodes, nodeId));
      return blocks;
    }

    if (currentVisited[nodeId]) {
      blocks.push(automationWorkflowPreviewReferenceBlock(workflowNodes, nodeId, 'Continues at'));
      return blocks;
    }

    const node = workflowNodes[nodeIndex];
    const item = automationWorkflowPreviewItemForNode(workflowNodes, node, opts);
    currentVisited = {
      ...currentVisited,
      [nodeId]: true,
    };
    blocks.push({
      kind: 'node',
      item: item,
    });

    if (node.type === 'exit') {
      return blocks;
    }
    if (node.type === 'go_to') {
      return blocks;
    }
    if (automationBranchNode(node.type)) {
      item.nested_branch_stop = true;
      return blocks;
    }
    if (!workflowNodes[nodeIndex + 1]) {
      item.terminal_label = 'Completes automation';
      return blocks;
    }

    nodeId = workflowNodes[nodeIndex + 1].id;
    currentDepth += 1;
  }

  return blocks;
}

export function automationWorkflowPreviewFlow(nodes, options) {
  const workflowNodes = nodes || [];
  const opts = {
    ...(options || {}),
    nodes: workflowNodes,
  };
  const main = [];
  let branch = null;
  let nodeId = workflowNodes[0] ? workflowNodes[0].id : '';
  let visited = {};
  let depth = 0;
  const maxDepth = opts.maxDepth || 40;

  while (nodeId) {
    if (depth >= maxDepth) {
      main.push({
        kind: 'reference',
        warning: true,
        label: 'Preview depth limit reached at',
        target: automationPreviewTarget(workflowNodes, nodeId),
      });
      break;
    }

    const nodeIndex = automationWorkflowPreviewNodeIndex(workflowNodes, nodeId);
    if (nodeIndex === -1) {
      main.push(automationWorkflowPreviewMissingBlock(workflowNodes, nodeId));
      break;
    }

    if (visited[nodeId]) {
      main.push(automationWorkflowPreviewReferenceBlock(workflowNodes, nodeId, 'Continues at'));
      break;
    }

    const node = workflowNodes[nodeIndex];
    const item = automationWorkflowPreviewItemForNode(workflowNodes, node, opts);
    visited = {
      ...visited,
      [nodeId]: true,
    };
    main.push({
      kind: 'node',
      item: item,
    });

    if (automationBranchNode(node.type)) {
      const laneVisited = {...visited};
      branch = {
        item: item,
        lanes: [
          {
            label: 'Yes',
            blocks: automationWorkflowPreviewPath(workflowNodes, node.yes_node_id, opts, laneVisited, depth + 1),
          },
          {
            label: 'No',
            blocks: automationWorkflowPreviewPath(workflowNodes, node.no_node_id, opts, laneVisited, depth + 1),
          },
        ],
      };
      break;
    }
    if (node.type === 'exit') {
      break;
    }
    if (node.type === 'go_to') {
      break;
    }
    if (!workflowNodes[nodeIndex + 1]) {
      item.terminal_label = 'Completes automation';
      break;
    }

    nodeId = workflowNodes[nodeIndex + 1].id;
    depth += 1;
  }

  return {
    main: main,
    branch: branch,
  };
}

export function automationWorkflowPreviewSummaryInline(type) {
  return _.contains([
    'add_tag',
    'remove_tag',
    'add_to_list',
    'remove_from_list',
    'wait_duration',
    'go_to',
  ], type);
}

export function createAutomationNode(type, options) {
  const opts = options || {};
  const emails = opts.emails || [];
  const lists = opts.lists || [];
  const generateId = opts.generateId || shortid.generate;
  const node = {
    id: generateId(),
    type: type,
    label: type === 'add_tag' ? 'Add tag' : type === 'remove_tag' ? 'Remove tag' : type === 'add_to_list' ? 'Add to list' : type === 'remove_from_list' ? 'Remove from list' : type === 'wait_duration' ? 'Wait' : type === 'if_has_tag' ? 'If contact has tag' : type === 'if_missing_tag' ? 'If contact does not have tag' : type === 'if_opened_email' ? 'If opened email' : type === 'if_clicked_email' ? 'If clicked email' : type === 'if_conditions' ? 'If conditions' : type === 'go_to' ? 'Go to' : type === 'send_email' ? 'Send email' : 'Exit automation',
  };

  if (type === 'add_tag' || type === 'remove_tag') {
    node.draft_tag = '';
  }
  if (type === 'if_has_tag' || type === 'if_missing_tag') {
    node.draft_tag = '';
    node.yes_node_id = '';
    node.no_node_id = '';
  }
  if (type === 'if_opened_email' || type === 'if_clicked_email') {
    node.automation_email_id = emails.length ? emails[0].id : '';
    node.yes_node_id = '';
    node.no_node_id = '';
    if (type === 'if_clicked_email') {
      node.click_match = 'any';
      node.link_url = '';
    }
  }
  if (type === 'if_conditions') {
    node.condition = {
      mode: 'all',
      items: [createAutomationConditionItem('has_tag', opts)],
    };
    node.yes_node_id = '';
    node.no_node_id = '';
  }
  if (type === 'wait_duration') {
    node.duration = {
      days: 0,
      hours: 0,
      minutes: 5,
    };
  }
  if (type === 'go_to') {
    node.target_node_id = '';
  }
  if (type === 'send_email') {
    node.automation_email_id = emails.length ? emails[0].id : '';
  }
  if (type === 'add_to_list' || type === 'remove_from_list') {
    node.list_id = lists.length ? lists[0].id : '';
  }

  return node;
}

export function appendAutomationNode(nodes, type, options) {
  return (nodes || []).concat([createAutomationNode(type, options)]);
}

export function insertAutomationNodeAfter(nodes, index, type, options) {
  const nextNodes = (nodes || []).slice();
  nextNodes.splice(index + 1, 0, createAutomationNode(type, options));
  return nextNodes;
}

export function moveAutomationNode(nodes, index, direction) {
  const nextNodes = (nodes || []).slice();
  const targetIndex = index + direction;
  if (index < 0 || index >= nextNodes.length || targetIndex < 0 || targetIndex >= nextNodes.length) {
    return nextNodes;
  }
  const node = nextNodes[index];
  nextNodes[index] = nextNodes[targetIndex];
  nextNodes[targetIndex] = node;
  return nextNodes;
}

class AutomationWorkflowEditor extends Component {
  state = {
    expandedNodeIds: {},
    emailLinksById: {},
    emailLinksLoading: {},
    emailLinksError: {},
    workflowView: 'edit',
  }

  componentDidMount() {
    this.loadVisibleClickedEmailLinks();
  }

  componentDidUpdate() {
    this.loadVisibleClickedEmailLinks();
  }

  loadVisibleClickedEmailLinks() {
    _.each(this.props.nodes || [], node => {
      if (
        this.state.expandedNodeIds[node.id] &&
        node.type === 'if_clicked_email' &&
        automationClickMatchValue(node) !== 'any' &&
        node.automation_email_id
      ) {
        this.loadAutomationEmailLinks(node.automation_email_id);
      }
      if (this.state.expandedNodeIds[node.id] && node.type === 'if_conditions') {
        _.each(((node.condition || {}).items || []), item => {
          if (
            item.type === 'clicked_email' &&
            automationClickMatchValue(item) !== 'any' &&
            item.automation_email_id
          ) {
            this.loadAutomationEmailLinks(item.automation_email_id);
          }
        });
      }
    });
  }

  loadAutomationEmailLinks(emailId) {
    if (!this.props.automationId || !emailId) {
      return;
    }
    if (
      this.state.emailLinksById[emailId] ||
      this.state.emailLinksLoading[emailId] ||
      this.state.emailLinksError[emailId]
    ) {
      return;
    }
    this.setState({
      emailLinksLoading: {
        ...this.state.emailLinksLoading,
        [emailId]: true,
      },
      emailLinksError: {
        ...this.state.emailLinksError,
        [emailId]: '',
      },
    });
    axios.get('/api/automations/' + this.props.automationId + '/emails/' + emailId + '/links')
      .then(response => {
        this.setState({
          emailLinksById: {
            ...this.state.emailLinksById,
            [emailId]: response.data.links || [],
          },
          emailLinksLoading: {
            ...this.state.emailLinksLoading,
            [emailId]: false,
          },
        });
      })
      .catch(() => {
        this.setState({
          emailLinksLoading: {
            ...this.state.emailLinksLoading,
            [emailId]: false,
          },
          emailLinksError: {
            ...this.state.emailLinksError,
            [emailId]: 'Could not load discovered links. Enter the URL manually.',
          },
        });
      });
  }

  nodeChange = (index, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            [event.target.id]: {$set: getvalue(event)},
          },
        },
      },
    });
  }

  nodeTagChange = (index, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            draft_tag: {$set: event.params.data.id},
          },
        },
      },
    });
  }

  nodeDurationChange = (index, event) => {
    const value = parseInt(event.target.value, 10);
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            duration: {
              [event.target.id]: {$set: isNaN(value) ? 0 : value},
            },
          },
        },
      },
    });
  }

  nodeTargetChange = (index, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            [event.target.id]: {$set: getvalue(event)},
          },
        },
      },
    });
  }

  conditionModeChange = (index, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            condition: {
              mode: {$set: getvalue(event)},
            },
          },
        },
      },
    });
  }

  conditionItemChange = (index, itemIndex, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            condition: {
              items: {
                [itemIndex]: {
                  [event.target.id]: {$set: getvalue(event)},
                },
              },
            },
          },
        },
      },
    });
  }

  conditionItemTypeChange = (index, itemIndex, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            condition: {
              items: {
                [itemIndex]: {$set: createAutomationConditionItem(getvalue(event), {
                  emails: this.props.emails || [],
                  lists: this.props.lists || [],
                })},
              },
            },
          },
        },
      },
    });
  }

  conditionItemTagChange = (index, itemIndex, event) => {
    this.conditionItemChange(index, itemIndex, {
      target: {
        id: 'tag',
        value: event.params.data.id,
      },
    });
  }

  addConditionItem = index => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            condition: {
              items: {
                $push: [createAutomationConditionItem('has_tag', {
                  emails: this.props.emails || [],
                  lists: this.props.lists || [],
                })],
              },
            },
          },
        },
      },
    });
  }

  removeConditionItem = (index, itemIndex) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            condition: {
              items: {
                $splice: [[itemIndex, 1]],
              },
            },
          },
        },
      },
    });
  }

  addNode = (type, afterIndex) => {
    const node = createAutomationNode(type, {
      emails: this.props.emails || [],
      lists: this.props.lists || [],
    });
    this.setState({
      expandedNodeIds: {
        ...this.state.expandedNodeIds,
        [node.id]: true,
      },
    });
    if (afterIndex === undefined || afterIndex === null) {
      this.props.update({
        draft: {
          nodes: {
            $push: [node],
          },
        },
      });
      return;
    }
    this.props.update({
      draft: {
        nodes: {
          $splice: [[afterIndex + 1, 0, node]],
        },
      },
    });
  }

  deleteNode = index => {
    this.props.update({
      draft: {
        nodes: {
          $splice: [[index, 1]],
        },
      },
    });
  }

  toggleNodeDetails = node => {
    this.setState({
      expandedNodeIds: {
        ...this.state.expandedNodeIds,
        [node.id]: !this.state.expandedNodeIds[node.id],
      },
    });
  }

  showWorkflowView = view => {
    this.setState({
      workflowView: view,
    });
  }

  editPreviewNode = node => {
    this.setState({
      workflowView: 'edit',
      expandedNodeIds: {
        ...this.state.expandedNodeIds,
        [node.id]: true,
      },
    });
  }

  moveNode = (index, direction) => {
    this.props.update({
      draft: {
        nodes: {
          $set: moveAutomationNode(this.props.nodes || [], index, direction),
        },
      },
    });
  }

  tagData() {
    const tags = this.props.tags || [];
    const nodes = this.props.nodes || [];
    const draftTags = _.pluck(_.filter(nodes, node => _.contains(['add_tag', 'remove_tag', 'if_has_tag', 'if_missing_tag'], node.type) && node.draft_tag), 'draft_tag');
    const conditionTags = _.flatten(_.map(nodes, node => _.map(((node.condition || {}).items || []), item => item.tag || '')));
    return _.map(_.uniq(tags.concat(draftTags).concat(conditionTags).concat(this.props.entryTags || [])), tag => tag).filter(Boolean).map(tag => ({id: tag, text: tag}));
  }

  nodeTargetOptions(node) {
    return automationNodeTargetOptions(this.props.nodes || [], node);
  }

  nodeSummary(node) {
    return automationNodeSummary(node, {
      nodes: this.props.nodes || [],
      emails: this.props.emails || [],
      lists: this.props.lists || [],
    });
  }

  renderNodeConfig(node, index) {
    if (node.type === 'add_tag' || node.type === 'remove_tag' || node.type === 'if_has_tag' || node.type === 'if_missing_tag') {
      return (
        <div style={{minWidth: '220px'}}>
          <Select2
            data={this.tagData()}
            value={node.draft_tag || ''}
            onSelect={this.nodeTagChange.bind(this, index)}
            style={{width:'100%'}}
            options={{
              placeholder: 'Select or create tag',
              tags: true,
              createTag: function (params) {
                const fixed = fixTag(params.term);
                if (!fixed) {
                  return null;
                }
                return {
                  id: fixed,
                  text: fixed,
                };
              }
            }}
          />
          <span className="help-block">Draft-only configuration. This is not validated or executable yet.</span>
          {
            node.type === 'if_has_tag' || node.type === 'if_missing_tag' ?
              <div className="space-top-sm">
                <SelectLabel
                  id="yes_node_id"
                  label="Yes target"
                  obj={node}
                  onChange={this.nodeTargetChange.bind(this, index)}
                  options={this.nodeTargetOptions(node)}
                  emptyVal="Select target"
                />
                <SelectLabel
                  id="no_node_id"
                  label="No target"
                  obj={node}
                  onChange={this.nodeTargetChange.bind(this, index)}
                  options={this.nodeTargetOptions(node)}
                  emptyVal="Select target"
                />
              </div>
            :
              null
          }
        </div>
      );
    }

    if (node.type === 'wait_duration') {
      const duration = node.duration || {};
      return (
        <div className="form-inline" style={{minWidth: '280px'}}>
          <FormControl
            id="days"
            type="number"
            min="0"
            value={duration.days || 0}
            onChange={this.nodeDurationChange.bind(this, index)}
            style={{width: '70px'}}
          />
          {' '}days{' '}
          <FormControl
            id="hours"
            type="number"
            min="0"
            value={duration.hours || 0}
            onChange={this.nodeDurationChange.bind(this, index)}
            style={{width: '70px'}}
          />
          {' '}hours{' '}
          <FormControl
            id="minutes"
            type="number"
            min="0"
            value={duration.minutes || 0}
            onChange={this.nodeDurationChange.bind(this, index)}
            style={{width: '70px'}}
          />
          {' '}minutes
        </div>
      );
    }

    if (node.type === 'go_to') {
      return (
        <div style={{minWidth: '220px'}}>
          <SelectLabel
            id="target_node_id"
            label="Target"
            obj={node}
            onChange={this.nodeTargetChange.bind(this, index)}
            options={this.nodeTargetOptions(node)}
            emptyVal="Select target"
          />
        </div>
      );
    }

    if (node.type === 'send_email') {
      const options = automationEmailOptions(this.props.emails || []);
      if (!options.length) {
        return (
          <div style={{minWidth: '260px'}}>
            <p className="help-block">Create an automation email before configuring this step.</p>
          </div>
        );
      }
      return (
        <div style={{minWidth: '320px'}}>
          <SelectLabel
            id="automation_email_id"
            label="Automation email"
            obj={node}
            onChange={this.nodeTargetChange.bind(this, index)}
            options={options}
            emptyVal="Select email"
          />
        </div>
      );
    }

    if (node.type === 'if_opened_email' || node.type === 'if_clicked_email') {
      const options = automationEmailOptions(this.props.emails || []);
      const clickMatch = automationClickMatchValue(node);
      const discoveredLinks = node.automation_email_id ?
        (this.state.emailLinksById[node.automation_email_id] || []) :
        [];
      const selectedDiscoveredLink = _.find(discoveredLinks, link => link.normalized_url === (node.link_url || ''));
      if (!options.length) {
        return (
          <div style={{minWidth: '260px'}}>
            <p className="help-block">Create an automation email before configuring this condition.</p>
          </div>
        );
      }
      return (
        <div style={{minWidth: '320px'}}>
          <SelectLabel
            id="automation_email_id"
            label="Automation email"
            obj={node}
            onChange={this.nodeTargetChange.bind(this, index)}
            options={options}
            emptyVal="Select email"
          />
          {
            node.type === 'if_clicked_email' ?
              <div>
                <label className="control-label" htmlFor="click_match">Click match</label>
                <FormControl
                  id="click_match"
                  componentClass="select"
                  value={clickMatch}
                  onChange={this.nodeTargetChange.bind(this, index)}
                >
                  <option value="any">Any link</option>
                  <option value="url_exact">Specific URL</option>
                  <option value="url_prefix">URL starts with</option>
                </FormControl>
                {
                  clickMatch !== 'any' ?
                    <div className="space-top-sm">
                      <label className="control-label" htmlFor="discovered_link_url">Discovered links</label>
                      {
                        node.automation_email_id && this.state.emailLinksLoading[node.automation_email_id] ?
                          <p className="help-block">Loading discovered links...</p>
                        :
                          null
                      }
                      {
                        node.automation_email_id && this.state.emailLinksError[node.automation_email_id] ?
                          <p className="help-block text-danger">{this.state.emailLinksError[node.automation_email_id]}</p>
                        :
                          null
                      }
                      <FormControl
                        id="discovered_link_url"
                        componentClass="select"
                        value={selectedDiscoveredLink ? node.link_url || '' : ''}
                        onChange={event => {
                          if (event.target.value) {
                            this.nodeTargetChange(index, {
                              target: {id: 'link_url', value: event.target.value},
                            });
                          }
                        }}
                        disabled={!discoveredLinks.length}
                      >
                        <option value="">
                          {discoveredLinks.length ? 'Select discovered URL' : 'No links discovered'}
                        </option>
                        {
                          _.map(discoveredLinks, link => (
                            <option key={link.normalized_url + '-' + link.tracked} value={link.normalized_url}>
                              {link.display_url || link.normalized_url}
                              {link.occurrence_count > 1 ? ' (' + link.occurrence_count + ')' : ''}
                              {link.tracked === false ? ' - untracked' : ''}
                            </option>
                          ))
                        }
                      </FormControl>
                      <span className="help-block">
                        Discovered links are extracted from saved email content. Enter the URL manually if a link is missing.
                      </span>
                      <label className="control-label" htmlFor="link_url">URL</label>
                      <FormControl
                        id="link_url"
                        type="text"
                        value={node.link_url || ''}
                        onChange={this.nodeTargetChange.bind(this, index)}
                        placeholder="https://example.com/page"
                      />
                      <span className="help-block">
                        {
                          clickMatch === 'url_prefix' ?
                            'URL starts with matches the same URL plus query strings or hash fragments, such as ?utm= or #section.' :
                            'Specific URL matches the normalized clicked URL exactly.'
                        }
                      </span>
                    </div>
                  :
                    null
                }
              </div>
            :
              null
          }
          <SelectLabel
            id="yes_node_id"
            label="Yes target"
            obj={node}
            onChange={this.nodeTargetChange.bind(this, index)}
            options={this.nodeTargetOptions(node)}
            emptyVal="Select target"
          />
          <SelectLabel
            id="no_node_id"
            label="No target"
            obj={node}
            onChange={this.nodeTargetChange.bind(this, index)}
            options={this.nodeTargetOptions(node)}
            emptyVal="Select target"
          />
        </div>
      );
    }

    if (node.type === 'if_conditions') {
      const condition = node.condition || {mode: 'all', items: []};
      const items = condition.items || [];
      return (
        <div style={{minWidth: '320px'}}>
          <label className="control-label" htmlFor="mode">Match</label>
          <FormControl
            id="mode"
            componentClass="select"
            value={condition.mode || 'all'}
            onChange={this.conditionModeChange.bind(this, index)}
          >
            <option value="all">All conditions</option>
            <option value="any">Any condition</option>
          </FormControl>
          <div className="space-top-sm">
            {
              _.map(items, (item, itemIndex) => this.renderConditionItem(node, index, item, itemIndex))
            }
          </div>
          <Button
            bsSize="small"
            onClick={this.addConditionItem.bind(this, index)}
            disabled={items.length >= 20}
          >
            Add condition
          </Button>
          <div className="space-top-sm">
            <SelectLabel
              id="yes_node_id"
              label="Yes target"
              obj={node}
              onChange={this.nodeTargetChange.bind(this, index)}
              options={this.nodeTargetOptions(node)}
              emptyVal="Select target"
            />
            <SelectLabel
              id="no_node_id"
              label="No target"
              obj={node}
              onChange={this.nodeTargetChange.bind(this, index)}
              options={this.nodeTargetOptions(node)}
              emptyVal="Select target"
            />
          </div>
        </div>
      );
    }

    if (node.type === 'add_to_list' || node.type === 'remove_from_list') {
      const options = automationListOptions(this.props.lists || []);
      if (!options.length) {
        return (
          <div style={{minWidth: '220px'}}>
            <p className="help-block">Create a contact list before selecting this node.</p>
          </div>
        );
      }

      return (
        <div style={{minWidth: '220px'}}>
          <SelectLabel
            id="list_id"
            obj={node}
            onChange={this.nodeTargetChange.bind(this, index)}
            options={options}
            emptyVal="Select list"
          />
        </div>
      );
    }

    return null;
  }

  renderConditionItem(node, index, item, itemIndex) {
    const emailOptions = automationEmailOptions(this.props.emails || []);
    const listOptions = automationListOptions(this.props.lists || []);
    const clickMatch = automationClickMatchValue(item);
    const discoveredLinks = item.automation_email_id ?
      (this.state.emailLinksById[item.automation_email_id] || []) :
      [];
    const selectedDiscoveredLink = _.find(discoveredLinks, link => link.normalized_url === (item.link_url || ''));

    return (
      <div
        key={itemIndex}
        style={{
          border: '1px solid #e3e8f0',
          borderRadius: '4px',
          padding: '12px',
          marginBottom: '10px',
          background: '#fbfcfe',
        }}
      >
        <div className="row">
          <div className="col-sm-3">
            <label className="control-label" htmlFor="type">Condition</label>
            <FormControl
              id="type"
              componentClass="select"
              value={item.type || 'has_tag'}
              onChange={this.conditionItemTypeChange.bind(this, index, itemIndex)}
            >
              <option value="clicked_email">Clicked email</option>
              <option value="has_tag">Has tag</option>
              <option value="in_list">In list</option>
              <option value="missing_tag">Missing tag</option>
              <option value="not_in_list">Not in list</option>
              <option value="opened_email">Opened email</option>
            </FormControl>
          </div>
          <div className="col-sm-7">
            {this.renderConditionItemFields(index, itemIndex, item, emailOptions, listOptions, clickMatch, discoveredLinks, selectedDiscoveredLink)}
          </div>
          <div className="col-sm-2">
            <label className="control-label">&nbsp;</label>
            <Button
              bsSize="small"
              onClick={this.removeConditionItem.bind(this, index, itemIndex)}
              disabled={((node.condition || {}).items || []).length <= 1}
              block
            >
              Remove
            </Button>
          </div>
        </div>
      </div>
    );
  }

  renderConditionItemFields(index, itemIndex, item, emailOptions, listOptions, clickMatch, discoveredLinks, selectedDiscoveredLink) {
    if (item.type === 'has_tag' || item.type === 'missing_tag') {
      return (
        <div>
          <label className="control-label">Tag</label>
          <Select2
            data={this.tagData()}
            value={item.tag || ''}
            onSelect={this.conditionItemTagChange.bind(this, index, itemIndex)}
            style={{width:'100%'}}
            options={{
              placeholder: 'Select or create tag',
              tags: true,
              createTag: function (params) {
                const fixed = fixTag(params.term);
                if (!fixed) {
                  return null;
                }
                return {
                  id: fixed,
                  text: fixed,
                };
              }
            }}
          />
        </div>
      );
    }

    if (item.type === 'in_list' || item.type === 'not_in_list') {
      if (!listOptions.length) {
        return <p className="help-block">Create a contact list before configuring this condition.</p>;
      }
      return (
        <SelectLabel
          id="list_id"
          label="Contact list"
          obj={item}
          onChange={this.conditionItemChange.bind(this, index, itemIndex)}
          options={listOptions}
          emptyVal="Select list"
        />
      );
    }

    if (item.type === 'opened_email' || item.type === 'clicked_email') {
      if (!emailOptions.length) {
        return <p className="help-block">Create an automation email before configuring this condition.</p>;
      }
      return (
        <div>
          <SelectLabel
            id="automation_email_id"
            label="Automation email"
            obj={item}
            onChange={this.conditionItemChange.bind(this, index, itemIndex)}
            options={emailOptions}
            emptyVal="Select email"
          />
          {
            item.type === 'clicked_email' ?
              <div>
                <label className="control-label" htmlFor="click_match">Click match</label>
                <FormControl
                  id="click_match"
                  componentClass="select"
                  value={clickMatch}
                  onChange={this.conditionItemChange.bind(this, index, itemIndex)}
                >
                  <option value="any">Any link</option>
                  <option value="url_exact">Specific URL</option>
                  <option value="url_prefix">URL starts with</option>
                </FormControl>
                {
                  clickMatch !== 'any' ?
                    <div className="space-top-sm">
                      <label className="control-label" htmlFor="discovered_link_url">Discovered links</label>
                      {
                        item.automation_email_id && this.state.emailLinksLoading[item.automation_email_id] ?
                          <p className="help-block">Loading discovered links...</p>
                        :
                          null
                      }
                      {
                        item.automation_email_id && this.state.emailLinksError[item.automation_email_id] ?
                          <p className="help-block text-danger">{this.state.emailLinksError[item.automation_email_id]}</p>
                        :
                          null
                      }
                      <FormControl
                        id="discovered_link_url"
                        componentClass="select"
                        value={selectedDiscoveredLink ? item.link_url || '' : ''}
                        onChange={event => {
                          if (event.target.value) {
                            this.conditionItemChange(index, itemIndex, {
                              target: {id: 'link_url', value: event.target.value},
                            });
                          }
                        }}
                        disabled={!discoveredLinks.length}
                      >
                        <option value="">
                          {discoveredLinks.length ? 'Select discovered URL' : 'No links discovered'}
                        </option>
                        {
                          _.map(discoveredLinks, link => (
                            <option key={link.normalized_url + '-' + link.tracked} value={link.normalized_url}>
                              {link.display_url || link.normalized_url}
                              {link.occurrence_count > 1 ? ' (' + link.occurrence_count + ')' : ''}
                              {link.tracked === false ? ' - untracked' : ''}
                            </option>
                          ))
                        }
                      </FormControl>
                      <label className="control-label" htmlFor="link_url">URL</label>
                      <FormControl
                        id="link_url"
                        type="text"
                        value={item.link_url || ''}
                        onChange={this.conditionItemChange.bind(this, index, itemIndex)}
                        placeholder="https://example.com/page"
                      />
                    </div>
                  :
                    null
                }
              </div>
            :
              null
          }
        </div>
      );
    }

    return <p className="help-block text-danger">Unsupported condition type</p>;
  }

  renderNodeDetails(node, index) {
    return (
      <div>
        <div style={{maxWidth: '320px', marginBottom: '14px'}}>
          <div className="text-muted" style={{fontSize: '11px', textTransform: 'uppercase', marginBottom: '6px'}}>Label</div>
          <FormControl
            id="label"
            value={node.label}
            onChange={this.nodeChange.bind(this, index)}
            required={true}
          />
        </div>
        {this.renderNodeConfig(node, index)}
      </div>
    );
  }

  renderAddNodeDropdown(id, title, afterIndex) {
    const hasEmails = (this.props.emails || []).length;
    const hasLists = (this.props.lists || []).length;
    const menuItems = automationAddNodeMenuItems(hasEmails, hasLists);
    return (
      <DropdownButton
        id={id}
        title={title}
      >
        {
          _.map(menuItems, item => (
            <MenuItem
              key={item.type}
              onClick={this.addNode.bind(this, item.type, afterIndex)}
              disabled={!!item.disabled}
            >
              {item.label}
            </MenuItem>
          ))
        }
      </DropdownButton>
    );
  }

  renderNodeCard(node, index, nodes) {
    const expanded = !!this.state.expandedNodeIds[node.id];
    const summary = this.nodeSummary(node);
    const summaryWarning = automationNodeSummaryWarning(summary);
    return (
      <div
        key={node.id}
        style={{
          border: '1px solid #dfe5ef',
          borderRadius: '6px',
          marginTop: index === 0 ? '20px' : '14px',
          background: '#fff',
          boxShadow: '0 1px 2px rgba(18, 32, 58, 0.04)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            padding: '14px 16px',
            flexWrap: 'wrap',
            borderBottom: expanded ? '1px solid #eef1f5' : '0',
            background: '#fbfcfe',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              minWidth: '240px',
              flex: '1 1 420px',
            }}
          >
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '19px',
                background: '#edf3ff',
                color: '#3f77ff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
                flex: '0 0 auto',
              }}
            >
              {index + 1}
            </div>
            <div style={{minWidth: 0}}>
              <div
                className="text-muted"
                style={{
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  marginBottom: '3px',
                }}
              >
                Step {index + 1} {this.props.renderNodeContactCount(node, {compact: true})}
              </div>
              <h4 style={{margin: 0, lineHeight: '1.45'}}>
                <span
                  style={{
                    display: 'inline-block',
                    padding: '4px 9px',
                    borderRadius: '4px',
                    background: summaryWarning ? '#f8eeee' : '#eef2f8',
                    color: summaryWarning ? '#a94442' : undefined,
                    fontWeight: 600,
                    fontSize: '13px',
                    lineHeight: '20px',
                  }}
                >
                  {summary}
                </span>
              </h4>
            </div>
          </div>
          <div
            className="last-cell"
            style={{
              display: 'flex',
              gap: '6px',
              flexWrap: 'wrap',
              justifyContent: 'flex-end',
              alignItems: 'center',
            }}
          >
              {this.renderAddNodeDropdown('automation-node-insert-dropdown-' + node.id, 'Insert', index)}
              <Button
                bsSize="small"
                disabled={index === 0}
                onClick={this.moveNode.bind(this, index, -1)}
                title="Move up"
              >
                Up
              </Button>
              <Button
                bsSize="small"
                disabled={index === nodes.length - 1}
                onClick={this.moveNode.bind(this, index, 1)}
                title="Move down"
              >
                Down
              </Button>
              <Button bsSize="small" onClick={this.deleteNode.bind(this, index)}>Delete</Button>
              <Button
                bsSize="small"
                onClick={this.toggleNodeDetails.bind(this, node)}
              >
                {expanded ? 'Hide details' : 'Edit details'}
              </Button>
          </div>
        </div>
        {
          expanded ?
            <div
              style={{
                borderTop: '1px solid #eef1f5',
                padding: '16px',
                background: '#fbfcfe',
              }}
            >
              {this.renderNodeDetails(node, index)}
            </div>
          :
            null
        }
      </div>
    );
  }

  renderPreviewConnection(connection) {
    const target = connection.target || {};
    const isGoTo = connection.kind === 'go_to';
    const isBranch = connection.kind === 'branch';
    return (
      <div
        key={connection.label + '-' + (target.id || 'missing')}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          flexWrap: 'wrap',
          marginTop: '8px',
        }}
      >
        <span
          style={{
            display: 'inline-block',
            minWidth: '48px',
            padding: '3px 8px',
            borderRadius: '12px',
            background: connection.label === 'No' ? '#fff1f1' : connection.label === 'Yes' ? '#eefaf1' : isGoTo ? '#fff7e6' : '#eef2f8',
            color: connection.label === 'No' ? '#a94442' : connection.label === 'Yes' ? '#2f7d46' : isGoTo ? '#8a5a00' : '#46566d',
            fontWeight: 700,
            fontSize: '12px',
            textAlign: 'center',
          }}
        >
          {connection.label}
        </span>
        <span
          style={{
            display: 'inline-block',
            padding: '5px 9px',
            borderRadius: '4px',
            background: target.missing ? '#f8eeee' : '#f6f8fb',
            color: target.missing ? '#a94442' : '#334155',
            border: (isGoTo && !target.missing ? '1px dashed #d79a25' : '1px solid ' + (target.missing ? '#ebcccc' : '#dfe5ef')),
            fontSize: '13px',
          }}
        >
          {isGoTo && !target.missing ? 'Go to Step ' + target.step : target.label + (target.type_label ? ' (' + target.type_label + ')' : '')}
        </span>
        {
          isBranch && !target.missing ?
            <span className="text-muted" style={{fontSize: '12px'}}>branch target</span>
          :
            null
        }
      </div>
    );
  }

  renderPreviewConnectionPanel(item, options) {
    const opts = options || {};
    if (item.type === 'go_to') {
      return null;
    }
    if (item.nested_branch_stop) {
      return (
        <div
          style={{
            marginTop: '12px',
            padding: '10px 12px',
            borderRadius: '6px',
            background: '#fffaf0',
            border: '1px dashed #d79a25',
            color: '#8a5a00',
            fontSize: '13px',
            fontWeight: 600,
          }}
        >
          Nested branch not expanded in this preview.
        </div>
      );
    }

    if (!item.connections.length) {
      if (!item.terminal_label) {
        return null;
      }
      return (
        <div
          style={{
            marginTop: '12px',
            paddingLeft: '46px',
            color: '#6b7280',
            fontSize: '13px',
            fontWeight: 600,
          }}
        >
          {item.terminal_label}
        </div>
      );
    }

    if (_.every(item.connections, connection => connection.kind === 'branch')) {
      if (opts.suppressBranchPanel) {
        return null;
      }
      return (
        <div
          style={{
            marginTop: '14px',
            padding: '12px',
            borderRadius: '6px',
            background: '#f8fafc',
            border: '1px solid #e5ebf3',
          }}
        >
          <div className="text-muted" style={{fontSize: '11px', textTransform: 'uppercase', marginBottom: '8px'}}>
            Branches
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: '10px',
            }}
          >
            {
              _.map(item.connections, connection => (
                <div
                  key={connection.label}
                  style={{
                    border: '1px solid ' + (connection.target.missing ? '#ebcccc' : '#dfe5ef'),
                    borderRadius: '6px',
                    padding: '8px 10px',
                    background: connection.target.missing ? '#fffafa' : '#fff',
                  }}
                >
                  {this.renderPreviewConnection(connection)}
                </div>
              ))
            }
          </div>
        </div>
      );
    }

    if (_.every(item.connections, connection => connection.kind === 'go_to')) {
      return (
        <div
          style={{
            marginTop: '14px',
            padding: '12px',
            borderRadius: '6px',
            background: '#fffaf0',
            border: '1px dashed #d79a25',
          }}
        >
          <div className="text-muted" style={{fontSize: '11px', textTransform: 'uppercase', marginBottom: '6px'}}>
            Jump
          </div>
          {_.map(item.connections, connection => this.renderPreviewConnection(connection))}
        </div>
      );
    }

    return (
      <div style={{marginTop: '12px', paddingLeft: '46px'}}>
        {_.map(item.connections, connection => this.renderPreviewConnection(connection))}
      </div>
    );
  }

  renderPreviewNodeCard(item, options) {
    const opts = options || {};
    const inlineSummary = automationWorkflowPreviewSummaryInline(item.type);
    return (
      <div
        style={{
          border: '1px solid ' + (item.warning ? '#ebcccc' : '#dfe5ef'),
          borderRadius: '6px',
          background: item.warning ? '#fffafa' : '#fff',
          boxShadow: '0 1px 2px rgba(18, 32, 58, 0.04)',
          padding: '14px 16px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '12px',
              flex: '1 1 360px',
              minWidth: 0,
            }}
          >
            <div
              style={{
                width: '34px',
                height: '34px',
                borderRadius: '17px',
                background: item.warning ? '#f8eeee' : '#edf3ff',
                color: item.warning ? '#a94442' : '#3f77ff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
                flex: '0 0 auto',
              }}
            >
              {item.step}
            </div>
            <div style={{minWidth: 0}}>
              <div
                className="text-muted"
                style={{
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  marginBottom: '5px',
                }}
              >
                Step {item.step}
              </div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  flexWrap: 'wrap',
                  marginBottom: inlineSummary ? 0 : '6px',
                }}
              >
                <span
                  style={{
                    display: 'inline-block',
                    padding: '3px 8px',
                    borderRadius: '4px',
                    background: '#eef2f8',
                    color: '#334155',
                    fontSize: '12px',
                    fontWeight: 700,
                  }}
                >
                  {item.type_label}
                </span>
                {
                  inlineSummary && item.summary ?
                    <span
                      style={{
                        color: item.warning ? '#a94442' : '#1f2937',
                        fontWeight: 600,
                        lineHeight: '1.45',
                        wordBreak: 'break-word',
                      }}
                    >
                      {item.summary}
                    </span>
                  :
                    null
                }
              </div>
              {
                !inlineSummary && item.summary ?
                  <div
                    style={{
                      color: item.warning ? '#a94442' : '#1f2937',
                      fontWeight: 600,
                      lineHeight: '1.45',
                      wordBreak: 'break-word',
                    }}
                  >
                    {item.summary}
                  </div>
                :
                  null
              }
            </div>
          </div>
        </div>
        {this.renderPreviewConnectionPanel(item, opts)}
      </div>
    );
  }

  renderPreviewMissingBlock(block) {
    const target = block.target || {};
    return (
      <div
        style={{
          border: '1px solid #ebcccc',
          borderRadius: '6px',
          background: '#fffafa',
          color: '#a94442',
          padding: '12px 14px',
          fontWeight: 600,
        }}
      >
        {target.label || 'Target missing'}
      </div>
    );
  }

  renderPreviewReferenceBlock(block) {
    const target = block.target || {};
    return (
      <div
        style={{
          border: '1px dashed #d79a25',
          borderRadius: '6px',
          background: block.warning ? '#fffafa' : '#fffaf0',
          color: block.warning ? '#a94442' : '#8a5a00',
          padding: '12px 14px',
          fontWeight: 600,
        }}
      >
        {block.label || 'Continues at'} {target.label}{target.type_label ? ' (' + target.type_label + ')' : ''}
      </div>
    );
  }

  previewBlockContinues(block) {
    if (!block || block.kind !== 'node') {
      return false;
    }
    const item = block.item || {};
    return item.type !== 'exit' &&
      item.type !== 'go_to' &&
      !automationBranchNode(item.type) &&
      !item.terminal_label;
  }

  renderPreviewBlock(block, index, blocks, options) {
    const opts = options || {};
    let rendered = null;
    if (block.kind === 'node') {
      rendered = this.renderPreviewNodeCard(block.item, opts);
    } else if (block.kind === 'missing') {
      rendered = this.renderPreviewMissingBlock(block);
    } else {
      rendered = this.renderPreviewReferenceBlock(block);
    }

    return (
      <div key={(block.item || block.target || {}).id || block.kind + '-' + index}>
        {rendered}
        {
          index < blocks.length - 1 && this.previewBlockContinues(block) ?
            <div
              aria-hidden="true"
              style={{
                width: '2px',
                height: '18px',
                background: '#dfe5ef',
                marginLeft: '33px',
              }}
            />
          :
            null
        }
      </div>
    );
  }

  renderPreviewBranchLanes(branch) {
    if (!branch) {
      return null;
    }
    const connectorColor = '#cfd8e6';

    return (
      <div
        style={{
          marginTop: '0',
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: 'relative',
            height: '62px',
            margin: '0 14px',
          }}
        >
          <div
            style={{
              position: 'absolute',
              left: '50%',
              top: 0,
              width: '2px',
              height: '22px',
              marginLeft: '-1px',
              background: connectorColor,
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: '25%',
              right: '25%',
              top: '22px',
              height: '2px',
              background: connectorColor,
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: '25%',
              top: '22px',
              width: '2px',
              height: '28px',
              marginLeft: '-1px',
              background: '#cce8d4',
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: '75%',
              top: '22px',
              width: '2px',
              height: '28px',
              marginLeft: '-1px',
              background: '#ebcccc',
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: '25%',
              top: '34px',
              transform: 'translateX(-50%)',
              padding: '3px 9px',
              borderRadius: '12px',
              background: '#eefaf1',
              color: '#2f7d46',
              fontWeight: 700,
              fontSize: '12px',
            }}
          >
            Yes
          </div>
          <div
            style={{
              position: 'absolute',
              left: '75%',
              top: '34px',
              transform: 'translateX(-50%)',
              padding: '3px 9px',
              borderRadius: '12px',
              background: '#fff1f1',
              color: '#a94442',
              fontWeight: 700,
              fontSize: '12px',
            }}
          >
            No
          </div>
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '14px',
          }}
        >
          {
            _.map(branch.lanes, lane => (
              <div
                key={lane.label}
                style={{
                  minWidth: 0,
                  padding: '0',
                }}
              >
                <div
                  aria-hidden="true"
                  style={{
                    display: 'flex',
                    justifyContent: 'center',
                    height: '18px',
                  }}
                >
                  <div
                    style={{
                      width: '2px',
                      height: '18px',
                      background: lane.label === 'No' ? '#ebcccc' : '#cce8d4',
                    }}
                  />
                </div>
                {
                  lane.blocks.length ?
                    _.map(lane.blocks, (block, index) => this.renderPreviewBlock(block, index, lane.blocks, {suppressBranchPanel: false}))
                  :
                    this.renderPreviewMissingBlock({
                      kind: 'missing',
                      target: {
                        label: 'Target missing',
                      },
                    })
                }
              </div>
            ))
          }
        </div>
      </div>
    );
  }

  renderWorkflowPreview(nodes) {
    const flow = automationWorkflowPreviewFlow(nodes, {
      emails: this.props.emails || [],
      lists: this.props.lists || [],
    });

    return (
      <div style={{marginTop: '18px'}}>
        <div className="help-block" style={{marginBottom: '12px'}}>
          Read-only preview of the draft workflow. Edit nodes in the list view.
        </div>
        {_.map(flow.main, (block, index) => this.renderPreviewBlock(block, index, flow.main, {suppressBranchPanel: !!flow.branch && block.item === flow.branch.item}))}
        {this.renderPreviewBranchLanes(flow.branch)}
      </div>
    );
  }

  render() {
    const nodes = this.props.nodes || [];
    const workflowView = this.state.workflowView || 'edit';
    return (
      <EDFormBox space>
        <div className="flex-items space-between" style={{alignItems: 'center', gap: '12px', flexWrap: 'wrap'}}>
          <h4>Draft Workflow</h4>
          <div style={{display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap'}}>
            <ButtonGroup>
              <Button
                bsSize="small"
                active={workflowView === 'edit'}
                onClick={this.showWorkflowView.bind(this, 'edit')}
              >
                Edit list
              </Button>
              <Button
                bsSize="small"
                active={workflowView === 'preview'}
                onClick={this.showWorkflowView.bind(this, 'preview')}
              >
                Visual preview
              </Button>
            </ButtonGroup>
            {workflowView === 'edit' ? this.renderAddNodeDropdown('automation-node-create-dropdown', 'Add Node') : null}
          </div>
        </div>
        {
          (this.props.emails || []).length ?
            null
          :
            <p className="help-block">Create an automation email before adding a send email node.</p>
        }
        {
          (this.props.lists || []).length ?
            null
          :
            <p className="help-block">Create a contact list before adding list action nodes.</p>
        }
        {
          nodes.length ?
            workflowView === 'preview' ?
              this.renderWorkflowPreview(nodes)
            :
              <div>
                {_.map(nodes, (node, index) => this.renderNodeCard(node, index, nodes))}
              </div>
          :
            <div className="text-center space-top-sm">
              <h4>This draft does not have any nodes yet.</h4>
            </div>
        }
      </EDFormBox>
    );
  }
}

export default AutomationWorkflowEditor;
