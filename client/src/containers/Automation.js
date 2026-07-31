import React, { Component } from "react";
import { Button, DropdownButton, FormControl, MenuItem, Panel, PanelGroup } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
import shortid from "shortid";
import Select2 from "react-select2-wrapper";
import LoaderButton from "../components/LoaderButton";
import LoaderPanel from "../components/LoaderPanel";
import SaveNavbar from "../components/SaveNavbar";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel, SelectLabel } from "../components/FormControls";
import { EDFormSection, EDFormBox, EDTable, EDTableRow } from "../components/EDDOM";
import fixTag from "../utils/fixtag";
import getvalue from "../utils/getvalue";
import notify from "../utils/notify";
import copyText from "../utils/clipboard";

import "react-select2-wrapper/css/select2.css";

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

function normalizeAutomation(automation) {
  automation.entry = automation.entry || {type: 'manual'};
  if (automation.entry.type === 'tag_added') {
    automation.entry.tag = automation.entry.tag || '';
  } else {
    automation.entry = {type: 'manual'};
  }
  automation.reentry = automation.reentry || 'once';
  automation.draft = automation.draft || {};
  automation.draft.nodes = automation.draft.nodes || [];
  return automation;
}

function entryPayload(entry) {
  if (entry && entry.type === 'tag_added') {
    return {
      type: 'tag_added',
      tag: entry.tag || '',
    };
  }
  return {
    type: 'manual',
  };
}

function patchPayload(data) {
  return {
    name: data.name,
    entry: entryPayload(data.entry),
    reentry: data.reentry || 'once',
    draft: {
      nodes: data.draft.nodes,
    },
  };
}

export function canReEnrolAutomation(data) {
  const published = data.published || {};
  return published.reentry === 'multiple' || data.reentry === 'multiple';
}

export function isTerminalEnrolmentStatus(status) {
  return _.contains(['completed', 'exited', 'cancelled'], status);
}

export function displayAutomationEnrolments(enrolments) {
  return _.chain(enrolments)
    .groupBy(enrolment => enrolment.contact_id || enrolment.contact_email)
    .map(group => {
      const ready = _.filter(group, enrolment => enrolment.status === 'ready');
      if (ready.length) {
        return _.max(ready, enrolment => moment(enrolment.created || 0).valueOf());
      }

      return _.max(group, enrolment => moment(enrolment.created || 0).valueOf());
    })
    .sortBy(enrolment => moment(enrolment.created || 0).valueOf())
    .value();
}

function formatDebugTime(value) {
  return value ? moment(value).format('lll') : '';
}

export function automationHistoryLog(history, options) {
  const events = options && options.newestFirst ?
    ((history && history.events) || []).slice().reverse()
  :
    (history && history.events) || [];
  if (!events.length) {
    return 'No automation history yet.';
  }

  return _.map(events, event => {
    const parts = [
      formatDebugTime(event.created),
      event.contact_email || 'unknown contact',
      'enrolment ' + event.enrolment_id,
    ];

    if (event.type === 'enrolment') {
      parts.push('enrolled');
      parts.push('status=' + (event.status || ''));
      parts.push('source=' + (event.source || ''));
      parts.push('current_node=' + (event.current_node_id || ''));
      if (event.wake_at) {
        parts.push('wake_at=' + event.wake_at);
      }
      if (event.paused_at) {
        parts.push('paused_at=' + event.paused_at);
      }
      if (event.resumed_at) {
        parts.push('resumed_at=' + event.resumed_at);
      }
      if (event.remaining_seconds !== undefined && event.remaining_seconds !== null) {
        parts.push('remaining_seconds=' + event.remaining_seconds);
      }
    } else {
      parts.push('step ' + (event.node_type || '') + ' ' + (event.node_id || ''));
      if (event.action) {
        parts.push('action=' + event.action);
      }
      if (event.node_label) {
        parts.push('"' + event.node_label + '"');
      }
      if (event.tag) {
        parts.push('tag=' + event.tag);
      }
      if (event.list_id) {
        parts.push('list=' + event.list_id);
      }
      if (event.list_name) {
        parts.push('list_name="' + event.list_name + '"');
      }
      if (event.added !== undefined && event.added !== null) {
        parts.push('added=' + event.added);
      }
      if (event.removed !== undefined && event.removed !== null) {
        parts.push('removed=' + event.removed);
      }
      if (event.wake_at) {
        parts.push('wake_at=' + event.wake_at);
      }
      if (event.skipped) {
        parts.push('skipped=true');
      }
      if (event.result !== undefined && event.result !== null) {
        parts.push('result=' + event.result);
      }
      if (event.branch) {
        parts.push('branch=' + event.branch);
      }
      if (event.target_node_id) {
        parts.push('target=' + event.target_node_id);
      }
      if (event.automation_email_id) {
        parts.push('automation_email=' + event.automation_email_id);
      }
      if (event.automation_email_name) {
        parts.push('email_name="' + event.automation_email_name + '"');
      }
      if (event.subject) {
        parts.push('subject="' + event.subject + '"');
      }
      if (event.recipient_email) {
        parts.push('recipient=' + event.recipient_email);
      }
      if (event.route_id) {
        parts.push('route=' + event.route_id);
      }
      if (event.sent !== undefined && event.sent !== null) {
        parts.push('sent=' + event.sent);
      }
      parts.push('status=' + (event.status || ''));
      if (event.error) {
        parts.push('error=' + event.error);
      }
    }

    parts.push('revision=' + (event.published_revision || ''));
    return parts.join(' | ');
  }).join('\n');
}

export function automationHistoryForEnrolment(history, enrolmentId) {
  return {
    enrolments: _.filter((history && history.enrolments) || [], enrolment => enrolment.id === enrolmentId),
    events: _.filter((history && history.events) || [], event => event.enrolment_id === enrolmentId),
  };
}

export function automationHistoryLogForEnrolment(history, enrolmentId) {
  return automationHistoryLog(automationHistoryForEnrolment(history, enrolmentId));
}

export function automationHistoryContacts(history) {
  return _.chain((history && history.enrolments) || [])
    .groupBy(enrolment => enrolment.contact_email || 'unknown contact')
    .map((enrolments, email) => ({
      id: email,
      email: email,
      enrolments: _.chain(enrolments)
        .sortBy(enrolment => moment(enrolment.created || 0).valueOf())
        .reverse()
        .value(),
    }))
    .sortBy(contact => contact.email.toLowerCase())
    .value();
}

export function automationEnrolmentAction(enrolment, automation, now) {
  if (_.contains(['held', 'paused_ready', 'paused_waiting'], enrolment.status)) {
    return {
      type: 'none',
      label: '',
      disabled: true,
    };
  }

  if (enrolment.status === 'ready') {
    return {
      type: 'run_next',
      label: 'Run next test',
      disabled: false,
    };
  }

  if (enrolment.status === 'waiting') {
    const wakeAt = enrolment.wake_at && moment(enrolment.wake_at);
    if (wakeAt && wakeAt.isValid() && wakeAt.isSameOrBefore(now || moment())) {
      return {
        type: 'continue_wait',
        label: 'Continue test',
        disabled: false,
      };
    }
    return {
      type: 'skip_wait',
      label: 'Move to next node',
      waitLabel: 'Waiting until ' + (wakeAt && wakeAt.isValid() ? wakeAt.format('lll') : ''),
      disabled: false,
    };
  }

  if (canReEnrolAutomation(automation) && isTerminalEnrolmentStatus(enrolment.status)) {
    return {
      type: 'reenrol',
      label: 'Run automation again',
      disabled: false,
    };
  }

  return {
    type: 'none',
    label: '',
    disabled: true,
  };
}

class Automation extends Component {
  constructor(props) {
    super(props);

    this.state = {
      isPublishing: false,
      isPausing: false,
      isEnrolling: false,
      runningEnrolmentId: null,
      reenrollingEnrolmentId: null,
      enrolEmail: '',
      isCreatingEmail: false,
      deletingEmailId: null,
      duplicatingEmailId: null,
    };
  }

  goBack = () => {
    this.props.history.push('/automations');
  }

  handleChange = event => {
    this.props.update({[event.target.id]: {$set: getvalue(event)}});
  }

  enrolEmailChange = event => {
    this.setState({enrolEmail: event.target.value});
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

  entryTypeChange = event => {
    const type = getvalue(event);
    this.props.update({
      entry: {$set: type === 'tag_added' ? {
        type: 'tag_added',
        tag: (this.props.data.entry && this.props.data.entry.tag) || '',
      } : {
        type: 'manual',
      }},
    });
  }

  entryTagChange = event => {
    this.props.update({
      entry: {
        tag: {$set: event.params.data.id},
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

  tagData() {
    const tags = this.props.tags || [];
    const nodes = (this.props.data.draft && this.props.data.draft.nodes) || [];
    const draftTags = _.pluck(_.filter(nodes, node => _.contains(['add_tag', 'remove_tag', 'if_has_tag'], node.type) && node.draft_tag), 'draft_tag');
    const entry = this.props.data.entry || {};
    const entryTags = entry.type === 'tag_added' && entry.tag ? [entry.tag] : [];

    return _.map(_.uniq(tags.concat(draftTags).concat(entryTags)), tag => ({id: tag, text: tag}));
  }

  nodeTargetOptions(node) {
    const nodes = (this.props.data.draft && this.props.data.draft.nodes) || [];
    return _.chain(nodes)
      .map((target, index) => ({
        target: target,
        step: index + 1,
      }))
      .filter(option => option.target.id !== node.id)
      .map(option => ({
        id: option.target.id,
        name: 'Step ' + option.step + ' - ' +
          (option.target.label || this.nodeTypeLabel(option.target.type)) +
          ' (' + this.nodeTypeLabel(option.target.type) + ')',
      }))
      .value();
  }

  editorTypeLabel(type) {
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

  automationEmailOptions() {
    return _.map(this.props.emails || [], email => ({
      id: email.id,
      name: (email.name || 'Untitled email') +
        ' - ' +
        (email.subject || 'No subject') +
        ' (' +
        this.editorTypeLabel(email.type) +
        ')',
    }));
  }

  listOptions() {
    return _.map(this.props.lists || [], list => ({
      id: list.id,
      name: (list.name || 'Untitled list') +
        (list.count !== undefined && list.count !== null ? ' (' + list.count + ' contacts)' : ''),
    }));
  }

  addNode = type => {
    const node = {
      id: shortid.generate(),
      type: type,
      label: type === 'add_tag' ? 'Add tag' : type === 'remove_tag' ? 'Remove tag' : type === 'add_to_list' ? 'Add to list' : type === 'remove_from_list' ? 'Remove from list' : type === 'wait_duration' ? 'Wait' : type === 'if_has_tag' ? 'If contact has tag' : type === 'go_to' ? 'Go to' : type === 'send_email' ? 'Send email' : 'Exit automation',
    };

    if (type === 'add_tag' || type === 'remove_tag') {
      node.draft_tag = '';
    }
    if (type === 'if_has_tag') {
      node.draft_tag = '';
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
      const emails = this.props.emails || [];
      node.automation_email_id = emails.length ? emails[0].id : '';
    }
    if (type === 'add_to_list' || type === 'remove_from_list') {
      const lists = this.props.lists || [];
      node.list_id = lists.length ? lists[0].id : '';
    }

    this.props.update({
      draft: {
        nodes: {
          $push: [node],
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

  save = async () => {
    try {
      await this.props.save(patchPayload(this.props.data));
      notify.show('Automation saved', 'success');
      return true;
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to save automation'), 'error');
      return false;
    }
  }

  publish = async () => {
    this.setState({isPublishing: true});

    try {
      const saved = await this.save();
      if (!saved) {
        return;
      }

      await axios.post('/api/automations/' + this.props.id + '/publish');
      notify.show('Automation published', 'success');
      await this.props.reload();
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to publish automation'), 'error');
    } finally {
      this.setState({isPublishing: false});
    }
  }

  pause = async () => {
    this.setState({isPausing: true});

    try {
      await axios.post('/api/automations/' + this.props.id + '/pause');
      notify.show('Automation paused', 'success');
      await this.props.reload();
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to pause automation'), 'error');
    } finally {
      this.setState({isPausing: false});
    }
  }

  resume = async () => {
    this.setState({isPausing: true});

    try {
      await axios.post('/api/automations/' + this.props.id + '/resume');
      notify.show('Automation resumed', 'success');
      await this.props.reload();
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to resume automation'), 'error');
    } finally {
      this.setState({isPausing: false});
    }
  }

  enrolContact = async event => {
    event.preventDefault();

    const email = this.state.enrolEmail.trim();
    if (!email) {
      return;
    }

    this.setState({isEnrolling: true});
    try {
      await axios.post('/api/automations/' + this.props.id + '/enrolments', {email: email});
      notify.show('Contact enrolled', 'success');
      this.setState({enrolEmail: ''});
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to enrol contact'), 'error');
    } finally {
      this.setState({isEnrolling: false});
    }
  }

  runNext = async (enrolment, options) => {
    this.setState({runningEnrolmentId: enrolment.id});

    try {
      const url = '/api/automations/' + this.props.id + '/enrolments/' + enrolment.id + '/run-next' +
        (options && options.skip_wait ? '?skip_wait=true' : '');
      await axios.post(url, options || {});
      notify.show(options && options.skip_wait ? 'Automation wait skipped' : 'Automation test step ran', 'success');
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to run next automation step'), 'error');
    } finally {
      this.setState({runningEnrolmentId: null});
    }
  }

  copyHistoryLog = (log, event) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (copyText(log)) {
      notify.show('Debug history copied to clipboard', 'success');
    } else {
      notify.show('Error accessing clipboard', 'error');
    }
  }

  reEnrolContact = async enrolment => {
    this.setState({reenrollingEnrolmentId: enrolment.id});

    try {
      await axios.post('/api/automations/' + this.props.id + '/enrolments', {email: enrolment.contact_email});
      notify.show('Automation test restarted', 'success');
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to restart automation test'), 'error');
    } finally {
      this.setState({reenrollingEnrolmentId: null});
    }
  }

  canReEnrol() {
    return canReEnrolAutomation(this.props.data);
  }

  createEmail = async type => {
    this.setState({isCreatingEmail: true});
    try {
      const email = (await axios.post('/api/automations/' + this.props.id + '/emails', {type: type})).data;
      notify.show('Automation email created', 'success');
      this.props.history.push('/automations/' + this.props.id + '/emails/' + email.id);
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to create automation email'), 'error');
    } finally {
      this.setState({isCreatingEmail: false});
    }
  }

  editEmail = email => {
    this.props.history.push('/automations/' + this.props.id + '/emails/' + email.id);
  }

  duplicateEmail = async email => {
    this.setState({duplicatingEmailId: email.id});
    try {
      await axios.post('/api/automations/' + this.props.id + '/emails/' + email.id + '/duplicate');
      notify.show('Automation email duplicated', 'success');
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to duplicate automation email'), 'error');
    } finally {
      this.setState({duplicatingEmailId: null});
    }
  }

  deleteEmail = async email => {
    this.setState({deletingEmailId: email.id});
    try {
      await axios.delete('/api/automations/' + this.props.id + '/emails/' + email.id);
      notify.show('Automation email deleted', 'success');
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to delete automation email'), 'error');
    } finally {
      this.setState({deletingEmailId: null});
    }
  }

  displayEnrolments(enrolments) {
    return displayAutomationEnrolments(enrolments);
  }

  handleSubmit = async event => {
    const isclose = this.props.formClose(event);

    const saved = await this.save();

    if (saved && isclose) {
      this.goBack();
    }
  }

  navbarButtons = () => {
    return (
      <div>
        <Button
          bsStyle="primary"
          disabled={this.props.isSaving || this.state.isPublishing || this.state.isPausing}
          onClick={this.publish}
        >
          {this.state.isPublishing ? 'Publishing...' : 'Publish'}
        </Button>
        {
          this.props.data.published_at ?
            <span>
              {' '}
              <Button
                disabled={this.props.isSaving || this.state.isPublishing || this.state.isPausing}
                onClick={this.props.data.status === 'paused' ? this.resume : this.pause}
              >
                {
                  this.state.isPausing ?
                    this.props.data.status === 'paused' ? 'Resuming...' : 'Pausing...'
                  :
                    this.props.data.status === 'paused' ? 'Resume' : 'Pause'
                }
              </Button>
            </span>
          :
            null
        }
        {' '}
        <LoaderButton
          id="automation-buttons-dropdown"
          text="Save"
          loadingText="Saving..."
          className="green"
          disabled={this.props.isSaving || this.state.isPublishing}
          onClick={this.props.formSubmit}
          splitItems={[
            { text: 'Save and Close', onClick: this.props.formSubmit.bind(null, true) },
            { text: 'Cancel', onClick: this.goBack }
          ]}
        />
      </div>
    );
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
      const options = this.automationEmailOptions();
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

    if (node.type === 'add_to_list' || node.type === 'remove_from_list') {
      const options = this.listOptions();
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

  nodeTypeLabel(type) {
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
    if (type === 'go_to') {
      return 'Go to';
    }
    if (type === 'send_email') {
      return 'Send email';
    }
    return 'Exit';
  }

  renderEnrolments() {
    const data = this.props.data;
    const enrolments = this.props.enrolments || [];
    const displayEnrolments = this.displayEnrolments(enrolments);

    if (!data.published_at) {
      return (
        <EDFormBox space>
          <h4>Enrolments</h4>
          <p>Publish this automation before contacts can be enrolled.</p>
        </EDFormBox>
      );
    }

    return (
      <EDFormBox space>
        <div className="flex-items space-between">
          <h4>Enrolments</h4>
          <form className="form-inline" onSubmit={this.enrolContact}>
            <FormControl
              type="email"
              value={this.state.enrolEmail}
              onChange={this.enrolEmailChange}
              placeholder="Existing contact email"
              style={{width: '240px'}}
              disabled={this.state.isEnrolling}
            />
            {' '}
            <LoaderButton
              type="submit"
              bsStyle="primary"
              text="Enrol Contact"
              loadingText="Enrolling..."
              isLoading={this.state.isEnrolling}
              disabled={this.state.isEnrolling || !this.state.enrolEmail.trim()}
            />
          </form>
        </div>
        {
          displayEnrolments.length ?
            <EDTable className="growing-margin-left" minWidth="600px" maxWidth="1024px">
              <thead>
                <tr>
                  <th>Contact</th>
                  <th>Status</th>
                  <th>Current Node</th>
                  <th>Source</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              {
                _.map(displayEnrolments, (enrolment, index) =>
                  {
                    const action = automationEnrolmentAction(enrolment, data);
                    return (
                      <EDTableRow key={enrolment.id} index={index}>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.contact_email}</h4>
                        </td>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.status}</h4>
                        </td>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.current_node_id}</h4>
                        </td>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.source}</h4>
                        </td>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>
                            {enrolment.created ? moment(enrolment.created).format('lll') : ''}
                          </h4>
                        </td>
                        <td className="last-cell" style={{minWidth: '150px'}}>
                          {
                            action.type === 'run_next' || action.type === 'continue_wait' ?
                              <Button
                                bsSize="small"
                                disabled={this.state.runningEnrolmentId === enrolment.id}
                                onClick={this.runNext.bind(this, enrolment)}
                              >
                                {
                                  this.state.runningEnrolmentId === enrolment.id ?
                                    'Running...'
                                  :
                                    action.label
                                }
                              </Button>
                            :
                              action.type === 'skip_wait' ?
                                <div>
                                  <div style={{whiteSpace: 'nowrap', marginBottom: '6px'}}>{action.waitLabel}</div>
                                  <Button
                                    bsSize="small"
                                    disabled={this.state.runningEnrolmentId === enrolment.id}
                                    onClick={this.runNext.bind(this, enrolment, {skip_wait: true})}
                                  >
                                    {
                                      this.state.runningEnrolmentId === enrolment.id ?
                                        'Moving...'
                                      :
                                        action.label
                                    }
                                  </Button>
                                </div>
                            :
                              action.type === 'reenrol' ?
                                <Button
                                  bsSize="small"
                                  disabled={this.state.reenrollingEnrolmentId === enrolment.id}
                                  onClick={this.reEnrolContact.bind(this, enrolment)}
                                >
                                  {
                                    this.state.reenrollingEnrolmentId === enrolment.id ?
                                      'Starting...'
                                    :
                                      action.label
                                  }
                                </Button>
                            :
                              null
                          }
                        </td>
                      </EDTableRow>
                    );
                  }
                )
              }
            </EDTable>
          :
            <div className="text-center space-top-sm">
              <h4>No contacts are enrolled yet.</h4>
            </div>
        }
      </EDFormBox>
    );
  }

  renderEmails() {
    const emails = this.props.emails || [];
    const busy = this.state.isCreatingEmail || this.state.deletingEmailId || this.state.duplicatingEmailId;

    return (
      <EDFormBox space>
        <div className="flex-items space-between">
          <h4>Emails</h4>
          <DropdownButton
            id="automation-email-create-dropdown"
            title={this.state.isCreatingEmail ? 'Creating...' : 'Create Email'}
            disabled={busy}
          >
            <MenuItem onClick={this.createEmail.bind(this, 'beefree')}>BeeFree editor</MenuItem>
            <MenuItem onClick={this.createEmail.bind(this, '')}>Legacy editor</MenuItem>
            <MenuItem onClick={this.createEmail.bind(this, 'wysiwyg')}>WYSIWYG editor</MenuItem>
            <MenuItem onClick={this.createEmail.bind(this, 'raw')}>HTML editor</MenuItem>
          </DropdownButton>
        </div>
        {
          emails.length ?
            <EDTable className="growing-margin-left" minWidth="600px" maxWidth="1024px">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Subject</th>
                  <th>Modified</th>
                  <th></th>
                </tr>
              </thead>
              {
                _.map(emails, (email, index) =>
                  <EDTableRow key={email.id} index={index}>
                    <td><h4 style={{whiteSpace: 'nowrap'}}>{email.name}</h4></td>
                    <td><h4 style={{whiteSpace: 'nowrap'}}>{email.subject}</h4></td>
                    <td>
                      <h4 style={{whiteSpace: 'nowrap'}}>
                        {email.modified ? moment(email.modified).format('lll') : ''}
                      </h4>
                    </td>
                    <td className="last-cell" style={{minWidth: '240px'}}>
                      <Button
                        bsSize="small"
                        disabled={busy}
                        onClick={this.editEmail.bind(this, email)}
                      >
                        Edit
                      </Button>
                      {' '}
                      <Button
                        bsSize="small"
                        disabled={busy}
                        onClick={this.duplicateEmail.bind(this, email)}
                      >
                        {this.state.duplicatingEmailId === email.id ? 'Duplicating...' : 'Duplicate'}
                      </Button>
                      {' '}
                      <Button
                        bsSize="small"
                        disabled={busy}
                        onClick={this.deleteEmail.bind(this, email)}
                      >
                        {this.state.deletingEmailId === email.id ? 'Deleting...' : 'Delete'}
                      </Button>
                    </td>
                  </EDTableRow>
                )
              }
            </EDTable>
          :
            <div className="text-center space-top-sm">
              <h4>No automation emails yet.</h4>
            </div>
        }
      </EDFormBox>
    );
  }

  renderStepRuns(enrolment) {
    if (!enrolment.step_runs || !enrolment.step_runs.length) {
      return <p>No step runs recorded for this pass.</p>;
    }

    return (
      <EDTable className="growing-margin-left" minWidth="600px" maxWidth="1024px">
        <thead>
          <tr>
            <th>Created</th>
            <th>Node</th>
            <th>Type</th>
            <th>Label</th>
            <th>Tag</th>
            <th>Status</th>
            <th>Revision</th>
          </tr>
        </thead>
        {
          _.map(enrolment.step_runs, (stepRun, index) =>
            <EDTableRow key={stepRun.id} index={index}>
              <td><h4 style={{whiteSpace: 'nowrap'}}>{formatDebugTime(stepRun.created)}</h4></td>
              <td><h4 style={{whiteSpace: 'nowrap'}}>{stepRun.node_id}</h4></td>
              <td><h4 style={{whiteSpace: 'nowrap'}}>{stepRun.node_type}</h4></td>
              <td><h4 style={{whiteSpace: 'nowrap'}}>{stepRun.node_label || ''}</h4></td>
              <td><h4 style={{whiteSpace: 'nowrap'}}>{stepRun.tag || ''}</h4></td>
              <td><h4 style={{whiteSpace: 'nowrap'}}>{stepRun.status || stepRun.error || ''}</h4></td>
              <td><h4 style={{whiteSpace: 'nowrap'}}>{stepRun.published_revision || ''}</h4></td>
            </EDTableRow>
          )
        }
      </EDTable>
    );
  }

  renderEnrolmentHistory(history, enrolment) {
    const log = automationHistoryLogForEnrolment(history, enrolment.id);
    const events = automationHistoryForEnrolment(history, enrolment.id).events;

    return (
      <div>
        <p>
          Pass {enrolment.id}
          {' | '}status={enrolment.status || ''}
          {' | '}source={enrolment.source || ''}
          {' | '}current_node={enrolment.current_node_id || ''}
          {
            enrolment.wake_at ?
              ' | wake_at=' + enrolment.wake_at
            :
              ''
          }
          {
            enrolment.paused_at ?
              ' | paused_at=' + formatDebugTime(enrolment.paused_at)
            :
              ''
          }
          {
            enrolment.resumed_at ?
              ' | resumed_at=' + formatDebugTime(enrolment.resumed_at)
            :
              ''
          }
          {
            enrolment.wait && enrolment.wait.remaining_seconds !== undefined ?
              ' | remaining_seconds=' + enrolment.wait.remaining_seconds
            :
              ''
          }
          {' | '}created={formatDebugTime(enrolment.created)}
          {' | '}modified={formatDebugTime(enrolment.modified)}
        </p>
        {this.renderStepRuns(enrolment)}
        <div className="flex-items space-between" style={{marginTop: '16px', marginBottom: '6px', position: 'relative', zIndex: 2}}>
          <h4>Plain text log for this pass</h4>
          <button
            type="button"
            className="btn btn-default btn-sm"
            title="Copy this pass log"
            onMouseDown={event => event.stopPropagation()}
            onClick={this.copyHistoryLog.bind(this, log)}
            style={{marginTop: '4px', position: 'relative', zIndex: 3, pointerEvents: 'auto', cursor: 'pointer'}}
          >
            <i className="fa fa-clipboard" /> Copy
          </button>
        </div>
        <FormControl
          componentClass="textarea"
          rows={Math.min(Math.max(events.length + 1, 4), 12)}
          readOnly
          value={log}
          onFocus={event => event.target.select()}
        />
      </div>
    );
  }

  renderHistory() {
    const history = this.props.historyData || {};
    const contacts = automationHistoryContacts(history);
    const log = automationHistoryLog(history, {newestFirst: true});

    return (
      <EDFormBox space>
        <Panel id="automation-debug-history-panel">
          <Panel.Heading style={{backgroundColor: 'white'}}>
            <Panel.Title toggle style={{fontSize: '14px'}}>
              Debug history
            </Panel.Title>
          </Panel.Heading>
          <Panel.Collapse>
            <Panel.Body>
              {
                contacts.length ?
                  <PanelGroup accordion id="automation-history-contacts-accordion">
                    {
                      _.map(contacts, (contact, contactIndex) =>
                        <Panel eventKey={contact.id} key={contact.id}>
                          <Panel.Heading>
                            <Panel.Title toggle style={{fontSize: '14px'}}>
                              {contact.email}
                              {' '}
                              <span className="text-muted">
                                ({contact.enrolments.length} {contact.enrolments.length === 1 ? 'pass' : 'passes'})
                              </span>
                            </Panel.Title>
                          </Panel.Heading>
                          <Panel.Collapse>
                            <Panel.Body>
                              <PanelGroup accordion id={'automation-history-passes-' + contactIndex}>
                                {
                                  _.map(contact.enrolments, enrolment =>
                                    <Panel eventKey={enrolment.id} key={enrolment.id}>
                                      <Panel.Heading>
                                        <Panel.Title toggle style={{fontSize: '14px'}}>
                                          {formatDebugTime(enrolment.created) || 'Unknown date'}
                                          {' | '}status={enrolment.status || ''}
                                          {' | '}source={enrolment.source || ''}
                                        </Panel.Title>
                                      </Panel.Heading>
                                      <Panel.Collapse>
                                        <Panel.Body>
                                          {this.renderEnrolmentHistory(history, enrolment)}
                                        </Panel.Body>
                                      </Panel.Collapse>
                                    </Panel>
                                  )
                                }
                              </PanelGroup>
                            </Panel.Body>
                          </Panel.Collapse>
                        </Panel>
                      )
                    }
                  </PanelGroup>
                :
                  <p>No automation history yet.</p>
              }
              <div className="flex-items space-between" style={{marginTop: '16px', marginBottom: '6px', position: 'relative', zIndex: 2}}>
                <h4>Plain text log</h4>
                <button
                  type="button"
                  className="btn btn-default btn-sm"
                  title="Copy plain text log"
                  onMouseDown={event => event.stopPropagation()}
                  onClick={this.copyHistoryLog.bind(this, log)}
                  style={{marginTop: '4px', position: 'relative', zIndex: 3, pointerEvents: 'auto', cursor: 'pointer'}}
                >
                  <i className="fa fa-clipboard" /> Copy
                </button>
              </div>
              <FormControl
                componentClass="textarea"
                rows={Math.min(Math.max((history.events || []).length + 1, 4), 16)}
                readOnly
                value={log}
                onFocus={event => event.target.select()}
              />
            </Panel.Body>
          </Panel.Collapse>
        </Panel>
      </EDFormBox>
    );
  }

  render() {
    const data = this.props.data;
    const nodes = (data.draft && data.draft.nodes) || [];

    return (
      <SaveNavbar title={'Edit Automation'} user={this.props.user} isSaving={this.props.isSaving}
        onBack={this.goBack} buttons={this.navbarButtons()} id={this.props.id}>
        <LoaderPanel isLoading={this.props.isLoading}>
          <EDFormSection onSubmit={this.handleSubmit} formRef={this.props.formRef}>
            <EDFormBox>
              <FormControlLabel
                id="name"
                label="Name"
                obj={data}
                onChange={this.handleChange}
                required={true}
              />
              <FormControlLabel
                id="status"
                label="Status"
                obj={data}
                roph
                space
              />
            </EDFormBox>
            <EDFormBox space>
              <h4>Published Definition</h4>
              {
                data.published_at ?
                  <p>
                    Published {moment(data.published_at).format('lll')}
                    {data.published_revision ? ' (revision ' + data.published_revision + ')' : ''}
                  </p>
                :
                  <p>Not published</p>
              }
            </EDFormBox>
            <EDFormBox space>
              <h4>Entry</h4>
              <SelectLabel
                id="type"
                label="Entry trigger"
                obj={data.entry || {type: 'manual'}}
                onChange={this.entryTypeChange}
                options={[
                  {id: 'manual', name: 'Manual'},
                  {id: 'tag_added', name: 'Tag added'},
                ]}
              />
              {
                data.entry && data.entry.type === 'tag_added' ?
                  <div style={{maxWidth: '360px'}} className="space-bottom">
                    <label>Trigger tag</label>
                    <Select2
                      data={this.tagData()}
                      value={data.entry.tag || ''}
                      onSelect={this.entryTagChange}
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
                :
                  <p>Contacts can be added manually from this automation or from a contact/list action.</p>
              }
              <SelectLabel
                id="reentry"
                label="Contact re-entry"
                obj={data}
                onChange={this.handleChange}
                options={[
                  {id: 'once', name: 'Enter once'},
                  {id: 'multiple', name: 'Enter multiple times'},
                ]}
                space
              />
            </EDFormBox>
            {this.renderEmails()}
            <EDFormBox space>
              <div className="flex-items space-between">
                <h4>Draft Workflow</h4>
                <DropdownButton
                  id="automation-node-create-dropdown"
                  title="Add Node"
                >
                  <MenuItem onClick={this.addNode.bind(this, 'add_tag')}>Add Tag Node</MenuItem>
                  <MenuItem onClick={this.addNode.bind(this, 'remove_tag')}>Remove Tag Node</MenuItem>
                  <MenuItem
                    onClick={this.addNode.bind(this, 'add_to_list')}
                    disabled={!((this.props.lists || []).length)}
                  >
                    Add To List Node
                  </MenuItem>
                  <MenuItem
                    onClick={this.addNode.bind(this, 'remove_from_list')}
                    disabled={!((this.props.lists || []).length)}
                  >
                    Remove From List Node
                  </MenuItem>
                  <MenuItem onClick={this.addNode.bind(this, 'wait_duration')}>Wait Duration Node</MenuItem>
                  <MenuItem onClick={this.addNode.bind(this, 'if_has_tag')}>Condition Node</MenuItem>
                  <MenuItem onClick={this.addNode.bind(this, 'go_to')}>Go To Node</MenuItem>
                  <MenuItem
                    onClick={this.addNode.bind(this, 'send_email')}
                    disabled={!((this.props.emails || []).length)}
                  >
                    Send Email Node
                  </MenuItem>
                  <MenuItem onClick={this.addNode.bind(this, 'exit')}>Add Exit Node</MenuItem>
                </DropdownButton>
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
                        <th></th>
                      </tr>
                    </thead>
                    {
                      _.map(nodes, (node, index) =>
                        <EDTableRow key={node.id} index={index}>
                          <td>
                            <h4>{index + 1}</h4>
                          </td>
                          <td>
                            <h4 style={{whiteSpace: 'nowrap'}}>
                              {this.nodeTypeLabel(node.type)}
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
                            {this.renderNodeConfig(node, index)}
                          </td>
                          <td style={{minWidth: '92px'}} className="last-cell">
                            <Button onClick={this.deleteNode.bind(this, index)}>Delete</Button>
                          </td>
                        </EDTableRow>
                      )
                    }
                  </EDTable>
                :
                  <div className="text-center space-top-sm">
                    <h4>This draft does not have any nodes yet.</h4>
                  </div>
              }
            </EDFormBox>
            {this.renderEnrolments()}
            {this.renderHistory()}
          </EDFormSection>
        </LoaderPanel>
      </SaveNavbar>
    );
  }
}

export default withLoadSave({
  extend: Automation,
  initial: {
    name: '',
    status: 'draft',
    reentry: 'once',
    entry: {
      type: 'manual',
    },
    draft: {
      nodes: [],
    },
  },
  get: async ({id}) => normalizeAutomation((await axios.get('/api/automations/' + id)).data),
  patch: ({id, data}) => axios.patch('/api/automations/' + id, patchPayload(data)),
  extra: {
    tags: async () => (await axios.get('/api/recenttags')).data,
    emails: async ({id}) => (await axios.get('/api/automations/' + id + '/emails')).data,
    lists: async () => _.sortBy((await axios.get('/api/lists')).data, l => (l.name || '').toLowerCase()),
    enrolments: async ({id}) => (await axios.get('/api/automations/' + id + '/enrolments')).data,
    historyData: async ({id}) => (await axios.get('/api/automations/' + id + '/history')).data,
  },
});
