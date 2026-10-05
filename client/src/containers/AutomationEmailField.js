import React from 'react';
import { SelectLabel } from '../components/FormControls';

// Options come from the page's account/automation-scoped email endpoint.
// This checks the loaded list, not backend ownership or send readiness.
export function automationEmailSelectionError(value, options) {
  if (!value) return 'Select an automation email.';
  if ((options || []).filter(option => option.id === value).length !== 1) {
    return 'The selected email is not available in this automation. Select a valid replacement.';
  }
  return '';
}

export default function AutomationEmailField({id, value, options, onChange, invalid}) {
  const choices = options || [];
  const missing = value && !choices.some(option => option.id === value);
  return (
    <div style={{minWidth: '260px'}}>
      <SelectLabel
        id={id}
        label="Automation email"
        aria-label="Automation email"
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? id + '-error' : undefined}
        obj={{[id]: value || ''}}
        onChange={onChange}
        options={missing ? [{id: value, name: 'Selected email not found'}].concat(choices) : choices}
        emptyVal="Select email"
      />
      {!choices.length && <p className="help-block">No automation emails are available. Manage emails in the automation email library.</p>}
    </div>
  );
}
