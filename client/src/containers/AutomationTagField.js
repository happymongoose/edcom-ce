import React, { Component } from 'react';
import $ from 'jquery';
import Select2 from 'react-select2-wrapper';
import fixTag from '../utils/fixtag';

export function automationTagError(tag) {
  if (typeof tag !== 'string' || !tag.trim()) return 'Select or create a tag.';
  if (tag.length > 1024) return 'Tags cannot exceed 1024 characters.';
  return '';
}

export default class AutomationTagField extends Component {
  state = {ready: false}

  componentDidMount() {
    // Initialize after the parent element exists. Keep options stable because
    // the installed wrapper reinitializes Select2 when options change.
    this.options = {
      placeholder: this.props.placeholder || 'Select or create tag',
      tags: true,
      createTag: params => {
        const fixed = fixTag(params.term);
        return fixed ? {id: fixed, text: fixed} : null;
      },
    };
    if (this.props.inModal) this.options.dropdownParent = $(this.container);
    this.setState({ready: true});
  }

  componentDidUpdate() {
    // Select2 hides the native select; label its visible keyboard control too.
    $(this.container).find('[role="combobox"]').attr({
      'aria-label': 'Tag',
      'aria-invalid': this.props.invalid ? 'true' : null,
      'aria-describedby': this.props.invalid ? this.props.id + '-error' : null,
    });
  }

  render() {
    const {value, data, onChange, id, invalid} = this.props;
    // Single-select placeholders require a blank option; otherwise an empty
    // draft can display the first available tag as if it were selected.
    const options = [{id: '', text: ''}].concat(data || []);
    if (value && !options.some(option => option.id === value)) {
      options.push({id: value, text: value});
    }
    return (
      <div ref={element => { this.container = element; }}>
        {this.state.ready && <Select2
          id={id}
          disabled={!!this.props.disabled}
          data={options}
          value={value || ''}
          onOpen={() => $(this.container).find('.select2-search__field').attr('aria-label', 'Search or create tag')}
          onSelect={event => {
            onChange(event.params.data.id);
            if (this.props.clearAfterSelect) $(this.container).find('select').val('').trigger('change.select2');
          }}
          style={{width: '100%'}}
          options={this.options}
          aria-label="Tag"
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? id + '-error' : undefined}
        />}
      </div>
    );
  }
}
