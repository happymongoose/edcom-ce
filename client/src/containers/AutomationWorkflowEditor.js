import React, { Component } from "react";
import axios from "axios";
import { Button, ButtonGroup, DropdownButton, FormControl, MenuItem, Modal } from "react-bootstrap";
import _ from "underscore";
import moment from 'moment';
import shortid from "shortid";
import update from "immutability-helper";
import { SelectLabel } from "../components/FormControls";
import { EDFormBox } from "../components/EDDOM";
import getvalue from "../utils/getvalue";
import AutomationListField, { automationListSelectionError, automationLists, withAutomationLists, automationListsError } from "./AutomationListField";
import AutomationTargetField, { automationTargetOptions, automationTargetError, automationTargetSummary } from './AutomationTargetField';
import AutomationEmailField, { automationEmailSelectionError } from "./AutomationEmailField";
import AutomationTagsField, {automationTags, automationTagsError, withAutomationTags} from './AutomationTagsField';
import AutomationTagField, { automationTagError } from "./AutomationTagField";
import AutomationWaitFields, { automationWaitError, withAutomationWait } from "./AutomationWaitFields";
import automationPendingRemovals from "./automationPendingRemovals";
import AutomationGoToConnections from './AutomationGoToConnections';
import AutomationViewport from './AutomationViewport';
import {fallsThrough, targetFields, incomingTargets, uniqueNode, insertOnPath, removeStep, structureError, branchFallsIntoSibling, movableNode, moveOnPath, movePlacement, deleteCondition, retargetGoTo} from './automationStructure';

export function automationNodeTypeLabel(type) {
  if (type === 'remove_automation') return 'Remove from another automation';
  if (type === 'enrol_automation') return 'Enrol in another automation';
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
    {type: 'add_tag', label: 'Add tag'},
    {type: 'add_to_list', label: 'Add to list', disabled: !hasLists},
    {type: 'enrol_automation', label: 'Enrol in another automation'},
    {type: 'exit', label: 'Exit automation'},
    {type: 'go_to', label: 'Go to'},
    {type: 'if_conditions', label: 'If conditions'},
    {type: 'remove_automation', label: 'Remove from another automation'},
    {type: 'remove_from_list', label: 'Remove from list', disabled: !hasLists},
    {type: 'remove_tag', label: 'Remove tag'},
    {type: 'send_email', label: 'Send email', disabled: !hasEmails},
    {type: 'wait_duration', label: 'Wait'},
  ], item => item.label.toLowerCase());
}

export function automationConditionItemTypeLabel(type) {
  if (type === 'has_tag') {
    return 'Has any of these tags';
  }
  if (type === 'missing_tag') {
    return 'Has none of these tags';
  }
  if (['opened_email', 'not_opened_email'].includes(type)) {
    return type === 'not_opened_email' ? 'Did not open email' : 'Opened email';
  }
  if (['clicked_email', 'not_clicked_email'].includes(type)) {
    return type === 'not_clicked_email' ? 'Did not click link in email' : 'Clicked link in email';
  }
  if (type === 'in_list') {
    return 'Is in any of these lists';
  }
  if (type === 'not_in_list') {
    return 'Not in any of these lists';
  }
  return 'Unsupported condition';
}

export function createAutomationConditionItem(type, options) {
  const opts = options || {};
  const emails = opts.emails || [];
  if (['opened_email', 'not_opened_email'].includes(type)) {
    return {type: type, automation_email_id: emails.length ? emails[0].id : ''};
  }
  if (['clicked_email', 'not_clicked_email'].includes(type)) {
    return {
      type: type,
      automation_email_id: emails.length ? emails[0].id : '',
      click_match: 'any',
      link_url: '',
    };
  }
  if (type === 'has_tag' || type === 'missing_tag') return {type, tags: []};
  if (type === 'in_list' || type === 'not_in_list') return {type, list_ids: []};
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
    return 'has any of these tags: ' + ((item.tags || [item.tag]).filter(Boolean).join(', ') || 'No tags selected');
  }
  if (item.type === 'missing_tag') {
    return 'has none of these tags: ' + ((item.tags || [item.tag]).filter(Boolean).join(', ') || 'No tags selected');
  }
  if (['opened_email', 'not_opened_email'].includes(item.type)) {
    return (item.type === 'not_opened_email' ? 'did not open ' : 'opened ') + (item.automation_email_id ? (optionName(emailOptions, item.automation_email_id) || 'Selected email not found') : 'No email selected');
  }
  if (['clicked_email', 'not_clicked_email'].includes(item.type)) {
    const clickMatch = automationClickMatchValue(item);
    let clickSummary = 'any link';
    if (clickMatch === 'url_exact') {
      clickSummary = 'exact URL ' + (item.link_url || 'No URL entered');
    } else if (clickMatch === 'url_prefix') {
      clickSummary = 'URL starts with ' + (item.link_url || 'No URL entered');
    }
    return (item.type === 'not_clicked_email' ? 'did not click ' : 'clicked ') + clickSummary + ' in ' + (item.automation_email_id ? (optionName(emailOptions, item.automation_email_id) || 'Selected email not found') : 'No email selected');
  }
  if (item.type === 'in_list') {
    return 'is in any of these lists: ' + ((item.list_ids || [item.list_id]).filter(Boolean).map(id => optionName(listOptions, id) || 'Selected list not found').join(', ') || 'No lists selected');
  }
  if (item.type === 'not_in_list') {
    return 'not in any of these lists: ' + ((item.list_ids || [item.list_id]).filter(Boolean).map(id => optionName(listOptions, id) || 'Selected list not found').join(', ') || 'No lists selected');
  }
  return 'Unsupported condition';
}

export function automationNodeSummary(node, options) {
  const opts = options || {};
  const nodes = opts.nodes || [];
  const emailOptions = automationEmailOptions(opts.emails || []);
  const listOptions = automationListOptions(opts.lists || []);

  if (['enrol_automation', 'remove_automation'].includes(node.type)) {
    return automationNodeTypeLabel(node.type) + ': ' + automationTargetSummary(node.automation_id, automationTargetOptions(opts.automations, opts.automationId, node.type));
  }
  if (node.type === 'send_email') {
    if (!node.automation_email_id) {
      return 'No email selected';
    }
    return 'Send email: ' + (optionName(emailOptions, node.automation_email_id) || 'Selected email not found');
  }
  if (node.type === 'add_tag') {
    return automationTags(node).filter(Boolean).length ? (automationTags(node).length > 1 ? 'Add tags: ' : 'Add tag: ') + automationTags(node).join(', ') : 'No tag selected';
  }
  if (node.type === 'remove_tag') {
    return automationTags(node).filter(Boolean).length ? (automationTags(node).length > 1 ? 'Remove tags: ' : 'Remove tag: ') + automationTags(node).join(', ') : 'No tag selected';
  }
  if (node.type === 'add_to_list' || node.type === 'remove_from_list') {
    const ids = automationLists(node).filter(Boolean);
    if (!ids.length) return 'No list selected';
    return (node.type === 'add_to_list' ? 'Add to ' : 'Remove from ') + (ids.length > 1 ? 'lists: ' : 'list: ') +
      ids.map(id => optionName(listOptions, id) || 'Selected list not found').join(', ');
  }
  if (node.type === 'wait_duration') {
    return node.wait_until !== undefined ? 'Wait until: ' + (node.wait_until ? moment(node.wait_until).format('LLL') : 'Choose date and time') : 'Wait: ' + durationSummary(node.duration || {});
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
    summary.indexOf('No automation selected') !== -1 ||
    summary.indexOf('No conditions configured') !== -1 ||
    summary.indexOf('No URL entered') !== -1 ||
    summary.indexOf('Selected email not found') !== -1 ||
    summary.indexOf('Selected list not found') !== -1 ||
    summary.indexOf('Selected automation unavailable') !== -1 ||
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
      contact_count: _.isFunction(opts.nodeContactCount) ? opts.nodeContactCount(node) : null,
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

  if (['enrol_automation', 'remove_automation'].includes(node.type)) {
    return automationTargetSummary(node.automation_id, automationTargetOptions(opts.automations, opts.automationId, node.type));
  }
  if (node.type === 'send_email') {
    if (!node.automation_email_id) {
      return 'No email selected';
    }
    const email = _.findWhere(opts.emails || [], {id: node.automation_email_id});
    return email ? (email.name || email.subject || 'Untitled email') : 'Selected email not found';
  }
  if (node.type === 'add_tag' || node.type === 'remove_tag') {
    return automationTags(node).filter(Boolean).join(', ') || 'No tag selected';
  }
  if (node.type === 'add_to_list' || node.type === 'remove_from_list') {
    return automationLists(node).filter(Boolean).map(id => optionName(listOptions, id) || 'Selected list not found').join(', ') || 'No list selected';
  }
  if (node.type === 'wait_duration') {
    return node.wait_until !== undefined ? (node.wait_until ? moment(node.wait_until).format('LLL') : 'Choose date and time') : durationSummary(node.duration || {});
  }
  if (node.type === 'if_has_tag' || node.type === 'if_missing_tag') {
    return node.draft_tag || 'No tag selected';
  }
  if (node.type === 'if_opened_email') {
    return node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected';
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
      (node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected');
  }
  if (node.type === 'if_conditions') {
    const condition = node.condition || {};
    const items = condition.items || [];
    const mode = condition.mode === 'any' ? 'Any' : 'All';
    if (!items.length) {
      return 'No conditions configured';
    }
    if (items.length === 1) {
      return conditionItemSummary(items[0], opts);
    }
    const preview = _.map(items.slice(0, 2), item => conditionItemSummary(item, opts)).join(' | ');
    return mode + ' of ' + items.length + ' conditions: ' +
      preview + (items.length > 2 ? ' | ...' : '');
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
    contact_count: _.isFunction(opts.nodeContactCount) ? opts.nodeContactCount(node) : null,
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

function automationWorkflowPreviewBranch(workflowNodes, item, options, visited, depth) {
  return {item, lanes: ['Yes', 'No'].map(label => ({label,
    blocks: automationWorkflowPreviewPath(workflowNodes, item.node[label === 'Yes' ? 'yes_node_id' : 'no_node_id'],
      options, visited, depth),
  }))};
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

    if (currentVisited[nodeId] || opts.rendered.has(nodeId)) {
      blocks.push(automationWorkflowPreviewReferenceBlock(workflowNodes, nodeId, 'Continues at'));
      return blocks;
    }

    const node = workflowNodes[nodeIndex];
    opts.rendered.add(nodeId);
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
      blocks[blocks.length - 1].branch = automationWorkflowPreviewBranch(workflowNodes, item, opts, currentVisited, currentDepth + 1);
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
    rendered: new Set(),
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
    opts.rendered.add(nodeId);
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
    label: type === 'remove_automation' ? 'Remove from another automation' : type === 'enrol_automation' ? 'Enrol in another automation' : type === 'add_tag' ? 'Add tag' : type === 'remove_tag' ? 'Remove tag' : type === 'add_to_list' ? 'Add to list' : type === 'remove_from_list' ? 'Remove from list' : type === 'wait_duration' ? 'Wait' : type === 'if_has_tag' ? 'If contact has tag' : type === 'if_missing_tag' ? 'If contact does not have tag' : type === 'if_opened_email' ? 'If opened email' : type === 'if_clicked_email' ? 'If clicked email' : type === 'if_conditions' ? 'If conditions' : type === 'go_to' ? 'Go to' : type === 'send_email' ? 'Send email' : 'Exit automation',
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
  if (['enrol_automation', 'remove_automation'].includes(type)) node.automation_id = '';
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

export function automationPreviewPathWidth(blocks) {
  return Math.max(340, ...(blocks || []).map(block => automationPreviewBranchWidth(block.branch)));
}

export function automationPreviewBranchWidth(branch) {
  return branch ? branch.lanes.reduce((sum, lane) => sum + automationPreviewPathWidth(lane.blocks), 0) + 32 : 340;
}

class AutomationWorkflowEditor extends Component {
  state = {
    expandedNodeIds: {},
    emailLinksById: {},
    emailLinksLoading: {},
    emailLinksError: {},
    workflowView: 'preview',
    nodeEdit: null,
    nodeEditError: '',
    nodeSaving: false,
    structureEdit: null,
    structureEditError: '',
    moving: null,
    goToSelection: null,
    goToError: '',
  }

  componentDidMount() {
    document.addEventListener('keydown', this.cancelGoToOnEscape);
    this.loadVisibleClickedEmailLinks();
  }

  componentWillUnmount() {
    document.removeEventListener('keydown', this.cancelGoToOnEscape);
  }

  cancelGoToOnEscape = event => {
    if (event.keyCode === 27 && this.state.goToSelection) this.closeGoToSelection();
  }

  openGoToSelection = (id, trigger) => {
    const original = JSON.parse(JSON.stringify(this.props.nodes || []));
    try {
      const node = uniqueNode(original, id);
      if (node.type !== 'go_to') return;
      this.goToTrigger = trigger;
      this.setState({goToSelection: {id, original, nodes: original, target: node.target_node_id}, goToError: '', moving: null}, () => {
        if (this.goToPrompt) this.goToPrompt.focus();
      });
    } catch (error) {this.setState({structureEditError: error.message});}
  }

  closeGoToSelection = () => {
    this.setState({goToSelection: null, goToError: ''}, () => {
      if (this.goToTrigger && document.body.contains(this.goToTrigger)) this.goToTrigger.focus();
    });
  }

  goToSelectionError(nodes = this.props.nodes || []) {
    const selection = this.state.goToSelection;
    if (!selection) return '';
    if (!_.isEqual(nodes, selection.original)) return 'The workflow changed. Cancel and select the destination again.';
    try {
      if (!selection.target) return 'Select an available destination node.';
      retargetGoTo(selection.nodes, selection.id, selection.target);
      return '';
    } catch (error) {return error.message;}
  }

  confirmGoToSelection = () => {
    if (!this.state.goToSelection || this.goToSaving) return;
    const error = this.goToSelectionError();
    if (error) {this.setState({goToError: error}); return;}
    const selection = this.state.goToSelection;
    let committed = false;
    this.goToSaving = true;
    this.props.update({draft: {$apply: draft => {
      if (this.goToSelectionError(draft.nodes)) return draft;
      const plan = retargetGoTo(selection.nodes, selection.id, selection.target);
      const moves = {...(draft.moves || {})};
      plan.removed.forEach(node => {delete moves[node.id];});
      committed = true;
      return {...draft, nodes: plan.nodes, ...(draft.moves ? {moves} : {})};
    }}}, () => {
      this.goToSaving = false;
      if (committed) this.closeGoToSelection();
      else this.setState({goToError: 'The workflow changed. Cancel and select the destination again.'});
    });
  }

  renderGoToChoice(node) {
    const selection = this.state.goToSelection;
    if (!selection || node.id === selection.id) return null;
    const nodes = selection.nodes;
    const available = nodes.filter(item => item.id === node.id).length === 1;
    return <label className="automation-go-to-choice" title={available ? 'Choose destination' : 'Ambiguous node ID'}>
      <input type="checkbox" checked={selection.target === node.id} disabled={!available}
        aria-label={'Go to ' + node.label} data-target-node-id={node.id}
        onChange={() => this.setState({goToSelection: {...selection, target: selection.target === node.id ? '' : node.id}, goToError: ''})} />
      <span className="sr-only">Go to {node.label}</span>
    </label>;
  }

  componentDidUpdate() {
    this.loadVisibleClickedEmailLinks();
  }

  loadVisibleClickedEmailLinks() {
    _.each(this.props.nodes || [], node => {
      if (
        (this.state.expandedNodeIds[node.id] || this.props.configurationOnly === node.id) &&
        node.type === 'if_clicked_email' &&
        automationClickMatchValue(node) !== 'any' &&
        node.automation_email_id
      ) {
        this.loadAutomationEmailLinks(node.automation_email_id);
      }
      if ((this.state.expandedNodeIds[node.id] || this.props.configurationOnly === node.id) && node.type === 'if_conditions') {
        _.each(((node.condition || {}).items || []), item => {
          if (
            ['clicked_email', 'not_clicked_email'].includes(item.type) &&
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

  nodeTagChange = (index, tag) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            $apply: node => ['add_tag', 'remove_tag'].includes(node.type) ? withAutomationTags(node, tag) : {...node, draft_tag: tag},
          },
        },
      },
    });
  }

  nodeDurationChange = (index, unit, rawValue) => {
    const value = parseInt(rawValue, 10);
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            duration: {
              [unit]: {$set: this.props.configurationOnly ? rawValue : isNaN(value) ? 0 : value},
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

  conditionSelectionsChange = (index, itemIndex, item, singular, plural, values) => {
    const next = {...item};
    delete next[singular];
    next[plural] = values;
    this.props.update({draft: {nodes: {[index]: {condition: {items: {[itemIndex]: {$set: next}}}}}}});
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
    const node = this.props.nodes[index];
    if (automationBranchNode(node.type)) {
      this.openStructureEditor('delete', node.id);
      return;
    }
    this.props.update({
      draft: {
        ...((this.props.moveDecisions || {})[node.id] ? {moves: {$unset: [node.id]}} : {}),
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
    const draftTags = _.flatten(nodes.filter(node => ['add_tag', 'remove_tag', 'if_has_tag', 'if_missing_tag'].includes(node.type)).map(automationTags));
    const conditionTags = _.flatten(_.map(nodes, node => _.map(((node.condition || {}).items || []), item => item.tags || [item.tag || ''])));
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
      automations: this.props.automations || [], automationId: this.props.automationId,
    });
  }

  openNodeEditor = (id, type) => {
    if (!_.contains(['wait_duration', 'add_tag', 'remove_tag', 'send_email', 'add_to_list', 'remove_from_list', 'enrol_automation', 'remove_automation'], type)) return;
    const matches = (this.props.nodes || []).filter(node => node.id === id);
    const original = matches.length === 1 && matches[0].type === type ?
      JSON.parse(JSON.stringify(matches[0])) : null;
    this.setState({
      nodeEdit: {
        id: id, type: type, original: original,
        duration: type === 'wait_duration' ? {...((original || {}).duration || {days: 0, hours: 0, minutes: 5})} : undefined,
        wait_until: (original || {}).wait_until,
        list_ids: _.contains(['add_to_list', 'remove_from_list'], type) ? automationLists(original || {}) : undefined,
        automation_id: ['enrol_automation', 'remove_automation'].includes(type) ? (original || {}).automation_id || '' : undefined,
        automation_email_id: type === 'send_email' ? (original || {}).automation_email_id || '' : undefined,
        tags: _.contains(['add_tag', 'remove_tag'], type) ? automationTags(original || {}) : undefined,
      },
      nodeEditError: '',
    });
  }

  closeNodeEditor = () => {
    this.setState({nodeEdit: null, nodeEditError: ''});
  }

  waitDurationChange = (unit, value) => {
    this.setState(state => ({
      nodeEdit: {...state.nodeEdit, duration: {...state.nodeEdit.duration, [unit]: value}},
      nodeEditError: '',
    }));
  }

  modalTagChange = tag => {
    this.setState(state => ({nodeEdit: {...state.nodeEdit, tags: tag}, nodeEditError: ''}));
  }

  modalEmailChange = event => {
    const value = getvalue(event);
    this.setState(state => ({nodeEdit: {...state.nodeEdit, automation_email_id: value}, nodeEditError: ''}));
  }

  modalListChange = value => {
    this.setState(state => ({nodeEdit: {...state.nodeEdit, list_ids: value}, nodeEditError: ''}));
  }

  targetAutomationOptions(type) {
    return automationTargetOptions(this.props.automations, this.props.automationId, type);
  }

  nodeFieldError(edit) {
    if (['enrol_automation', 'remove_automation'].includes(edit.type)) return automationTargetError(edit.automation_id, this.targetAutomationOptions(edit.type));
    if (_.contains(['add_to_list', 'remove_from_list'], edit.type)) {
      return automationListsError(edit.list_ids, automationListOptions(this.props.lists || []));
    }
    if (edit.type === 'send_email') {
      return automationEmailSelectionError(edit.automation_email_id, automationEmailOptions(this.props.emails || []));
    }
    return edit.type === 'wait_duration' ? automationWaitError(edit.duration, edit.wait_until) : automationTagsError(edit.tags);
  }

  nodeTargetError(edit, nodes) {
    const label = automationNodeTypeLabel(edit.type);
    const matches = (nodes || []).filter(node => node.id === edit.id);
    if (matches.length !== 1 || !edit.original || matches[0].type !== edit.type) {
      return 'This ' + label + ' step is missing, changed type, or has a duplicate ID. Close this dialog and check the list editor.';
    }
    if (!_.isEqual(matches[0], edit.original)) {
      return 'This ' + label + ' step changed while the dialog was open. Close and reopen it to edit the current values.';
    }
    return '';
  }

  saveNodeEditor = () => {
    const edit = this.state.nodeEdit;
    if (!edit || this.nodeCommitPending) {
      return;
    }
    const error = this.nodeTargetError(edit, this.props.nodes) || this.nodeFieldError(edit);
    if (error) {
      this.setState({nodeEditError: this.nodeTargetError(edit, this.props.nodes)});
      return;
    }
    const patch = ['enrol_automation', 'remove_automation'].includes(edit.type) ? {automation_id: edit.automation_id} : edit.type === 'wait_duration' ? withAutomationWait({}, edit) : _.contains(['add_to_list', 'remove_from_list'], edit.type) ? withAutomationLists({}, edit.list_ids) : edit.type === 'send_email' ? {automation_email_id: edit.automation_email_id} : withAutomationTags({}, edit.tags);
    this.nodeCommitPending = true;
    this.setState({nodeSaving: true});
    let committed = false;
    this.props.update({draft: {nodes: {$apply: nodes => {
      // Resolve against the canonical array at commit time, never a captured index.
      if (this.nodeTargetError(edit, nodes) || this.nodeFieldError(edit)) {
        return nodes;
      }
      committed = true;
      return nodes.map(node => node.id === edit.id ? (['add_tag', 'remove_tag'].includes(edit.type) ? withAutomationTags(node, edit.tags) : ['add_to_list', 'remove_from_list'].includes(edit.type) ? withAutomationLists(node, edit.list_ids) : edit.type === 'wait_duration' ? withAutomationWait(node, edit) : {...node, ...patch}) : node);
    }}}}, () => {
      this.nodeCommitPending = false;
      this.setState({
        nodeSaving: false,
        nodeEdit: committed ? null : edit,
        nodeEditError: committed ? '' : 'This step changed. Close and reopen the dialog before saving.',
      });
    });
  }

  renderNodeEditor() {
    const edit = this.state.nodeEdit;
    const isWait = !edit || edit.type === 'wait_duration';
    const label = edit ? automationNodeTypeLabel(edit.type) : 'Wait';
    const fieldError = edit && this.nodeFieldError(edit);
    const targetError = edit && (this.nodeTargetError(edit, this.props.nodes) || this.state.nodeEditError);
    const isAutomationTarget = edit && ['enrol_automation', 'remove_automation'].includes(edit.type);
    const isEmail = edit && edit.type === 'send_email';
    const isList = edit && _.contains(['add_to_list', 'remove_from_list'], edit.type);
    const fieldId = isAutomationTarget ? 'automation-target-modal' : isList ? 'automation-list-modal' : isWait ? 'automation-wait-modal' : isEmail ? 'automation-email-modal' : 'automation-tag-modal';
    return (
      <Modal show={!!edit} onHide={this.closeNodeEditor} aria-labelledby="automation-node-title">
        <Modal.Header closeButton>
          <Modal.Title id="automation-node-title">Edit {label} step</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {edit && <div>
            <p>{(edit.original || {}).label || label}</p>
            {targetError && <p className="help-block text-danger" role="alert">{targetError}</p>}
            {isAutomationTarget ? <AutomationTargetField
              action={edit.type} id={fieldId} value={edit.automation_id} options={this.targetAutomationOptions(edit.type)} invalid={!!fieldError}
              onChange={event => {
                const value = getvalue(event);
                this.setState({nodeEdit: {...edit, automation_id: value}, nodeEditError: ''});
              }}
            /> : isWait ? <AutomationWaitFields
              duration={edit.duration}
              waitUntil={edit.wait_until}
              onModeChange={mode => this.setState({nodeEdit: {...edit, wait_until: mode === 'until' ? '' : undefined}})}
              onDateChange={value => this.setState({nodeEdit: {...edit, wait_until: value}})}
              idPrefix={fieldId}
              invalid={!!fieldError}
              onChange={this.waitDurationChange}
            /> : isList ? <AutomationListField
              id={fieldId}
              multiple
              value={edit.list_ids}
              options={automationListOptions(this.props.lists || [])}
              onChange={this.modalListChange}
              invalid={!!fieldError}
            /> : isEmail ? <AutomationEmailField
              id={fieldId}
              value={edit.automation_email_id}
              options={automationEmailOptions(this.props.emails || [])}
              onChange={this.modalEmailChange}
              invalid={!!fieldError}
            /> : <AutomationTagsField
              id={fieldId}
              value={edit.tags}
              data={this.tagData()}
              onChange={this.modalTagChange}
              invalid={!!fieldError}
              inModal
            />}
            {fieldError && <p id={fieldId + '-error'} className="help-block text-danger" role="alert">{fieldError}</p>}
            <p className="help-block">Save applies this configuration to the draft. Use the page Save button to persist the automation.</p>
          </div>}
        </Modal.Body>
        <Modal.Footer>
          <Button type="button" onClick={this.closeNodeEditor}>Cancel</Button>
          <Button type="button" bsStyle="primary" disabled={!!fieldError || !!targetError || this.state.nodeSaving} onClick={this.saveNodeEditor}>Save</Button>
        </Modal.Footer>
      </Modal>
    );
  }

  renderNodeConfig(node, index) {
    if (['enrol_automation', 'remove_automation'].includes(node.type)) {
      return <AutomationTargetField action={node.type} id="automation_id" value={node.automation_id}
        options={this.targetAutomationOptions(node.type)} onChange={this.nodeTargetChange.bind(this, index)} />;
    }
    if (node.type === 'add_tag' || node.type === 'remove_tag') {
      return <AutomationTagsField id={'node-tag-' + node.id} inModal={!!this.props.configurationOnly}
        data={this.tagData()} value={automationTags(node)} onChange={this.nodeTagChange.bind(this, index)} />;
    }
    if (node.type === 'if_has_tag' || node.type === 'if_missing_tag') {
      return (
        <div style={{minWidth: '220px'}}>
          <AutomationTagField
            id={'node-tag-' + node.id}
            inModal={!!this.props.configurationOnly}
            data={this.tagData()}
            value={node.draft_tag || ''}
            onChange={this.nodeTagChange.bind(this, index)}
          />
          <span className="help-block">Draft configuration. The complete workflow is validated when you publish.</span>
          {
            !this.props.hideBranchTargets && (node.type === 'if_has_tag' || node.type === 'if_missing_tag') ?
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
      return (
        <AutomationWaitFields
          duration={node.duration}
          waitUntil={node.wait_until}
          onModeChange={mode => this.props.update({draft: {nodes: {[index]: {$apply: current => withAutomationWait(current, mode === 'until' ? {wait_until: ''} : {duration: {days: 0, hours: 0, minutes: 5}})}}}})}
          onDateChange={value => this.props.update({draft: {nodes: {[index]: {$apply: current => withAutomationWait(current, {wait_until: value})}}}})}
          idPrefix={'wait-' + node.id}
          onChange={this.nodeDurationChange.bind(this, index)}
        />
      );
    }

    if (node.type === 'go_to') {
      if (this.props.hideBranchTargets) return <p className="help-block">After saving this step, click its card to choose a destination visually.</p>;
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
      return (
        <AutomationEmailField
          id="automation_email_id"
          value={node.automation_email_id}
          options={automationEmailOptions(this.props.emails || [])}
          onChange={this.nodeTargetChange.bind(this, index)}
        />
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
          {!this.props.hideBranchTargets && <div><SelectLabel
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
          </div>}
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
          {!this.props.hideBranchTargets && <div className="space-top-sm">
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
          </div>}
        </div>
      );
    }

    if (node.type === 'add_to_list' || node.type === 'remove_from_list') {
      return (
        <AutomationListField
          id="list_id"
          multiple
          value={automationLists(node)}
          options={automationListOptions(this.props.lists || [])}
          onChange={ids => this.props.update({draft: {nodes: {[index]: {$set: withAutomationLists(node, ids)}}}})}
        />
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
              {['has_tag', 'missing_tag', 'in_list', 'not_in_list', 'opened_email', 'not_opened_email', 'clicked_email', 'not_clicked_email']
                .map(type => ({type, label: automationConditionItemTypeLabel(type)}))
                .sort((a, b) => a.label.localeCompare(b.label))
                .map(option => <option key={option.type} value={option.type}>{option.label}</option>)}
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
      return <AutomationTagsField id={'condition-tags-' + index + '-' + itemIndex}
        inModal={!!this.props.configurationOnly} data={this.tagData()}
        value={item.tags || [item.tag || '']}
        onChange={tags => this.conditionSelectionsChange(index, itemIndex, item, 'tag', 'tags', tags)} />;
    }
    if (item.type === 'in_list' || item.type === 'not_in_list') {
      const selected = item.list_ids || (item.list_id ? [item.list_id] : []);
      return <div>
        <label className="control-label">{automationConditionItemTypeLabel(item.type)}</label>
        <SelectLabel id="condition-list-picker" label="Add a list" obj={{'condition-list-picker': ''}}
          options={listOptions.filter(option => !selected.includes(option.id))} emptyVal="Select list"
          onChange={event => {const id = getvalue(event); if (id && !selected.includes(id)) this.conditionSelectionsChange(index, itemIndex, item, 'list_id', 'list_ids', selected.concat(id));}} />
        <ul className="list-inline color_tag" style={{paddingTop: '12px'}}>{selected.map(id => <li key={id}>
          <button type="button" className="gray_tag" aria-label={'Remove list ' + (optionName(listOptions, id) || id)}
            onClick={() => this.conditionSelectionsChange(index, itemIndex, item, 'list_id', 'list_ids', selected.filter(value => value !== id))}>
            {optionName(listOptions, id) || 'Selected list not found'}
          </button>
        </li>)}</ul>
        {!selected.length && <p className="help-block">Select at least one list.</p>}
      </div>;
    }
    if (['opened_email', 'not_opened_email'].includes(item.type) || ['clicked_email', 'not_clicked_email'].includes(item.type)) {
      return (
        <div>
          <p className="help-block">Checks tracked activity in the current enrolment only, at the moment this step runs. Add a Wait step first to allow time to respond.</p>
          <AutomationEmailField
            id="automation_email_id"
            value={item.automation_email_id}
            onChange={this.conditionItemChange.bind(this, index, itemIndex)}
            options={emailOptions}
          />
          {
            ['clicked_email', 'not_clicked_email'].includes(item.type) ?
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
            autoFocus={!!this.props.configurationOnly}
            value={node.label}
            onChange={this.nodeChange.bind(this, index)}
            required={true}
          />
        </div>
        {this.renderNodeConfig(node, index)}
      </div>
    );
  }

  openStructureEditor = (mode, id, field) => {
    if (mode === 'add') this.structureTrigger = document.activeElement;
    try {
      const original = JSON.parse(JSON.stringify(this.props.nodes || []));
      if (id) uniqueNode(original, id);
      const draftOnly = !(this.props.publishedNodes || []).some(node => node.id === id);
      const selected = original.find(node => node.id === id);
      let replacement = '';
      if (mode === 'delete' && draftOnly && selected && fallsThrough(selected)) {
        const next = original[original.indexOf(selected) + 1];
        if (next) replacement = next.id;
      }
      this.structureSaving = false;
      this.setState({structureEdit: {mode, id, field, original, nodes: original,
        originalMoves: JSON.parse(JSON.stringify(this.props.moveDecisions || {})),
        replacement, draftOnly, routing: false, contactAction: '', deleteChoice: ''}, structureEditError: ''});
    } catch (error) {
      this.setState({structureEditError: error.message});
    }
  }

  startMoving = (id, event) => {
    if (event && event.dataTransfer) {
      event.dataTransfer.setData('text/plain', id);
      event.dataTransfer.effectAllowed = 'move';
      this.suppressNodeClickUntil = Date.now() + 500;
    }
    this.setState({moving: {id, original: JSON.parse(JSON.stringify(this.props.nodes || []))}, structureEditError: ''});
  }

  dropStep = (id, field, event) => {
    if (event) {event.preventDefault(); event.stopPropagation();}
    const moving = this.state.moving;
    if (!moving) return;
    try {
      if (!_.isEqual(this.props.nodes, moving.original)) throw new Error('The workflow changed while moving. Try again.');
      const result = moveOnPath(moving.original, moving.id, {id, field},
        type => createAutomationNode(type, {emails: this.props.emails, lists: this.props.lists}));
      this.structureSaving = false;
      this.setState({moving: null, structureEditError: '', structureEdit: {mode: 'move', id: moving.id,
        original: moving.original, originalMoves: JSON.parse(JSON.stringify(this.props.moveDecisions || {})),
        nodes: result.nodes, routing: result.routing, contactAction: ''}});
    } catch (error) {this.setState({moving: null, structureEditError: error.message});}
  }

  chooseStructureType = event => {
    const edit = this.state.structureEdit;
    try {
      const added = insertOnPath(edit.original, {id: edit.id, field: edit.field}, event.target.value,
        type => createAutomationNode(type, {emails: this.props.emails, lists: this.props.lists}));
      if (event.target.value === 'go_to') {
        this.goToTrigger = this.structureTrigger;
        this.setState({structureEdit: null, goToSelection: {id: added.id, original: edit.original,
          nodes: added.nodes, target: '', adding: true}, goToError: '', structureEditError: ''}, () => {
          if (this.goToPrompt) this.goToPrompt.focus();
        });
        return;
      }
      this.setState({structureEdit: {...edit, ...added, sourceId: edit.id, selected: true}, structureEditError: ''});
    } catch (error) {
      this.setState({structureEditError: error.message});
    }
  }

  structureFieldError(edit) {
    if (edit.mode === 'delete') return automationBranchNode(uniqueNode(edit.original, edit.id).type) && !edit.deletePlan ? 'Choose which paths to keep.' : '';
    if (edit.mode === 'move') return !(this.props.publishedNodes || []).some(node => node.id === edit.id) || edit.contactAction ? '' : 'Choose what happens to contacts at this step when published.';
    if (edit.mode === 'add' && !edit.selected) return 'Choose a step type.';
    const node = edit.nodes.find(item => item.id === edit.id);
    if (!node || !(node.label || '').trim()) return 'Enter a step label.';
    if (['enrol_automation', 'remove_automation'].includes(node.type)) return automationTargetError(node.automation_id, this.targetAutomationOptions(node.type));
    if (node.type === 'wait_duration') return automationWaitError(node.duration, node.wait_until);
    if (['add_tag', 'remove_tag'].includes(node.type)) return automationTagsError(automationTags(node));
    if (_.contains(['if_has_tag', 'if_missing_tag'], node.type)) {
      const error = automationTagError(node.draft_tag);
      if (error) return error;
    }
    if (_.contains(['send_email', 'if_opened_email', 'if_clicked_email'], node.type)) {
      const error = automationEmailSelectionError(node.automation_email_id, automationEmailOptions(this.props.emails || []));
      if (error) return error;
    }
    if (_.contains(['add_to_list', 'remove_from_list'], node.type)) {
      const error = automationListsError(automationLists(node), automationListOptions(this.props.lists || []));
      if (error) return error;
    }
    if (node.type === 'if_clicked_email' && automationClickMatchValue(node) !== 'any' && !(node.link_url || '').trim()) return 'Enter the clicked URL.';
    if (node.type === 'if_conditions') {
      const items = (node.condition || {}).items || [];
      if (!items.length) return 'Add at least one condition.';
      for (const item of items) {
        let error = '';
        if (item.type === 'has_tag' || item.type === 'missing_tag') error = automationTagsError(item.tags || [item.tag || '']);
        if (item.type === 'in_list' || item.type === 'not_in_list') {
          const ids = item.list_ids || (item.list_id ? [item.list_id] : []);
          error = !ids.length ? 'Select at least one list.' : ids.length > 100 ? 'Select up to 100 lists.' : new Set(ids).size !== ids.length ? 'Select each list only once.' :
            ids.map(id => automationListSelectionError(id, automationListOptions(this.props.lists || []))).find(Boolean);
        }
        if (_.contains(['opened_email', 'not_opened_email', 'clicked_email', 'not_clicked_email'], item.type)) error = automationEmailSelectionError(item.automation_email_id, automationEmailOptions(this.props.emails || []));
        if (error) return error;
        if (['clicked_email', 'not_clicked_email'].includes(item.type) && automationClickMatchValue(item) !== 'any' && !(item.link_url || '').trim()) return 'Enter the clicked URL.';
      }
    }
    if (targetFields(node).some(field => !edit.nodes.some(target => target.id === node[field] && target.id !== node.id))) {
      return 'Choose an existing, different step for each target.';
    }
    return '';
  }

  saveStructureEditor = () => {
    if (this.structureSaving || !this.state.structureEdit) return;
    const edit = this.state.structureEdit;
    try {
      const fieldError = this.structureFieldError(edit);
      if (fieldError) throw new Error(fieldError);
      let next = edit.mode === 'delete' ? (edit.deletePlan ? edit.deletePlan.nodes : removeStep(edit.original, edit.id, edit.replacement)) : edit.nodes;
      next = next.map(node => node.type === 'wait_duration' && node.id === edit.id ?
        withAutomationWait(node, node) : node);
      const error = structureError(next);
      if (error) throw new Error(error);
      if (!_.isEqual(this.props.nodes, edit.original)) throw new Error('The workflow changed while this dialog was open. Close and reopen it.');
      this.structureSaving = true;
      let committed = false;
      this.props.update({draft: {$apply: current => {
        // Structural operations depend on order as well as IDs. Resolve again
        // inside the canonical update, and reject all concurrent changes.
        if (!_.isEqual(current.nodes, edit.original) || !_.isEqual(current.moves || {}, edit.originalMoves)) return current;
        const moves = {...(current.moves || {})};
        if (edit.mode === 'move' && (this.props.publishedNodes || []).some(node => node.id === edit.id)) {
          moves[edit.id] = {action: edit.contactAction, published_revision: this.props.publishedRevision,
            placement: movePlacement(next, edit.id)};
        }
        Object.keys(moves).forEach(id => {if (!next.some(node => node.id === id)) delete moves[id];});
        committed = true;
        return {...current, nodes: next, ...(Object.keys(moves).length || current.moves ? {moves} : {})};
      }}}, () => {
        this.structureSaving = false;
        this.setState(committed ? {structureEdit: null, structureEditError: ''} :
          {structureEditError: 'The workflow changed while saving. Close and reopen the dialog.'});
      });
    } catch (error) {
      this.structureSaving = false;
      this.setState({structureEditError: error.message});
    }
  }

  closeStructureEditor = () => {
    if (!this.structureSaving) this.setState({structureEdit: null, structureEditError: ''});
  }

  chooseConditionDeletion = event => {
    const edit = this.state.structureEdit;
    const deleteChoice = event.target.value;
    try {
      const deletePlan = deleteCondition(edit.original, edit.id, deleteChoice,
        type => createAutomationNode(type, {emails: this.props.emails, lists: this.props.lists}));
      this.setState({structureEdit: {...edit, deleteChoice, deletePlan}, structureEditError: ''});
    } catch (error) {
      this.setState({structureEdit: {...edit, deleteChoice, deletePlan: null}, structureEditError: error.message});
    }
  }

  renderStructureEditor() {
    const edit = this.state.structureEdit;
    if (!edit) return this.state.structureEditError ? <p role="alert">{this.state.structureEditError}</p> : null;
    const node = edit.nodes.find(item => item.id === edit.id);
    const deletingCondition = edit.mode === 'delete' && automationBranchNode(node.type);
    const incoming = edit.mode === 'delete' && !deletingCondition ? incomingTargets(edit.original, edit.id) : [];
    if (edit.mode === 'add' && !edit.selected) {
      return <Modal show className="automation-node-drawer" onHide={this.closeStructureEditor} aria-labelledby="structure-picker-title">
        <Modal.Header closeButton><Modal.Title id="structure-picker-title">Add a step</Modal.Title></Modal.Header>
        <Modal.Body>
          <div className="automation-node-options">
            {automationAddNodeMenuItems((this.props.emails || []).length, (this.props.lists || []).length).filter(item => item.type !== 'exit').map(item =>
              <Button key={item.type} data-node-type={item.type} disabled={!!item.disabled} onClick={() => this.chooseStructureType({target: {value: item.type}})}>
                {item.label}<i className="fa fa-angle-right" aria-hidden="true" />
              </Button>)}
          </div>
          {this.state.structureEditError && <p className="text-danger" role="alert">{this.state.structureEditError}</p>}
        </Modal.Body>
        <Modal.Footer><Button onClick={this.closeStructureEditor}>Cancel</Button></Modal.Footer>
      </Modal>;
    }
    return <Modal show onHide={this.closeStructureEditor} bsSize="large" aria-labelledby="structure-edit-title">
      <Modal.Header closeButton><Modal.Title id="structure-edit-title">
        {edit.mode === 'delete' ? 'Delete step' : edit.mode === 'add' ? 'Add step' : edit.mode === 'move' ? 'Move step' : 'Edit step'}
      </Modal.Title></Modal.Header>
      <Modal.Body>
        {edit.routing && <p className="help-block">A visible Go to step preserves the other paths into the shared destination.</p>}
        {edit.mode === 'move' && !(this.props.publishedNodes || []).some(item => item.id === edit.id) && <p>Move “{node.label}”? This draft-only step has no live contacts.</p>}
        {edit.mode === 'move' && (this.props.publishedNodes || []).some(item => item.id === edit.id) && <div>
          <p>Move “{node.label}”? Choose what happens to contacts at this live step when you publish.</p>
          <label htmlFor="move-contact-action">Contacts at this step</label>
          <FormControl id="move-contact-action" componentClass="select" value={edit.contactAction}
            onChange={event => this.setState({structureEdit: {...edit, contactAction: event.target.value}, structureEditError: ''})}>
            <option value="">Choose an option</option>
            <option value="follow">Follow the step to its new position</option>
            <option value="exit">Exit the automation when published</option>
          </FormControl>
          <p className="help-block">Nothing changes live until publication. This choice applies to everyone at this step then, even if the count changes. Following preserves wait progress and pause state. Moving again asks you to choose again.</p>
          {!(this.props.publishedNodes || []).some(item => item.id === edit.id) && <p className="help-block">This draft-only step has no live contacts.</p>}
        </div>}
        {edit.selected && automationBranchNode(node.type) && <p className="help-block">
          New Yes and No paths end independently. An existing non-ending continuation is preserved through Go to steps. Use Edit list to inspect target references.
        </p>}
        {(edit.mode === 'edit' || edit.selected) && <AutomationWorkflowEditor
          {...this.props} nodes={edit.nodes} configurationOnly={edit.id}
          hideBranchTargets={this.state.workflowView === 'preview'}
          update={spec => this.setState({structureEdit: {...edit, nodes: update({draft: {nodes: edit.nodes}}, spec).draft.nodes}, structureEditError: ''})}
        />}
        {edit.mode === 'delete' && <div>
          {deletingCondition ? <div>
            <p>Delete “{node.label}”? Choose which path to keep. Shared continuations and steps referenced from elsewhere are preserved.</p>
            <label htmlFor="condition-delete-choice">Paths after deletion</label>
            <FormControl componentClass="select" id="condition-delete-choice" value={edit.deleteChoice} onChange={this.chooseConditionDeletion}>
              <option value="">Choose what to keep</option>
              <option value="yes">Keep the Yes path</option>
              <option value="no">Keep the No path</option>
              <option value="both">Delete both paths</option>
            </FormControl>
            {edit.deletePlan && <div><p>{edit.deletePlan.removed.length} steps will be removed:</p>
              <ul>{edit.deletePlan.removed.map(item => <li key={item.id}>{item.label} (step {edit.original.findIndex(original => original.id === item.id) + 1})</li>)}</ul>
              <p>Other steps remain. {edit.deleteChoice === 'both' ? 'This path will end here.' : 'Incoming paths will continue to the kept branch.'}</p>
            </div>}
          </div> : <div>
            <p>Delete “{node.label}” from the draft? Only this step is removed; downstream steps remain.</p>
            <p>Ordinary steps before it will continue to the next remaining draft step.</p>
          </div>}
          <p>{edit.draftOnly ? 'This step is new to the draft and has no live contacts.' : 'Live contacts stay at their published steps until you publish and review any required migration.'}</p>
          {incoming.length > 0 && !(edit.draftOnly && edit.replacement) && <div>
            <p>These incoming paths need an explicit replacement: {incoming.map(ref => ref.label + ' (' + ref.id + ', ' + ref.field + ')').join('; ')}.</p>
            <label htmlFor="delete-replacement">Replacement for incoming paths</label>
            <FormControl id="delete-replacement" componentClass="select" value={edit.replacement}
              onChange={event => this.setState({structureEdit: {...edit, replacement: event.target.value}, structureEditError: ''})}>
              <option value="">Choose a replacement step</option>
              {edit.original.filter(item => item.id !== edit.id).map((item) => <option key={item.id} value={item.id}>{item.label} ({item.id})</option>)}
            </FormControl>
          </div>}
        </div>}
        <p className="help-block">This changes the draft only. Publication validates the complete workflow.</p>
        {(edit.selected || edit.mode === 'edit') && this.structureFieldError(edit) && <p className="text-danger" role="alert">{this.structureFieldError(edit)}</p>}
        {this.state.structureEditError && <p className="text-danger" role="alert">{this.state.structureEditError}</p>}
      </Modal.Body>
      <Modal.Footer>
        <Button onClick={this.closeStructureEditor}>Cancel</Button>
        <Button bsStyle={edit.mode === 'delete' ? 'danger' : 'primary'}
          disabled={!!this.structureFieldError(edit) || (incoming.length > 0 && !edit.replacement)}
          onClick={this.saveStructureEditor}>{edit.mode === 'delete' ? 'Delete step' : 'Save step'}</Button>
      </Modal.Footer>
    </Modal>;
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

  renderPendingCard(record) {
    const node = record.node;
    return <aside key={node.id} className="automation-pending-removal" data-node-id={node.id}
      aria-label={'Pending removal: published step ' + record.publishedStep}
      style={{background: '#f4f5f6', border: '1px dashed #89939f', borderRadius: '6px',
        color: '#374151', padding: '14px 16px', margin: '12px 0', display: 'flex',
        alignItems: 'center', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap'}}>
      <div style={{flex: '1 1 240px', minWidth: 0}}>
        <div style={{display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap',
          fontSize: '11px', marginBottom: '3px'}}>
          <span>Published step {record.publishedStep} · {node.label || automationNodeTypeLabel(node.type)}</span>
          <span>({this.props.renderNodeContactCount(node, {pending: true, countOnly: true})})</span>
          <span className="label label-default">Pending removal</span>
        </div>
        <div style={{display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap'}}>
          <span style={{display: 'inline-block', padding: '4px 9px', borderRadius: '4px',
            background: '#e8ebef', fontWeight: 600, fontSize: '13px', lineHeight: '20px'}}>
            {automationNodeSummary(node, {nodes: this.props.publishedNodes || [],
              emails: this.props.emails || [], lists: this.props.lists || [],
              automations: this.props.automations || [], automationId: this.props.automationId})}
          </span>
          <span style={{fontSize: '12px', color: '#4b5563'}}>Still live until you publish.</span>
        </div>
      </div>
      {this.props.renderNodeContactCount(node, {pending: true, linkOnly: true})}
    </aside>;
  }

  renderPendingFallback(records) {
    if (!records.length) return null;
    return <section aria-label="Other pending removals" style={{borderTop: '1px solid #ddd', marginTop: '18px'}}>
      <h4>Pending removals — published position not shown here</h4>
      <p>These live steps are outside the draft path shown above.</p>
      {records.map(record => this.renderPendingCard(record))}
    </section>;
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
      const Terminal = _.contains(['wait_duration', 'add_tag', 'remove_tag', 'send_email', 'add_to_list', 'remove_from_list', 'enrol_automation', 'remove_automation'], item.type) ? 'span' : 'div';
      return (
        <Terminal
          style={{
            display: 'block',
            marginTop: '12px',
            paddingLeft: '46px',
            color: '#6b7280',
            fontSize: '13px',
            fontWeight: 600,
          }}
        >
          {item.terminal_label}
        </Terminal>
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
    const selection = this.state.goToSelection;
    const targetId = selection && selection.id === item.id ? selection.target : item.node.target_node_id;
    const summary = item.type === 'go_to' ? ((selection ? selection.nodes : this.props.nodes || []).find(node => node.id === targetId) || {}).label || 'Select destination' : item.summary;
    const inlineSummary = automationWorkflowPreviewSummaryInline(item.type);
    const compound = item.type === 'if_conditions';
    const structural = compound || item.type === 'go_to';
    const editable = structural || _.contains(['wait_duration', 'add_tag', 'remove_tag', 'send_email', 'add_to_list', 'remove_from_list', 'enrol_automation', 'remove_automation'], item.type);
    const editLabel = automationNodeTypeLabel(item.type);
    const Card = editable ? 'button' : 'div';
    const Content = editable ? 'span' : 'div';
    return (
      <div>
      <Card
        type={editable ? 'button' : undefined}
        className={editable ? (structural ? 'automation-condition-preview-node' : item.type === 'wait_duration' ? 'automation-wait-preview-node' : _.contains(['add_to_list', 'remove_from_list'], item.type) ? 'automation-list-preview-node' : ['enrol_automation', 'remove_automation'].includes(item.type) ? 'automation-target-preview-node' : item.type === 'send_email' ? 'automation-email-preview-node' : 'automation-tag-preview-node') : undefined}
        aria-label={editable ? 'Edit ' + editLabel + ' step ' + item.step + ': ' + item.summary : undefined}
        onClick={editable ? event => {
          if (this.state.goToSelection) return;
          if (Date.now() < (this.suppressNodeClickUntil || 0)) return;
          if (item.type === 'go_to') this.openGoToSelection(item.id, event.currentTarget);
          else if (structural) this.openStructureEditor('edit', item.id);
          else this.openNodeEditor(item.id, item.type);
        } : undefined}
        style={{
          width: editable ? '100%' : undefined,
          textAlign: editable ? 'left' : undefined,
          color: editable ? 'inherit' : undefined,
          font: editable ? 'inherit' : undefined,
          cursor: editable ? 'pointer' : undefined,
          border: '1px solid ' + (item.warning ? '#ebcccc' : '#dfe5ef'),
          borderRadius: '6px',
          background: item.warning ? '#fffafa' : '#fff',
          boxShadow: '0 1px 2px rgba(18, 32, 58, 0.04)',
          padding: '14px 80px 14px 16px',
        }}
      >
        <Content
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <Content
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '12px',
              flex: '1 1 360px',
              minWidth: 0,
            }}
          >
            <Content style={{minWidth: 0}}>
              <Content
                className="text-muted"
                style={{
                  display: 'block',
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  marginBottom: '5px',
                }}
              >
                {
                  item.contact_count !== null && item.contact_count !== undefined ?
                    <span style={{textTransform: 'none', fontWeight: 400}}>
                      {item.contact_count} live {item.contact_count === 1 ? 'contact' : 'contacts'}
                    </span>
                  :
                    null
                }
              </Content>
              <Content
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
                      {summary}
                    </span>
                  :
                    null
                }
              </Content>
              {
                !inlineSummary && item.summary ?
                  <Content
                    style={{
                      display: 'block',
                      color: item.warning ? '#a94442' : '#1f2937',
                      fontWeight: 600,
                      lineHeight: '1.45',
                      wordBreak: 'break-word',
                    }}
                  >
                    {summary}
                  </Content>
                :
                  null
              }
            </Content>
          </Content>
        </Content>
        {!structural && !item.terminal_label && this.renderPreviewConnectionPanel(item, opts)}
      </Card>
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
        {target.id && !target.missing && <Button bsSize="xsmall" style={{marginLeft: 8}}
          onClick={() => this.jumpToPreviewStep(target.id)}>Show step</Button>}
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
    if (block.kind === 'node' && block.item.type === 'exit') {
      rendered = <div>
        {this.renderGoToChoice(block.item.node)}
        {opts.detached && this.renderPathInsertion('Add before Exit step ' + block.item.step, block.item.id, 'before')}
        <div className="automation-path-end-label" data-preview-node-id={block.item.id} title={'Step ' + block.item.step + ': ' + block.item.node.label}>
          <i className="fa fa-ban" aria-hidden="true" /> Automation ends
          {block.item.contact_count !== null && block.item.contact_count !== undefined &&
            <span className="automation-end-count"> · {block.item.contact_count} live contacts</span>}
        </div>
      </div>;
    } else if (block.kind === 'node') {
      rendered = <div className="automation-visual-card" data-preview-node-id={block.item.id} draggable={!this.state.goToSelection && movableNode(block.item.node)}
        onDragStart={event => {if (movableNode(block.item.node)) this.startMoving(block.item.id, event);}}
        onDragEnd={() => {this.suppressNodeClickUntil = Date.now() + 300; this.setState({moving: null});}}>
        {this.renderPreviewNodeCard(block.item, {...opts, suppressBranchPanel: opts.suppressBranchPanel || !!block.branch})}
        {this.renderGoToChoice(block.item.node)}
        {!this.state.goToSelection && <div className="automation-visual-card-tools">
          {block.item.type === 'go_to' && <button type="button" className="automation-node-icon"
            aria-label={'Show destination of step ' + block.item.step} title="Show destination"
            onClick={() => this.jumpToPreviewStep(block.item.node.target_node_id)}><i className="fa fa-crosshairs" aria-hidden="true" /></button>}
          {movableNode(block.item.node) && <button type="button" className="automation-node-icon" aria-label={'Move step ' + block.item.step}
            title="Move step" onClick={() => this.startMoving(block.item.id)}><i className="fa fa-arrows" aria-hidden="true" /></button>}
          {(automationBranchNode(block.item.type) && block.item.type !== 'if_conditions') &&
            <button type="button" className="automation-node-icon" title={'Configure ' + block.item.type_label}
              onClick={() => this.openStructureEditor('edit', block.item.id)}><i className="fa fa-pencil" aria-hidden="true" /><span className="sr-only">Configure {block.item.type_label}</span></button>}
          <button type="button" className="automation-node-icon" aria-label={'Delete step ' + block.item.step} title="Delete step"
            onClick={() => this.openStructureEditor('delete', block.item.id)}><i className="fa fa-trash-o" aria-hidden="true" /></button>
        </div>}
        {!this.state.goToSelection && (this.props.moveDecisions || {})[block.item.id] && <button type="button" className="automation-move-decision"
          onClick={() => this.openStructureEditor('move', block.item.id)}>Review move decision</button>}
      </div>;
    } else if (block.kind === 'missing') {
      rendered = this.renderPreviewMissingBlock(block);
    } else {
      rendered = this.renderPreviewReferenceBlock(block);
    }

    const path = <div>
        {rendered}
        {block.branch && this.renderPreviewBranchLanes(block.branch, opts.pendingByBlock || new Map())}
        {block.kind === 'node' && <div>
          {fallsThrough(block.item.node) && this.renderPathInsertion('Add after step ' + block.item.step, block.item.id)}
          {fallsThrough(block.item.node) && block.item.terminal_label &&
            <div className="automation-path-end-label"><i className="fa fa-ban" aria-hidden="true" /> Automation ends</div>}
          {block.item.type === 'go_to' && this.renderPathInsertion('Add on Go to path of step ' + block.item.step, block.item.id, 'target_node_id', true)}
          {automationBranchNode(block.item.type) && !block.branch && !opts.suppressBranchPanel && ['Yes', 'No'].map(label =>
            <div key={label}>{label}{this.renderPathInsertion('Add on ' + label + ' path', block.item.id, label === 'Yes' ? 'yes_node_id' : 'no_node_id', true)}</div>)}
        </div>}
      </div>;
    return <div key={(block.item || block.target || {}).id || block.kind + '-' + index}>
      {opts.pending && opts.pending.length ?
        <div style={{display: 'flex', flexWrap: 'wrap', gap: '14px', alignItems: 'flex-start'}}>
          <div style={{flex: '1 1 280px', minWidth: 0}}>{path}</div>
          <div className="automation-pending-annotations" style={{flex: '0 1 300px'}}>
            <p className="help-block">Live steps near this published position · outside the draft path</p>
            {opts.pending.map(record => this.renderPendingCard(record))}
          </div>
        </div> : path}
    </div>;
  }

  renderPathInsertion(label, id, field, terminal = false) {
    if (this.state.goToSelection) return <div className="automation-path-insertion" aria-hidden="true" />;
    const moving = this.state.moving;
    return <div className={'automation-path-insertion' + (terminal ? ' automation-path-end' : '')}>
      <button type="button" className={moving ? 'automation-path-drop' : 'automation-path-add'} aria-label={moving ? 'Move here: ' + label : label} title={label}
        disabled={!!moving && moving.id === id}
        onDragOver={event => {if (moving && moving.id !== id) {event.preventDefault(); event.dataTransfer.dropEffect = 'move';}}}
        onDrop={event => this.dropStep(id, field, event)}
        onKeyDown={event => {if (event.key === 'Escape') this.setState({moving: null});}}
        onClick={() => moving ? this.dropStep(id, field) : this.openStructureEditor('add', id, field)}>
        <span aria-hidden="true">{moving ? 'Move here' : '+'}</span></button>
    </div>;
  }

  renderPreviewBranchLanes(branch, pendingByBlock) {
    if (!branch) {
      return null;
    }
    const connectorColor = '#cfd8e6';
    const widths = branch.lanes.map(lane => automationPreviewPathWidth(lane.blocks));
    const laneGridStyle = {
      display: 'grid',
      gridTemplateColumns: widths.map(width => width + 'px').join(' '),
      gap: '32px',
    };

    return (
      <div
        className="automation-branch-subtree"
        style={{
          marginTop: '0',
          width: automationPreviewBranchWidth(branch),
          marginLeft: 'auto',
          marginRight: 'auto',
        }}
      >
        <div
          style={{
            position: 'relative',
            margin: '0 0 0',
          }}
        >
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: '50%',
              top: 0,
              width: '2px',
              height: '31px',
              marginLeft: '-1px',
              background: connectorColor,
            }}
          />
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: widths[0] / 2,
              right: widths[1] / 2,
              top: '31px',
              height: '2px',
              background: connectorColor,
            }}
          />
          <div
            style={laneGridStyle}
          >
            {
              _.map(branch.lanes, lane => (
                <div
                  key={lane.label + '-connector'}
                  style={{
                    minWidth: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    paddingTop: '20px',
                  }}
                >
                  <div
                    style={{
                      position: 'relative',
                      zIndex: 1,
                      padding: '3px 9px',
                      borderRadius: '12px',
                      background: lane.label === 'No' ? '#fff1f1' : '#eefaf1',
                      color: lane.label === 'No' ? '#a94442' : '#2f7d46',
                      fontWeight: 700,
                      fontSize: '12px',
                    }}
                  >
                    {lane.label}
                  </div>
                  <div
                    aria-hidden="true"
                    style={{
                      width: '2px',
                      height: '20px',
                      background: connectorColor,
                    }}
                  />
                </div>
              ))
            }
          </div>
        </div>
        <div
          style={laneGridStyle}
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
                {this.renderPathInsertion('Add on ' + lane.label + ' path of step ' + branch.item.step, branch.item.id, lane.label === 'Yes' ? 'yes_node_id' : 'no_node_id')}
                {branchFallsIntoSibling(this.props.nodes || [], branch.item.node, lane.label === 'Yes' ? 'yes_node_id' : 'no_node_id') &&
                  <p className="text-warning" role="note">This saved path continues into the other branch by step order. Add an Exit at the end of this path to separate them.</p>}
                {
                  lane.blocks.length ?
                    _.map(lane.blocks, (block, index) => this.renderPreviewBlock(block, index, lane.blocks,
                      {suppressBranchPanel: false, pending: pendingByBlock.get(block), pendingByBlock}))
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

  jumpToPreviewStep = id => {
    const error = this.navigationViewport ? this.navigationViewport.jumpTo(id) : 'The preview is unavailable. Use Edit list.';
    if (error || this.state.navigationError) this.setState({navigationError: error});
  }

  renderWorkflowPreview(nodes, pending) {
    const flow = automationWorkflowPreviewFlow(nodes, {
      emails: this.props.emails || [],
      lists: this.props.lists || [],
      automations: this.props.automations || [], automationId: this.props.automationId,
      nodeContactCount: this.props.nodeContactCount,
    });

    // Attach once to a rendered anchor. Shared branch nodes can appear more
    // than once; annotations never become blocks or executable connections.
    const firstBlocks = new Map();
    const visit = blocks => blocks.forEach(block => {
      if (block.kind === 'node' && !firstBlocks.has(block.item.id)) firstBlocks.set(block.item.id, block);
      if (block.branch) block.branch.lanes.forEach(lane => visit(lane.blocks));
    });
    visit(flow.main);
    if (flow.branch) flow.branch.lanes.forEach(lane => visit(lane.blocks));
    const otherNodes = nodes.filter(node => !firstBlocks.has(node.id));
    const previewItems = new Map();
    firstBlocks.forEach((block, id) => previewItems.set(id, block.item));
    const previewItem = node => {
      if (!previewItems.has(node.id)) previewItems.set(node.id, automationWorkflowPreviewItemForNode(nodes, node, {
        emails: this.props.emails || [], lists: this.props.lists || [],
        automations: this.props.automations || [], automationId: this.props.automationId, nodeContactCount: this.props.nodeContactCount,
      }));
      return previewItems.get(node.id);
    };
    // Built only when the finder is used, cached for this immutable render.
    let navigationItems;
    const getNavigationItems = () => {
      if (navigationItems) return navigationItems;
      const counts = new Map();
      nodes.forEach(node => counts.set(node.id, (counts.get(node.id) || 0) + 1));
      const seen = new Set();
      navigationItems = [];
      nodes.forEach((node, index) => {
        if (seen.has(node.id)) return;
        seen.add(node.id);
        const item = previewItem(node);
        const ambiguous = typeof node.id !== 'string' || !node.id || counts.get(node.id) !== 1;
        const warning = ambiguous ? 'Duplicate or invalid step ID.' : this.structureFieldError({mode: 'edit', id: node.id, nodes}) || (item.warning ? item.summary : '');
        navigationItems.push({id: node.id, label: node.label || 'Untitled step', step: index + 1,
          type: item.type_label, summary: item.summary, count: item.contact_count, warning,
          ambiguous, detached: !firstBlocks.has(node.id)});
      });
      return navigationItems;
    };
    const pendingByBlock = new Map();
    const fallback = [];
    pending.forEach(record => {
      const block = firstBlocks.get(record.anchorId);
      if (!block) fallback.push(record);
      else pendingByBlock.set(block, (pendingByBlock.get(block) || []).concat(record));
    });

    return (
      <div style={{marginTop: '18px', paddingBottom: this.state.goToSelection ? '180px' : undefined}}>
        <div className="automation-workflow-visual-preview-narrow-message">
          Visual preview is available on wider screens. Use Edit list on this device.
          {pending.length > 0 && <div style={{marginTop: '8px'}}>
            {pending.length} pending {pending.length === 1 ? 'removal' : 'removals'} still live.{' '}
            <Button bsSize="small" onClick={this.showWorkflowView.bind(this, 'edit')}>View pending removals in Edit list</Button>
          </div>}
        </div>
        <div className="automation-workflow-visual-preview">
          <div className="help-block" style={{marginBottom: '12px'}}>
            Click a step to edit it, or use its pencil where shown. Add steps on the labelled path; shared continuations appear as references. Exit and Go to end a branch path. Scroll sideways to follow wider branches.
          </div>
          <p className="help-block">Hover over or focus a Go to step to trace its destination while scrolling. Press Escape or click elsewhere to clear the arrow.</p>
          {this.state.moving && <p role="status">Choose a drop box for this step. <Button bsSize="small" onClick={() => this.setState({moving: null})}>Cancel move</Button></p>}
          {this.state.navigationError && <p role="alert" className="text-danger">{this.state.navigationError}</p>}
          <AutomationViewport ref={element => {this.navigationViewport = element;}} getNavigationItems={getNavigationItems}
            width={Math.max(automationPreviewPathWidth(flow.main), automationPreviewBranchWidth(flow.branch))}>
          {scale => <AutomationGoToConnections scale={scale} nodes={nodes} disabled={!!this.state.goToSelection || !!this.state.moving}>
          {this.renderPathInsertion('Add before first step', nodes[0].id, 'entry')}
          {_.map(flow.main, (block, index) => this.renderPreviewBlock(block, index, flow.main,
            {suppressBranchPanel: !!flow.branch && block.item === flow.branch.item, pending: pendingByBlock.get(block)}))}
          {this.renderPreviewBranchLanes(flow.branch, pendingByBlock)}
          {otherNodes.length > 0 && <section aria-label="Other draft steps" style={{marginTop: '20px'}}>
            <h4>Other draft steps</h4>
            <p className="help-block">Steps outside the expanded preview, including unconnected steps and Go to destinations. No execution order is implied here.</p>
            {otherNodes.map(node => this.renderPreviewBlock({kind: 'node', item: previewItem(node)}, 0, [], {detached: true}))}
          </section>}
          </AutomationGoToConnections>}
          </AutomationViewport>
        </div>
        {this.renderPendingFallback(fallback)}
      </div>
    );
  }

  render() {
    const nodes = this.state.goToSelection ? this.state.goToSelection.nodes : this.props.nodes || [];
    let goToRemovals = [];
    if (this.state.goToSelection && !this.goToSelectionError()) {
      const selection = this.state.goToSelection;
      goToRemovals = retargetGoTo(selection.nodes, selection.id, selection.target).removed;
    }
    if (this.props.configurationOnly) {
      const index = nodes.findIndex(node => node.id === this.props.configurationOnly);
      return index < 0 ? null : this.renderNodeDetails(nodes[index], index);
    }
    const removedSteps = goToRemovals.filter(node => node.type !== 'exit');
    const removedEndings = goToRemovals.length - removedSteps.length;
    const pending = automationPendingRemovals(this.props.publishedNodes || [], nodes);
    const workflowView = this.state.workflowView || 'preview';
    return (
      <EDFormBox space>
        <div className="flex-items space-between" style={{alignItems: 'center', gap: '12px', flexWrap: 'wrap'}}>
          <h4>Draft Workflow</h4>
          <div style={{display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap'}}>
            <ButtonGroup>
              <Button
                bsSize="small"
                active={workflowView === 'edit'}
                disabled={!!this.state.goToSelection}
                onClick={this.showWorkflowView.bind(this, 'edit')}
              >
                Edit list
              </Button>
              <Button
                bsSize="small"
                active={workflowView === 'preview'}
                disabled={!!this.state.goToSelection}
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
              this.renderWorkflowPreview(nodes, pending)
            :
              <div>
                {_.map(nodes, (node, index) => <div key={node.id}>
                  {pending.filter(record => record.anchorId === node.id && record.side === 'before').map(record => this.renderPendingCard(record))}
                  {this.renderNodeCard(node, index, nodes)}
                  {pending.filter(record => record.anchorId === node.id && record.side === 'after').map(record => this.renderPendingCard(record))}
                </div>)}
              </div>
          :
            <div className="text-center space-top-sm">
              <h4>This draft does not have any nodes yet.</h4>
              {workflowView === 'preview' && this.renderPathInsertion('Add first step', undefined, undefined, true)}
            </div>
        }
        {workflowView !== 'preview' || !nodes.length ? this.renderPendingFallback(pending.filter(record => record.anchorId === null)) : null}
        {this.renderNodeEditor()}
        {this.renderStructureEditor()}
        {this.state.goToSelection && <div className="automation-go-to-prompt" role="region" aria-label="Select Go to destination"
          tabIndex="-1" ref={element => {this.goToPrompt = element;}}>
          <strong>Select which node to go to</strong>
          <p>Choose one checkbox. A contact returning to a previously visited step without an elapsed wait is held before the action repeats.</p>
          {goToRemovals.length > 0 && <div role="alert">
            {removedSteps.length > 0 && <div><strong>Confirming will remove {removedSteps.length} {removedSteps.length === 1 ? 'step' : 'steps'} from this draft path:</strong>
              <ul>{removedSteps.map(node => <li key={node.id}>{node.label} ({automationNodeTypeLabel(node.type)})</li>)}</ul></div>}
            {removedEndings > 0 && <p>This replaces the “Automation ends” {removedEndings === 1 ? 'ending' : 'endings'} on this path with a jump to your selected destination.</p>}
            <p>The destination and shared paths are kept. Live contacts stay at their published steps until you publish and resolve their destinations.</p>
          </div>}
          {(this.state.goToError || this.goToSelectionError()) && <p role="alert" className="text-danger">{this.state.goToError || this.goToSelectionError()}</p>}
          <Button type="button" onClick={this.closeGoToSelection}>Cancel</Button>{' '}
          <Button type="button" bsStyle="primary" disabled={!!this.goToSelectionError()} onClick={this.confirmGoToSelection}>Confirm</Button>
        </div>}
      </EDFormBox>
    );
  }
}

export default AutomationWorkflowEditor;
