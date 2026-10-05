import React from 'react';
import { SelectLabel } from '../components/FormControls';

// The page supplies account-scoped lists. Never coerce a stored reference into
// a different option; backend ownership and publish validation remain authoritative.
export function automationListSelectionError(value, options) {
  if (!value) return 'Select a contact list.';
  if (typeof value !== 'string' || (options || []).filter(option => option.id === value).length !== 1) {
    return 'The selected list is not available. Select a valid replacement.';
  }
  return '';
}

export const automationLists = node => node.list_ids !== undefined ? node.list_ids : [node.list_id === undefined ? '' : node.list_id];
export function withAutomationLists(node, ids) {
  const result = {...node};
  delete result.list_id; delete result.list_ids;
  if (ids.length === 1) result.list_id = ids[0];
  else result.list_ids = ids;
  return result;
}
export function automationListsError(ids, options) {
  if (!ids.length) return 'Select a contact list.';
  if (ids.length > 100) return 'Select up to 100 contact lists.';
  if (new Set(ids).size !== ids.length) return 'Select each list only once.';
  return ids.map(value => automationListSelectionError(value, options)).find(Boolean) || '';
}

export default function AutomationListField({id, value, options, onChange, invalid, multiple}) {
  if (multiple) {
    const ids = value.length ? value : [''];
    return <div>
      {ids.map((selected, index) => <div key={index} style={{display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8}}>
        <AutomationListField id={index ? id + '-' + index : id} value={selected} options={options} invalid={invalid}
          onChange={event => onChange(ids.map((item, i) => i === index ? event.target.value : item))} />
        {ids.length > 1 && <button type="button" className="btn btn-default btn-xs" aria-label={'Remove selected list ' + (index + 1)}
          onClick={() => onChange(ids.filter((_, i) => i !== index))}>Remove</button>}
      </div>)}
      {ids.length < 100 && <button type="button" className="btn btn-default btn-xs" onClick={() => onChange(ids.concat(''))}>Add another list</button>}
    </div>;
  }
  const choices = options || [];
  const missing = value !== undefined && value !== null && value !== '' &&
    (typeof value !== 'string' || !choices.some(option => option.id === value));
  // The empty display option cannot collide with a real ID. The caller keeps
  // the exact missing reference until the user changes the selection.
  return (
    <div style={{minWidth: '220px'}}>
      <SelectLabel
        id={id}
        label="Contact list"
        aria-label="Contact list"
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? id + '-error' : undefined}
        obj={{[id]: missing ? '' : value || ''}}
        onChange={onChange}
        options={choices}
        emptyVal={missing ? 'Selected list not found' : 'Select list'}
      />
      {!choices.length && <p className="help-block">No contact lists are available.</p>}
    </div>
  );
}
