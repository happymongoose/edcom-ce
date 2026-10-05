import React from 'react';
import { FormControl } from 'react-bootstrap';
import moment from 'moment';

const units = ['days', 'hours', 'minutes'];

// Shared local editing validation; the backend validates executable settings at publish.
export function automationWaitError(duration, waitUntil) {
  if (waitUntil !== undefined) return typeof waitUntil === 'string' && waitUntil.includes('T') &&
    /(?:Z|[+-]\d{2}:?\d{2})$/.test(waitUntil) && moment(waitUntil, moment.ISO_8601, true).isValid() ? '' : 'Choose a valid date and time.';
  const values = units.map(unit => (duration || {})[unit]);
  if (values.some(value =>
    !/^[0-9]+$/.test(String(value)) || !isFinite(Number(value)) ||
    Math.floor(Number(value)) !== Number(value)
  )) {
    return 'Days, hours and minutes must be nonnegative whole numbers.';
  }
  const total = Number(values[0]) * 24 * 60 + Number(values[1]) * 60 + Number(values[2]);
  if (total < 5) {
    return 'Wait must be at least 5 minutes.';
  }
  if (total > 365 * 24 * 60) {
    return 'Wait cannot exceed 365 days.';
  }
  return '';
}

export function automationWaitInstant(value) {
  const date = moment(value, 'YYYY-MM-DDTHH:mm', true);
  // Do not silently move a nonexistent local time forward across a DST gap.
  return date.isValid() && date.format('YYYY-MM-DDTHH:mm') === value ? date.toISOString() : '';
}

export function withAutomationWait(node, values) {
  const result = {...node}; delete result.duration; delete result.wait_until;
  if (values.wait_until !== undefined) result.wait_until = values.wait_until;
  else result.duration = {days: Number(values.duration.days), hours: Number(values.duration.hours), minutes: Number(values.duration.minutes)};
  return result;
}

export default function AutomationWaitFields({duration, waitUntil, onModeChange, onDateChange, onChange, idPrefix, invalid}) {
  const until = waitUntil !== undefined;
  return (
    <div>
      <FormControl componentClass="select" style={{marginBottom: 15}} id={idPrefix + '-mode'} aria-label="Wait mode" value={until ? 'until' : 'duration'} onChange={event => onModeChange(event.target.value)}>
        <option value="duration">Wait for a duration</option><option value="until">Wait until a date and time</option>
      </FormControl>
      {until ? <div>
        <FormControl type="datetime-local" aria-label="Wait until" id={idPrefix + '-until'}
          aria-invalid={invalid || undefined} aria-describedby={invalid ? idPrefix + '-error' : undefined}
          value={moment(waitUntil, moment.ISO_8601, true).isValid() ? moment(waitUntil).format('YYYY-MM-DDTHH:mm') : ''}
          onChange={event => onDateChange(automationWaitInstant(event.target.value))} />
        <p className="help-block">Time zone: {Intl.DateTimeFormat().resolvedOptions().timeZone || 'your browser time zone'}. Saved as an exact instant. Contacts reaching a passed deadline continue immediately.</p>
        {waitUntil && <p className="help-block">Selected deadline: {moment(waitUntil).format('YYYY-MM-DD HH:mm Z')}</p>}
      </div> : <div className="form-inline" style={{minWidth: '280px'}}>{units.map(unit => (
        <span key={unit}>
          <FormControl
            id={idPrefix + '-' + unit}
            type="number"
            min="0"
            step="1"
            aria-label={unit}
            aria-invalid={invalid || undefined}
            aria-describedby={invalid ? idPrefix + '-error' : undefined}
            value={(duration || {})[unit] === undefined ? '' : duration[unit]}
            onChange={event => onChange(unit, event.target.value)}
            style={{width: '70px'}}
          />
          {' '}{unit}{' '}
        </span>
      ))}</div>}
    </div>
  );
}
