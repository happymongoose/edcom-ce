import React from 'react';
import { SelectLabel } from '../components/FormControls';

// The account-scoped collection is loaded once by the page. These are local
// eligibility checks only; publish and runtime remain authoritative.
export function automationTargetOptions(automations, sourceId, action = 'enrol_automation') {
  return (automations || []).filter(automation =>
    typeof automation.id === 'string' && automation.id && automation.id !== sourceId &&
    ['published', 'paused'].includes(automation.status) &&
    (action === 'remove_automation' ? automation.published && typeof automation.published === 'object' && Object.keys(automation.published).length :
      Array.isArray((automation.published || {}).nodes) && automation.published.nodes.length)
  ).map(automation => ({
    id: automation.id,
    name: (automation.name || 'Untitled automation') + (automation.status === 'paused' ? ' (paused)' : ''),
  })).sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

export function automationTargetError(value, options) {
  if (!value) return 'Select an automation.';
  if (typeof value !== 'string' || (options || []).filter(option => option.id === value).length !== 1) {
    return 'The selected automation is unavailable. Choose another published automation in this account.';
  }
  return '';
}

export function automationTargetSummary(value, options) {
  const matches = (options || []).filter(option => option.id === value);
  return !value ? 'No automation selected' : matches.length === 1 ? matches[0].name : 'Selected automation unavailable';
}

export default function AutomationTargetField({id, value, options, onChange, invalid, action = 'enrol_automation'}) {
  const choices = options || [];
  const missing = value && automationTargetError(value, choices);
  return <div style={{minWidth: '260px'}}>
    <SelectLabel id={id} label="Automation" aria-label={action === 'remove_automation' ? 'Automation to remove from' : 'Automation to enrol in'}
      aria-invalid={invalid || undefined} aria-describedby={invalid ? id + '-error' : undefined}
      obj={{[id]: value || ''}} onChange={onChange} emptyVal="Select automation"
      options={missing ? [{id: value, name: 'Selected automation unavailable'}].concat(choices.filter(option => option.id !== value)) : choices} />
    {!choices.length && <p className="help-block">No other published automations are available in this account.</p>}
    {action === 'remove_automation' ? <div>
      <p className="help-block">Ends this contact’s active or paused enrolments in the selected automation; this automation continues. Completed history stays unchanged. If the contact is not enrolled, this step simply continues.</p>
      <p className="help-block">If a target action is running, this step is held for review until it can be retried safely.</p>
    </div> : <p className="help-block">Starts an additional enrolment; this automation continues. The target’s re-entry rules apply. A paused target holds new contacts until resumed.</p>}
  </div>;
}
