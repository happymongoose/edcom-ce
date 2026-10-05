import React from 'react';
import AutomationTagField, {automationTagError} from './AutomationTagField';

export const automationTags = node => node.draft_tags || [node.draft_tag || ''];
export function withAutomationTags(node, tags) {
  const result = {...node};
  delete result.draft_tag; delete result.draft_tags;
  if (tags.length === 1) result.draft_tag = tags[0];
  else result.draft_tags = tags;
  return result;
}
export function automationTagsError(tags) {
  if (!tags.length) return 'Select or create a tag.';
  if (tags.length > 100) return 'Select up to 100 tags per step.';
  const invalid = tags.map(automationTagError).find(Boolean);
  if (invalid) return invalid;
  return new Set(tags).size !== tags.length ? 'Select each tag only once.' : '';
}
export default function AutomationTagsField({value, onChange, ...props}) {
  const tags = value.filter(Boolean);
  return <div>
    <p className="text-center">To create a new tag, type it into the input box and hit enter.</p>
    <div className="campaign_box automation-tags-box">
      <div className="automation-tags-picker">
        <AutomationTagField {...props} value="" clearAfterSelect placeholder="Add or Create Tag" disabled={tags.length >= 100}
          data={(props.data || []).filter(option => !tags.includes(option.id))}
          onChange={tag => {if (tag && !tags.includes(tag) && tags.length < 100) onChange(tags.concat(tag));}} />
      </div>
      <div className="form-group form_style"><label>Tags</label></div>
      {!tags.length && <p>None Selected</p>}
      {tags.length >= 100 && <p className="help-block">Maximum 100 tags per step. Remove a tag to add another.</p>}
      <ul className="list-inline color_tag">
        {tags.map((tag, index) => <li key={index}>
          <button type="button" className="gray_tag" aria-label={'Remove tag ' + tag}
            title="Remove from this step" onClick={() => onChange(tags.filter((_, i) => i !== index))}>{tag}</button>
        </li>)}
      </ul>
      <span className="sr-only">Select a tag to add it. Click a selected tag to remove it from this step.</span>
    </div>
  </div>;
}
