import React, { Component } from "react";
import { Button, DropdownButton, FormControl, MenuItem, Modal, Panel, PanelGroup } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
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
import { canViewAutomationDiagnostics } from "../utils/automationDiagnostics";
import AutomationWorkflowEditor, { automationEditorTypeLabel, automationListOptions } from "./AutomationWorkflowEditor";

import "react-select2-wrapper/css/select2.css";

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

function normalizeAutomation(automation) {
  automation.entry = entryPayload(automation.entry || {type: 'manual'});
  automation.reentry = automation.reentry || 'once';
  automation.draft = automation.draft || {};
  automation.draft.nodes = automation.draft.nodes || [];
  return automation;
}

export function normalizeEntryTrigger(trigger) {
  if (trigger && _.contains(['tag_added', 'tag_removed'], trigger.type)) {
    return {
      type: trigger.type,
      tag: trigger.tag || '',
    };
  }
  if (trigger && _.contains(['list_joined', 'list_left'], trigger.type)) {
    return {
      type: trigger.type,
      list_id: trigger.list_id || '',
    };
  }
  if (trigger && _.contains(['segment_entered', 'segment_left'], trigger.type)) {
    return {
      type: trigger.type,
      segment_id: trigger.segment_id || '',
    };
  }
  return {
    type: 'manual',
  };
}

export function entryTriggers(entry) {
  if (entry && entry.type === 'multi') {
    const triggers = _.map(entry.triggers || [], normalizeEntryTrigger);
    return triggers.length ? triggers : [{type: 'manual'}];
  }
  return [normalizeEntryTrigger(entry || {type: 'manual'})];
}

export function entryPayload(entry) {
  const triggers = entryTriggers(entry);
  if (triggers.length > 1) {
    return {
      type: 'multi',
      triggers: triggers,
    };
  }
  const trigger = triggers[0] || {type: 'manual'};
  return normalizeEntryTrigger(trigger);
}

function triggerPayloadForType(type, current, lists, segments) {
  if (_.contains(['tag_added', 'tag_removed'], type)) {
    return {
      type: type,
      tag: (current && current.tag) || '',
    };
  }
  if (_.contains(['list_joined', 'list_left'], type)) {
    return {
      type: type,
      list_id: (current && current.list_id) || (lists.length ? lists[0].id : ''),
    };
  }
  if (_.contains(['segment_entered', 'segment_left'], type)) {
    return {
      type: type,
      segment_id: (current && current.segment_id) || (segments.length ? segments[0].id : ''),
    };
  }
  return {
    type: 'manual',
  };
}

function replaceEntryTrigger(entry, index, trigger) {
  const triggers = entryTriggers(entry);
  triggers[index] = trigger;
  return entryPayload({type: 'multi', triggers: triggers});
}

function addEntryTriggerToEntry(entry, trigger) {
  const triggers = entryTriggers(entry).concat([trigger]);
  return entryPayload({type: 'multi', triggers: triggers});
}

function removeEntryTriggerFromEntry(entry, index) {
  const triggers = entryTriggers(entry);
  triggers.splice(index, 1);
  return entryPayload({type: 'multi', triggers: triggers.length ? triggers : [{type: 'manual'}]});
}

function entryTagValues(entry) {
  return _.chain(entryTriggers(entry))
    .filter(trigger => _.contains(['tag_added', 'tag_removed'], trigger.type) && trigger.tag)
    .pluck('tag')
    .value();
}

function triggerOptions() {
  return [
    {id: 'manual', name: 'Manual'},
    {id: 'tag_added', name: 'Tag added'},
    {id: 'tag_removed', name: 'Tag removed'},
    {id: 'list_joined', name: 'Joined list'},
    {id: 'list_left', name: 'Left list'},
    {id: 'segment_entered', name: 'Entered segment'},
    {id: 'segment_left', name: 'Left segment'},
  ];
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

export function isActiveEnrolmentStatus(status) {
  return _.contains(['ready', 'waiting', 'held', 'paused_ready', 'paused_waiting', 'running'], status);
}

function contactKey(enrolment) {
  return enrolment.contact_id || enrolment.contact_email;
}

export function automationEnrolmentCounts(enrolments) {
  const contacts = _.groupBy(enrolments || [], contactKey);
  const activeContacts = _.filter(_.values(contacts), group =>
    _.some(group, enrolment => isActiveEnrolmentStatus(enrolment.status))
  );
  return {
    active: activeContacts.length,
    enrolled: _.keys(contacts).length,
  };
}

export function automationImpersonatedHref(path, impersonateId) {
  if (!impersonateId) {
    return path;
  }
  return path + (path.indexOf('?') === -1 ? '?' : '&') + 'impersonate=' + encodeURIComponent(impersonateId);
}

export function automationNodeContactIds(node, draftNodes, publishedNodes) {
  const index = _.findIndex(draftNodes || [], item => item.id === node.id);
  const publishedNode = index >= 0 ? (publishedNodes || [])[index] : null;
  return _.uniq(_.compact([node.id, publishedNode && publishedNode.id]));
}

export function automationNodeContactCount(node, draftNodes, publishedNodes, summary) {
  const counts = (summary && summary.nodes) || {};
  const positionCounts = (summary && summary.node_positions) || {};
  const index = _.findIndex(draftNodes || [], item => item.id === node.id);
  if (index >= 0 && positionCounts[String(index + 1)] !== undefined) {
    return positionCounts[String(index + 1)] || 0;
  }
  return _.reduce(
    automationNodeContactIds(node, draftNodes, publishedNodes),
    (total, nodeId) => total + (counts[nodeId] || 0),
    0
  );
}

export function automationNodeContactFilterId(node, draftNodes, publishedNodes) {
  const ids = automationNodeContactIds(node, draftNodes, publishedNodes);
  return ids.length > 1 ? ids[1] : ids[0];
}

export function automationNodeContactFilterParam(node, draftNodes, publishedNodes, summary) {
  const index = _.findIndex(draftNodes || [], item => item.id === node.id);
  const positionCounts = (summary && summary.node_positions) || {};
  if (index >= 0 && positionCounts[String(index + 1)] !== undefined) {
    return {
      key: 'node_position',
      value: String(index + 1),
    };
  }
  return {
    key: 'node_id',
    value: automationNodeContactFilterId(node, draftNodes, publishedNodes),
  };
}

export function displayAutomationEnrolments(enrolments) {
  return _.chain(enrolments)
    .groupBy(contactKey)
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
    } else if (event.type === 'engagement') {
      parts.push('engagement ' + (event.event_type || ''));
      if (event.automation_email_id) {
        parts.push('automation_email=' + event.automation_email_id);
      }
      if (event.automation_email_name) {
        parts.push('email_name="' + event.automation_email_name + '"');
      }
      if (event.subject) {
        parts.push('subject="' + event.subject + '"');
      }
      if (event.send_step_run_id) {
        parts.push('send_step=' + event.send_step_run_id);
      }
      if (event.link_url) {
        parts.push('link=' + event.link_url);
      }
      if (event.link_index !== undefined && event.link_index !== null) {
        parts.push('link_index=' + event.link_index);
      }
      if (event.inferred) {
        parts.push('inferred=true');
      }
      if (event.inferred_from_event_type) {
        parts.push('inferred_from=' + event.inferred_from_event_type);
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
  return sortAutomationHistoryContacts(_.chain((history && history.enrolments) || [])
    .groupBy(enrolment => enrolment.contact_email || 'unknown contact')
    .map((enrolments, email) => {
      const sortedEnrolments = _.chain(enrolments)
        .sortBy(enrolment => moment(enrolment.created || 0).valueOf())
        .reverse()
        .value();
      return {
        id: email,
        email: email,
        latest_created: sortedEnrolments.length ? sortedEnrolments[0].created : null,
        enrolments: sortedEnrolments,
      };
    })
    .value(), 'recent_desc');
}

export function filterAutomationHistoryContacts(contacts, search) {
  const term = (search || '').trim().toLowerCase();
  if (!term) {
    return contacts || [];
  }
  return _.filter(contacts || [], contact => (contact.email || '').toLowerCase().indexOf(term) !== -1);
}

export function sortAutomationHistoryContacts(contacts, sort) {
  const mode = sort || 'recent_desc';
  const normalizedContacts = contacts || [];
  const byEmail = contact => (contact.email || '').toLowerCase();
  const latest = contact => moment(contact.latest_created || ((contact.enrolments || [])[0] || {}).created || 0).valueOf();

  if (mode === 'email_asc') {
    return _.sortBy(normalizedContacts, byEmail);
  }
  if (mode === 'email_desc') {
    return _.sortBy(normalizedContacts, byEmail).reverse();
  }
  if (mode === 'recent_asc') {
    return _.sortBy(normalizedContacts, latest);
  }
  return _.sortBy(normalizedContacts, latest).reverse();
}

export function paginateAutomationHistoryContacts(contacts, page, pageSize) {
  const size = pageSize || 50;
  const total = (contacts || []).length;
  const totalPages = Math.max(1, Math.ceil(total / size));
  const currentPage = Math.min(Math.max(parseInt(page, 10) || 1, 1), totalPages);
  const start = (currentPage - 1) * size;
  return {
    contacts: (contacts || []).slice(start, start + size),
    page: currentPage,
    pageSize: size,
    total: total,
    totalPages: totalPages,
  };
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
      enrolmentSearch: '',
      enrolmentSearchResults: null,
      isSearchingEnrolments: false,
      isCreatingEmail: false,
      deletingEmailId: null,
      duplicatingEmailId: null,
      showEmailCopyModal: false,
      emailCopySources: [],
      emailCopyFilter: 'all',
      emailCopySearch: '',
      isLoadingEmailCopySources: false,
      copyingEmailSourceId: null,
      historyContactSearch: '',
      historyContactPage: 1,
      historyContactSort: 'recent_desc',
      isRefreshingPreflight: false,
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

  enrolmentSearchChange = event => {
    this.setState({enrolmentSearch: event.target.value});
  }

  searchEnrolments = async event => {
    event.preventDefault();
    const search = this.state.enrolmentSearch.trim();
    if (!search) {
      this.setState({enrolmentSearchResults: null});
      return;
    }

    this.setState({isSearchingEnrolments: true});
    try {
      const response = await axios.get('/api/automations/' + this.props.id + '/enrolments', {
        params: {
          view: 'all',
          search: search,
          page_size: 50,
        },
      });
      this.setState({enrolmentSearchResults: response.data});
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to search enrolments'), 'error');
    } finally {
      this.setState({isSearchingEnrolments: false});
    }
  }

  historyContactSearchChange = event => {
    this.setState({
      historyContactSearch: event.target.value,
      historyContactPage: 1,
    });
  }

  historyContactPageChange = page => {
    this.setState({historyContactPage: page});
  }

  historyContactSortChange = event => {
    this.setState({
      historyContactSort: event.target.value,
      historyContactPage: 1,
    });
  }

  entryTypeChange = (index, event) => {
    const type = getvalue(event);
    const lists = this.props.lists || [];
    const segments = this.props.segments || [];
    const current = entryTriggers(this.props.data.entry)[index] || {};
    this.props.update({
      entry: {$set: replaceEntryTrigger(
        this.props.data.entry,
        index,
        triggerPayloadForType(type, current, lists, segments),
      )},
    });
  }

  entryTagChange = (index, event) => {
    this.props.update({
      entry: {$set: replaceEntryTrigger(
        this.props.data.entry,
        index,
        {
          ...entryTriggers(this.props.data.entry)[index],
          tag: event.params.data.id,
        },
      )},
    });
  }

  entryListChange = (index, event) => {
    this.props.update({
      entry: {$set: replaceEntryTrigger(
        this.props.data.entry,
        index,
        {
          ...entryTriggers(this.props.data.entry)[index],
          list_id: getvalue(event),
        },
      )},
    });
  }

  entrySegmentChange = (index, event) => {
    this.props.update({
      entry: {$set: replaceEntryTrigger(
        this.props.data.entry,
        index,
        {
          ...entryTriggers(this.props.data.entry)[index],
          segment_id: getvalue(event),
        },
      )},
    });
  }

  addEntryTrigger = type => {
    const lists = this.props.lists || [];
    const segments = this.props.segments || [];
    this.props.update({
      entry: {$set: addEntryTriggerToEntry(
        this.props.data.entry,
        triggerPayloadForType(type, {}, lists, segments),
      )},
    });
  }

  removeEntryTrigger = index => {
    this.props.update({
      entry: {$set: removeEntryTriggerFromEntry(this.props.data.entry, index)},
    });
  }

  tagData() {
    const tags = this.props.tags || [];
    const nodes = (this.props.data.draft && this.props.data.draft.nodes) || [];
    const draftTags = _.pluck(_.filter(nodes, node => _.contains(['add_tag', 'remove_tag', 'if_has_tag'], node.type) && node.draft_tag), 'draft_tag');
    const entryTags = entryTagValues(this.props.data.entry);

    return _.map(_.uniq(tags.concat(draftTags).concat(entryTags)), tag => ({id: tag, text: tag}));
  }

  segmentOptions() {
    return _.map(this.props.segments || [], segment => ({
      id: segment.id,
      name: segment.name || segment.id,
    }));
  }

  listOptions() {
    return automationListOptions(this.props.lists || []);
  }

  renderEntryTrigger(trigger, index, count) {
    return (
      <div key={index} className="space-bottom" style={{borderBottom: '1px solid #eee', paddingBottom: '12px', maxWidth: '720px'}}>
        <div style={{display: 'flex', alignItems: 'flex-start', gap: '12px'}}>
          <div style={{width: '260px'}}>
            <SelectLabel
              id="type"
              label={index === 0 ? 'Entry trigger' : 'Additional trigger'}
              obj={trigger}
              onChange={event => this.entryTypeChange(index, event)}
              options={triggerOptions()}
            />
          </div>
          {
            count > 1 ?
              <Button
                bsStyle="link"
                style={{marginTop: '27px'}}
                onClick={() => this.removeEntryTrigger(index)}
              >
                Remove
              </Button>
            :
              null
          }
        </div>
        {
          _.contains(['tag_added', 'tag_removed'], trigger.type) ?
            <div style={{maxWidth: '360px'}}>
              <label>Trigger tag</label>
              <Select2
                data={this.tagData()}
                value={trigger.tag || ''}
                onSelect={event => this.entryTagChange(index, event)}
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
            _.contains(['list_joined', 'list_left'], trigger.type) ?
              (this.listOptions().length ?
                <div style={{maxWidth: '360px'}}>
                  <SelectLabel
                    id="list_id"
                    label="Trigger list"
                    obj={trigger}
                    onChange={event => this.entryListChange(index, event)}
                    options={this.listOptions()}
                    emptyVal="Select list"
                  />
                </div>
              :
                <p className="help-block">Create a contact list before selecting this trigger.</p>
              )
            :
              _.contains(['segment_entered', 'segment_left'], trigger.type) ?
                (this.segmentOptions().length ?
                  <div style={{maxWidth: '360px'}}>
                    <SelectLabel
                      id="segment_id"
                      label="Trigger segment"
                      obj={trigger}
                      onChange={event => this.entrySegmentChange(index, event)}
                      options={this.segmentOptions()}
                      emptyVal="Select segment"
                    />
                  </div>
                :
                  <p className="help-block">Create a segment before selecting this trigger.</p>
                )
              :
                <p>Contacts can be added manually from this automation or from a contact/list action.</p>
        }
      </div>
    );
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
      if (this.state.enrolmentSearchResults && this.state.enrolmentSearch.trim()) {
        await this.searchEnrolments({preventDefault: () => {}});
      }
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
      if (this.state.enrolmentSearchResults && this.state.enrolmentSearch.trim()) {
        await this.searchEnrolments({preventDefault: () => {}});
      }
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
      if (this.state.enrolmentSearchResults && this.state.enrolmentSearch.trim()) {
        await this.searchEnrolments({preventDefault: () => {}});
      }
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

  openEmailCopyModal = async () => {
    this.setState({
      showEmailCopyModal: true,
      emailCopyFilter: 'all',
      emailCopySearch: '',
    }, this.loadEmailCopySources);
  }

  closeEmailCopyModal = () => {
    if (this.state.copyingEmailSourceId) {
      return;
    }
    this.setState({showEmailCopyModal: false});
  }

  emailCopyFilterChange = event => {
    this.setState({emailCopyFilter: event.target.value}, this.loadEmailCopySources);
  }

  emailCopySearchChange = event => {
    this.setState({emailCopySearch: event.target.value});
  }

  searchEmailCopySources = event => {
    event.preventDefault();
    this.loadEmailCopySources();
  }

  loadEmailCopySources = async () => {
    this.setState({isLoadingEmailCopySources: true});
    try {
      const response = await axios.get('/api/automations/' + this.props.id + '/email-copy-sources', {
        params: {
          source_filter: this.state.emailCopyFilter,
          q: this.state.emailCopySearch.trim(),
        },
      });
      this.setState({emailCopySources: response.data});
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to load automation email sources'), 'error');
    } finally {
      this.setState({isLoadingEmailCopySources: false});
    }
  }

  createEmailFromSource = async source => {
    this.setState({copyingEmailSourceId: source.source_id});
    try {
      const email = (await axios.post('/api/automations/' + this.props.id + '/emails/from-source', {
        source_type: source.source_type,
        source_id: source.source_id,
      })).data;
      notify.show('Automation email copied', 'success');
      this.setState({showEmailCopyModal: false});
      this.props.history.push('/automations/' + this.props.id + '/emails/' + email.id);
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to copy automation email'), 'error');
    } finally {
      this.setState({copyingEmailSourceId: null});
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

  refreshPreflight = async () => {
    this.setState({isRefreshingPreflight: true});
    try {
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to refresh email sending readiness'), 'error');
    } finally {
      this.setState({isRefreshingPreflight: false});
    }
  }

  displayEnrolments(enrolments) {
    return displayAutomationEnrolments(enrolments);
  }

  impersonatedHref(path) {
    return automationImpersonatedHref(path, this.props.loggedInImpersonate);
  }

  renderEnrolmentTable(enrolments, emptyMessage) {
    const data = this.props.data;
    const displayEnrolments = this.displayEnrolments(enrolments);

    if (!displayEnrolments.length) {
      return (
        <div className="text-center space-top-sm">
          <h4>{emptyMessage}</h4>
        </div>
      );
    }

    return (
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
    );
  }

  renderNodeContactCount(node, options) {
    const opts = options || {};
    const summary = (this.props.enrolmentsData && this.props.enrolmentsData.summary) || {};
    const data = this.props.data || {};
    const nodes = (data.draft && data.draft.nodes) || [];
    const publishedNodes = (data.published && data.published.nodes) || [];
    const count = automationNodeContactCount(node, nodes, publishedNodes, summary);
    const filter = automationNodeContactFilterParam(node, nodes, publishedNodes, summary);
    const href = this.impersonatedHref(
      '/automations/' + this.props.id + '/enrolments?view=active&' + filter.key + '=' + encodeURIComponent(filter.value)
    );

    if (opts.compact) {
      return (
        <span style={{textTransform: 'none', fontWeight: 400}}>
          ({count} {count === 1 ? 'contact' : 'contacts'}
          {
            count ?
              <span>
                {', '}
                <a href={href} target="_blank" rel="noopener noreferrer">view</a>
              </span>
            :
              null
          }
          )
        </span>
      );
    }

    return (
      <div style={{minWidth: '150px'}}>
        <h4 style={{whiteSpace: 'nowrap'}}>{count} {count === 1 ? 'contact' : 'contacts'}</h4>
        <Button
          bsSize="small"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          disabled={!count}
        >
          View contacts
        </Button>
      </div>
    );
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

  renderEnrolments() {
    const data = this.props.data;
    const summary = (this.props.enrolmentsData && this.props.enrolmentsData.summary) || automationEnrolmentCounts(this.props.enrolments || []);
    const searchResults = this.state.enrolmentSearchResults;
    const searchEnrolments = (searchResults && searchResults.enrolments) || [];
    const fullActiveHref = '/automations/' + this.props.id + '/enrolments?view=active';
    const fullAllHref = '/automations/' + this.props.id + '/enrolments?view=all';

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
          <h4>
            Enrolments
            {' '}
            <span className="text-muted" style={{fontWeight: 'normal'}}>
              Active {summary.active || 0} / Enrolled {summary.enrolled || 0}
            </span>
          </h4>
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
        <div className="flex-items space-between" style={{gap: '12px', marginTop: '14px'}}>
          <form className="form-inline" onSubmit={this.searchEnrolments}>
            <FormControl
              type="email"
              value={this.state.enrolmentSearch}
              onChange={this.enrolmentSearchChange}
              placeholder="Search enrolled email"
              style={{width: '260px'}}
              disabled={this.state.isSearchingEnrolments}
            />
            {' '}
            <LoaderButton
              type="submit"
              bsStyle="default"
              text="Search"
              loadingText="Searching..."
              isLoading={this.state.isSearchingEnrolments}
              disabled={this.state.isSearchingEnrolments || !this.state.enrolmentSearch.trim()}
            />
          </form>
          <div>
            <Button href={this.impersonatedHref(fullActiveHref)} target="_blank" rel="noopener noreferrer">
              Show all active contacts
            </Button>
            {' '}
            <Button href={this.impersonatedHref(fullAllHref)} target="_blank" rel="noopener noreferrer">
              Show all enrolled contacts
            </Button>
          </div>
        </div>
        {
          searchResults ?
            <div style={{marginTop: '16px'}}>
              <p>
                Showing {searchEnrolments.length} of {searchResults.total || 0} matching enrolled contacts.
              </p>
              {this.renderEnrolmentTable(searchEnrolments, 'No enrolled contacts match that email search.')}
            </div>
          :
            null
        }
      </EDFormBox>
    );
  }

  renderEmailCopyModal() {
    const sources = this.state.emailCopySources || [];
    return (
      <Modal show={this.state.showEmailCopyModal} onHide={this.closeEmailCopyModal} bsSize="large">
        <Modal.Header closeButton>
          <Modal.Title>Copy existing email</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <form onSubmit={this.searchEmailCopySources} className="space-bottom">
            <div style={{display: 'flex', gap: '10px', flexWrap: 'wrap'}}>
              <FormControl
                componentClass="select"
                value={this.state.emailCopyFilter}
                onChange={this.emailCopyFilterChange}
                style={{width: '220px'}}
              >
                <option value="this">This automation</option>
                <option value="other">Other automations</option>
                <option value="all">All copy sources</option>
                <option value="transactional_templates">Transactional templates</option>
              </FormControl>
              <FormControl
                type="text"
                placeholder="Search by name, subject or source"
                value={this.state.emailCopySearch}
                onChange={this.emailCopySearchChange}
                style={{width: '320px', maxWidth: '100%'}}
              />
              <Button type="submit" disabled={this.state.isLoadingEmailCopySources}>
                {this.state.isLoadingEmailCopySources ? 'Searching...' : 'Search'}
              </Button>
            </div>
          </form>
          {
            this.state.isLoadingEmailCopySources ?
              <p className="text-muted">Loading email sources...</p>
            : sources.length ?
              <EDTable className="growing-margin-left" minWidth="760px">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Subject</th>
                    <th>Editor</th>
                    <th>Source</th>
                    <th>Modified</th>
                    <th></th>
                  </tr>
                </thead>
                {
                  _.map(sources, (source, index) =>
                    <EDTableRow key={source.source_id} index={index}>
                      <td><h4 style={{whiteSpace: 'nowrap'}}>{source.name}</h4></td>
                      <td><h4 style={{whiteSpace: 'nowrap'}}>{source.subject || 'No subject'}</h4></td>
                      <td><h4 style={{whiteSpace: 'nowrap'}}>{automationEditorTypeLabel(source.editor_type)}</h4></td>
                      <td>
                        <h4 style={{whiteSpace: 'nowrap'}}>
                          {source.source_label || source.source_automation_name || source.source_type}
                          {source.same_automation ? ' (this automation)' : ''}
                        </h4>
                      </td>
                      <td>
                        <h4 style={{whiteSpace: 'nowrap'}}>
                          {source.modified ? moment(source.modified).format('lll') : ''}
                        </h4>
                      </td>
                      <td className="last-cell">
                        <Button
                          bsSize="small"
                          disabled={!!this.state.copyingEmailSourceId}
                          onClick={this.createEmailFromSource.bind(this, source)}
                        >
                          {this.state.copyingEmailSourceId === source.source_id ? 'Creating...' : 'Create copy'}
                        </Button>
                      </td>
                    </EDTableRow>
                  )
                }
              </EDTable>
            :
              <p className="help-block">No automation emails match this search.</p>
          }
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={this.closeEmailCopyModal} disabled={!!this.state.copyingEmailSourceId}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    );
  }

  renderEmails() {
    const emails = this.props.emails || [];
    const busy = this.state.isCreatingEmail || this.state.deletingEmailId || this.state.duplicatingEmailId || this.state.copyingEmailSourceId;

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
            <MenuItem divider />
            <MenuItem onClick={this.openEmailCopyModal}>Copy existing email...</MenuItem>
          </DropdownButton>
        </div>
        {this.renderEmailCopyModal()}
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

  renderPreflightMessages(messages, className) {
    if (!messages || !messages.length) {
      return null;
    }
    return (
      <ul className={className} style={{marginBottom: 0}}>
        {_.map(messages, (message, index) =>
          <li key={message.code + '-' + index}>{message.message}</li>
        )}
      </ul>
    );
  }

  renderPreflight() {
    const preflight = this.props.preflightData;
    if (!preflight) {
      return (
        <EDFormBox space>
          <div className="flex-items space-between">
            <h4>Email sending readiness</h4>
            <Button onClick={this.refreshPreflight} disabled={this.state.isRefreshingPreflight}>
              Refresh
            </Button>
          </div>
          <p className="text-muted">Email sending readiness has not loaded yet.</p>
        </EDFormBox>
      );
    }

    const errors = preflight.errors || [];
    const warnings = preflight.warnings || [];
    const info = preflight.info || [];
    const nodes = preflight.nodes || [];
    const route = preflight.route || {};
    let statusText = 'Ready';
    let statusClass = 'text-success';
    if (errors.length) {
      statusText = 'Errors';
      statusClass = 'text-danger';
    } else if (warnings.length) {
      statusText = 'Warnings';
      statusClass = 'text-warning';
    }

    return (
      <EDFormBox space>
        <div className="flex-items space-between">
          <h4>
            Email sending readiness
            {' '}
            <span className={statusClass} style={{fontWeight: 'normal'}}>
              {statusText}
            </span>
          </h4>
          <Button onClick={this.refreshPreflight} disabled={this.state.isRefreshingPreflight}>
            {this.state.isRefreshingPreflight ? 'Refreshing...' : 'Refresh'}
          </Button>
        </div>
        <p className="text-muted">
          Checking saved {preflight.mode || 'draft'} send-email configuration.
        </p>
        {
          route.status ?
            <p>
              Route: {route.route_name || route.route_id || route.status}
              {' '}
              <span className="text-muted">({route.status})</span>
            </p>
          :
            null
        }
        {this.renderPreflightMessages(errors, 'text-danger')}
        {this.renderPreflightMessages(warnings, 'text-warning')}
        {this.renderPreflightMessages(info, 'text-muted')}
        {
          nodes.length ?
            <EDTable className="growing-margin-left" minWidth="600px" maxWidth="1024px">
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Email</th>
                  <th>Subject</th>
                  <th>Status</th>
                </tr>
              </thead>
              {
                _.map(nodes, (node, index) => {
                  const nodeErrors = node.errors || [];
                  const nodeWarnings = node.warnings || [];
                  return (
                    <EDTableRow key={node.node_id || index} index={index}>
                      <td>{node.step}</td>
                      <td>{node.email_name || node.automation_email_id || 'Missing email'}</td>
                      <td>{node.subject || 'No subject'}</td>
                      <td>
                        {
                          nodeErrors.length ?
                            this.renderPreflightMessages(nodeErrors, 'text-danger')
                          : nodeWarnings.length ?
                            this.renderPreflightMessages(nodeWarnings, 'text-warning')
                          :
                            <span className="text-success">Ready</span>
                        }
                      </td>
                    </EDTableRow>
                  );
                })
              }
            </EDTable>
          :
            <p className="help-block">This workflow has no send-email nodes.</p>
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
    const filteredContacts = filterAutomationHistoryContacts(contacts, this.state.historyContactSearch);
    const sortedContacts = sortAutomationHistoryContacts(filteredContacts, this.state.historyContactSort);
    const contactPage = paginateAutomationHistoryContacts(sortedContacts, this.state.historyContactPage, 50);
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
              <div className="flex-items space-between" style={{marginBottom: '12px', gap: '12px'}}>
                <div style={{width: '360px', maxWidth: '100%'}}>
                  <FormControl
                    type="text"
                    placeholder="Search contacts by email"
                    value={this.state.historyContactSearch}
                    onChange={this.historyContactSearchChange}
                  />
                </div>
                <div style={{width: '220px', maxWidth: '100%'}}>
                  <FormControl
                    componentClass="select"
                    value={this.state.historyContactSort}
                    onChange={this.historyContactSortChange}
                  >
                    <option value="recent_desc">Most recent first</option>
                    <option value="recent_asc">Oldest first</option>
                    <option value="email_asc">Email A-Z</option>
                    <option value="email_desc">Email Z-A</option>
                  </FormControl>
                </div>
                <div className="text-right" style={{paddingTop: '8px'}}>
                  <span>
                    {
                      filteredContacts.length ?
                        'Showing ' + (((contactPage.page - 1) * contactPage.pageSize) + 1) + '-' + (((contactPage.page - 1) * contactPage.pageSize) + contactPage.contacts.length) + ' of ' + filteredContacts.length + ' contacts'
                      :
                        'Showing 0 contacts'
                    }
                  </span>
                </div>
              </div>
              {
                contactPage.contacts.length ?
                  <PanelGroup accordion id="automation-history-contacts-accordion">
                    {
                      _.map(contactPage.contacts, (contact, contactIndex) =>
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
                  <p>{this.state.historyContactSearch ? 'No contacts match that email search.' : 'No automation history yet.'}</p>
              }
              {
                contactPage.totalPages > 1 ?
                  <div className="flex-items space-between" style={{marginTop: '12px', marginBottom: '16px'}}>
                    <Button
                      bsSize="small"
                      disabled={contactPage.page <= 1}
                      onClick={this.historyContactPageChange.bind(this, contactPage.page - 1)}
                    >
                      Previous
                    </Button>
                    <span>Page {contactPage.page} of {contactPage.totalPages}</span>
                    <Button
                      bsSize="small"
                      disabled={contactPage.page >= contactPage.totalPages}
                      onClick={this.historyContactPageChange.bind(this, contactPage.page + 1)}
                    >
                      Next
                    </Button>
                  </div>
                :
                  null
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
        onBack={this.goBack} buttons={this.navbarButtons()} id={this.props.id}
        loggedInImpersonate={this.props.loggedInImpersonate}>
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
              {_.map(entryTriggers(data.entry), (trigger, index, triggers) => this.renderEntryTrigger(trigger, index, triggers.length))}
              <DropdownButton
                id="add-entry-trigger"
                title="Add trigger"
              >
                {_.map(triggerOptions(), option =>
                  <MenuItem key={option.id} onClick={() => this.addEntryTrigger(option.id)}>
                    {option.name}
                  </MenuItem>
                )}
              </DropdownButton>
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
            {this.renderPreflight()}
            <AutomationWorkflowEditor
              nodes={nodes}
              emails={this.props.emails || []}
              lists={this.props.lists || []}
              tags={this.props.tags || []}
              entryTags={entryTagValues(data.entry)}
              update={this.props.update}
              renderNodeContactCount={this.renderNodeContactCount.bind(this)}
            />
            {this.renderEnrolments()}
            {canViewAutomationDiagnostics(this.props) ? this.renderHistory() : null}
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
    segments: async () => _.sortBy((await axios.get('/api/segments')).data, s => (s.name || '').toLowerCase()),
    enrolmentsData: async ({id}) => (await axios.get('/api/automations/' + id + '/enrolments?summary=true')).data,
    preflightData: async ({id}) => (await axios.get('/api/automations/' + id + '/preflight?mode=draft')).data,
    historyData: async ({id, user, loggedInImpersonate}) => {
      if (!canViewAutomationDiagnostics({user, loggedInImpersonate})) {
        return {enrolments: [], events: []};
      }
      return (await axios.get('/api/automations/' + id + '/history')).data;
    },
  },
});
