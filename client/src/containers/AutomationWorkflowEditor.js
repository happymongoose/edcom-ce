import React, { Component } from "react";
import { Button, DropdownButton, FormControl, MenuItem } from "react-bootstrap";
import _ from "underscore";
import shortid from "shortid";
import Select2 from "react-select2-wrapper";
import { SelectLabel } from "../components/FormControls";
import { EDFormBox, EDTable, EDTableRow } from "../components/EDDOM";
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
  if (type === 'if_opened_email') {
    return 'If opened email';
  }
  if (type === 'if_clicked_email') {
    return 'If clicked email';
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

export function automationNodeSummary(node, options) {
  const opts = options || {};
  const nodes = opts.nodes || [];
  const emailOptions = automationEmailOptions(opts.emails || []);
  const listOptions = automationListOptions(opts.lists || []);

  if (node.type === 'send_email') {
    if (!node.automation_email_id) {
      return 'No email selected';
    }
    return 'Send: ' + (optionName(emailOptions, node.automation_email_id) || 'Selected email not found');
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
  if (node.type === 'if_opened_email') {
    return 'If opened: ' + (node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected') +
      ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
      ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
  }
  if (node.type === 'if_clicked_email') {
    return 'If clicked: ' + (node.automation_email_id ? (optionName(emailOptions, node.automation_email_id) || 'Selected email not found') : 'No email selected') +
      ' | Yes -> ' + targetSummary(nodes, node, node.yes_node_id) +
      ' | No -> ' + targetSummary(nodes, node, node.no_node_id);
  }
  if (node.type === 'go_to') {
    return 'Go to: ' + targetSummary(nodes, node, node.target_node_id);
  }
  return 'Exit automation';
}

export function createAutomationNode(type, options) {
  const opts = options || {};
  const emails = opts.emails || [];
  const lists = opts.lists || [];
  const generateId = opts.generateId || shortid.generate;
  const node = {
    id: generateId(),
    type: type,
    label: type === 'add_tag' ? 'Add tag' : type === 'remove_tag' ? 'Remove tag' : type === 'add_to_list' ? 'Add to list' : type === 'remove_from_list' ? 'Remove from list' : type === 'wait_duration' ? 'Wait' : type === 'if_has_tag' ? 'If contact has tag' : type === 'if_opened_email' ? 'If opened email' : type === 'if_clicked_email' ? 'If clicked email' : type === 'go_to' ? 'Go to' : type === 'send_email' ? 'Send email' : 'Exit automation',
  };

  if (type === 'add_tag' || type === 'remove_tag') {
    node.draft_tag = '';
  }
  if (type === 'if_has_tag') {
    node.draft_tag = '';
    node.yes_node_id = '';
    node.no_node_id = '';
  }
  if (type === 'if_opened_email' || type === 'if_clicked_email') {
    node.automation_email_id = emails.length ? emails[0].id : '';
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
    const draftTags = _.pluck(_.filter(nodes, node => _.contains(['add_tag', 'remove_tag', 'if_has_tag'], node.type) && node.draft_tag), 'draft_tag');
    return _.map(_.uniq(tags.concat(draftTags).concat(this.props.entryTags || [])), tag => ({id: tag, text: tag}));
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
    if (node.type === 'add_tag' || node.type === 'remove_tag' || node.type === 'if_has_tag') {
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
            node.type === 'if_has_tag' ?
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

  renderAddNodeDropdown(id, title, afterIndex) {
    const hasEmails = (this.props.emails || []).length;
    const hasLists = (this.props.lists || []).length;
    return (
      <DropdownButton
        id={id}
        title={title}
      >
        <MenuItem onClick={this.addNode.bind(this, 'add_tag', afterIndex)}>Add Tag Node</MenuItem>
        <MenuItem onClick={this.addNode.bind(this, 'remove_tag', afterIndex)}>Remove Tag Node</MenuItem>
        <MenuItem
          onClick={this.addNode.bind(this, 'add_to_list', afterIndex)}
          disabled={!hasLists}
        >
          Add To List Node
        </MenuItem>
        <MenuItem
          onClick={this.addNode.bind(this, 'remove_from_list', afterIndex)}
          disabled={!hasLists}
        >
          Remove From List Node
        </MenuItem>
        <MenuItem onClick={this.addNode.bind(this, 'wait_duration', afterIndex)}>Wait Duration Node</MenuItem>
        <MenuItem onClick={this.addNode.bind(this, 'if_has_tag', afterIndex)}>Condition Node</MenuItem>
        <MenuItem
          onClick={this.addNode.bind(this, 'if_opened_email', afterIndex)}
          disabled={!hasEmails}
        >
          If Opened Email Node
        </MenuItem>
        <MenuItem
          onClick={this.addNode.bind(this, 'if_clicked_email', afterIndex)}
          disabled={!hasEmails}
        >
          If Clicked Email Node
        </MenuItem>
        <MenuItem onClick={this.addNode.bind(this, 'go_to', afterIndex)}>Go To Node</MenuItem>
        <MenuItem
          onClick={this.addNode.bind(this, 'send_email', afterIndex)}
          disabled={!hasEmails}
        >
          Send Email Node
        </MenuItem>
        <MenuItem onClick={this.addNode.bind(this, 'exit', afterIndex)}>Add Exit Node</MenuItem>
      </DropdownButton>
    );
  }

  render() {
    const nodes = this.props.nodes || [];
    return (
      <EDFormBox space>
        <div className="flex-items space-between">
          <h4>Draft Workflow</h4>
          {this.renderAddNodeDropdown('automation-node-create-dropdown', 'Add Node')}
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
            <EDTable className="growing-margin-left" minWidth="600px" maxWidth="1024px">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Type</th>
                  <th>Label</th>
                  <th>Configuration</th>
                  <th>Contacts at step</th>
                  <th></th>
                </tr>
              </thead>
              {
                _.map(nodes, (node, index) =>
                  {
                    const expanded = !!this.state.expandedNodeIds[node.id];
                    return (
                      <EDTableRow key={node.id} index={index}>
                        <td>
                          <h4>{index + 1}</h4>
                        </td>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>
                            {automationNodeTypeLabel(node.type)}
                          </h4>
                        </td>
                        <td>
                          <FormControl
                            id="label"
                            value={node.label}
                            onChange={this.nodeChange.bind(this, index)}
                            required={true}
                          />
                        </td>
                        <td>
                          <p style={{marginBottom: expanded ? '8px' : 0}}>
                            {this.nodeSummary(node)}
                          </p>
                          <Button
                            bsSize="small"
                            onClick={this.toggleNodeDetails.bind(this, node)}
                          >
                            {expanded ? 'Hide details' : 'Edit details'}
                          </Button>
                          {
                            expanded ?
                              <div style={{marginTop: '10px'}}>
                                {this.renderNodeConfig(node, index)}
                              </div>
                            :
                              null
                          }
                        </td>
                        <td>
                          {this.props.renderNodeContactCount(node)}
                        </td>
                        <td style={{minWidth: '300px'}} className="last-cell">
                          {this.renderAddNodeDropdown('automation-node-insert-dropdown-' + node.id, 'Insert node after this step', index)}
                          {' '}
                          <Button
                            bsSize="small"
                            disabled={index === 0}
                            onClick={this.moveNode.bind(this, index, -1)}
                          >
                            Move up
                          </Button>
                          {' '}
                          <Button
                            bsSize="small"
                            disabled={index === nodes.length - 1}
                            onClick={this.moveNode.bind(this, index, 1)}
                          >
                            Move down
                          </Button>
                          {' '}
                          <Button onClick={this.deleteNode.bind(this, index)}>Delete</Button>
                        </td>
                      </EDTableRow>
                    );
                  }
                )
              }
            </EDTable>
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
