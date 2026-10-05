import React, {Component} from 'react';
import {Button} from 'react-bootstrap';

// A bounded search result list over presentation records, never a second workflow.
export default class AutomationStepFinder extends Component {
  state = {open: false, query: '', filter: 'all', error: ''};
  close = () => this.setState({open: false, error: ''}, () => this.trigger.focus());
  render() {
    const {open, query, filter, error} = this.state;
    const matches = open ? this.props.getItems().filter(item => {
      if (filter === 'contacts' && !(typeof item.count === 'number' && item.count > 0)) return false;
      if (filter === 'warnings' && !item.warning) return false;
      if (filter === 'other' && !item.detached) return false;
      return [item.label, item.type, item.summary, item.id, 'step ' + item.step].join(' ').toLowerCase().includes(query.trim().toLowerCase());
    }) : [];
    return <div className="automation-step-finder" onKeyDown={event => {
      if (event.key === 'Escape' || event.keyCode === 27) {event.stopPropagation(); this.close();}
    }}>
      <button type="button" className="btn btn-default btn-xs" ref={element => {this.trigger = element;}}
        aria-expanded={open} onClick={() => open ? this.close() : this.setState({open: true}, () => this.search.focus())}>Find step</button>
      {open && <section aria-label="Find draft step" className="automation-step-search">
        <div className="automation-step-search-fields">
          <input type="search" aria-label="Search draft steps" placeholder="Label, type or ID" value={query}
            ref={element => {this.search = element;}} onChange={event => this.setState({query: event.target.value, error: ''})} />
          <select aria-label="Filter draft steps" value={filter} onChange={event => this.setState({filter: event.target.value, error: ''})}>
            <option value="all">All draft steps</option>
            <option value="contacts">With live contacts</option>
            <option value="warnings">Needs attention</option>
            <option value="other">Outside expanded path</option>
          </select>
          <Button bsSize="xsmall" onClick={this.close}>Close</Button>
        </div>
        <p role="status">{matches.length} matching draft {matches.length === 1 ? 'step' : 'steps'}{matches.length > 50 ? ' · Showing the first 50; narrow your search.' : ''}</p>
        {filter === 'warnings' && <p>Frontend checks only. Publishing performs the full validation.</p>}
        {error && <p role="alert">{error}</p>}
        <ul>{matches.slice(0, 50).map(item => <li key={item.id}>
          <button type="button" disabled={item.ambiguous} data-find-node-id={item.id} onClick={() => {
            const message = this.props.onJump(item.id);
            if (message) this.setState({error: message});
            else this.setState({open: false, error: ''});
          }}>
            <strong>Draft step {item.step} · {item.label}</strong> · {item.type}
            <small>{item.id} · {typeof item.count === 'number' ? item.count + ' live contacts' : 'Live count unavailable'}{item.detached ? ' · Outside expanded path' : ''}</small>
            {item.summary && <small>{item.summary}</small>}
            {item.warning && <small className="text-danger">{item.warning}</small>}
          </button>
        </li>)}</ul>
      </section>}
    </div>;
  }
}
