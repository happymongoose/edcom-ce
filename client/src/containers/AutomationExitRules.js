import React, {Component} from 'react';
import {Button, FormControl, Modal} from 'react-bootstrap';
import AutomationTagsField, {automationTagsError} from './AutomationTagsField';
import AutomationListField, {automationListsError} from './AutomationListField';
import fixTag from '../utils/fixtag';

export const exitRuleTypes = [
  {id: 'has_tag', name: 'Has any of these tags'},
  {id: 'missing_tag', name: 'Has none of these tags'},
  {id: 'in_list', name: 'Is in any of these lists'},
  {id: 'not_in_list', name: 'Is in none of these lists'},
];
const tagged = type => ['has_tag', 'missing_tag'].includes(type);
export function exitRuleError(rule, lists) {
  if (!exitRuleTypes.some(item => item.id === rule.type)) return 'Choose an exit rule.';
  return tagged(rule.type) ? automationTagsError(rule.tags || []) : automationListsError(rule.list_ids || [], lists);
}
export function exitRuleSummary(rule, lists) {
  const option = exitRuleTypes.find(item => item.id === rule.type);
  const values = tagged(rule.type) ? rule.tags || [] : (rule.list_ids || []).map(id => {
    const list = lists.find(item => item.id === id);
    return list ? list.name : 'Selected list not found (' + id + ')';
  });
  return (option ? option.name : 'Unsupported rule') + ': ' + values.join(', ');
}

export default class AutomationExitRules extends Component {
  state = {edit: null, error: ''};
  open = index => {
    if (this.props.disabled) return;
    const value = this.props.value || [];
    this._original = JSON.stringify(value);
    this.setState({edit: {index, rule: index === null ? {type: '', tags: []} : JSON.parse(JSON.stringify(value[index]))}, error: ''});
    this.props.onEditingChange(true);
  }
  close = () => {
    this.setState({edit: null, error: ''});
    this.props.onEditingChange(false);
  }
  change = rule => this.setState({edit: {...this.state.edit, rule}, error: ''});
  save = () => {
    if (!this.state.edit || this.props.disabled) return;
    if (this._original !== JSON.stringify(this.props.value || [])) {
      this.setState({error: 'Exit rules changed while this editor was open. Cancel and reopen the rule.'}); return;
    }
    const {index, rule} = this.state.edit;
    const error = exitRuleError(rule, this.props.lists);
    if (error) {this.setState({error}); return;}
    const value = (this.props.value || []).slice();
    if (index === null) {if (value.length >= 20) return; value.push(rule);} else value[index] = rule;
    this.props.onChange(value); this.close();
  }
  render() {
    const {value = [], lists = [], tags = [], disabled} = this.props;
    const {edit, error} = this.state;
    return <div>
      <h4>Exit rules</h4>
      <p>Contacts exit and cannot enter while <strong>any</strong> rule matches. Changes take effect when you publish.</p>
      {!value.length && <p className="help-block">No exit rules.</p>}
      {value.map((rule, index) => <div key={index} className="form-group">
        <strong>{exitRuleSummary(rule, lists)}</strong>{' '}
        <Button bsSize="small" disabled={disabled} onClick={() => this.open(index)}>Edit rule {index + 1}</Button>{' '}
        <Button bsSize="small" disabled={disabled} onClick={() => this.props.onChange(value.filter((_, i) => i !== index))}>Remove rule {index + 1}</Button>
      </div>)}
      <Button disabled={disabled || value.length >= 20} onClick={() => this.open(null)}>Add exit rule</Button>
      <p className="help-block">Removing a tag or changing list membership can restore eligibility; it does not restart an exited enrolment. Entry triggers and Enter once / Enter multiple times still apply.</p>
      <Modal show={!!edit} onHide={this.close} aria-labelledby="exit-rule-title">
        <Modal.Header closeButton><Modal.Title id="exit-rule-title">Exit and exclude contact</Modal.Title></Modal.Header>
        <Modal.Body>
          {edit && <div>
            <label htmlFor="exit-rule-type">Rule</label>
            <FormControl componentClass="select" id="exit-rule-type" value={edit.rule.type}
              onChange={event => this.change(tagged(event.target.value) ? {type: event.target.value, tags: []} : {type: event.target.value, list_ids: []})}>
              <option value="">Choose a rule</option>
              {exitRuleTypes.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
            </FormControl>
            {edit.rule.type && <div style={{marginTop: 16}}>
              {tagged(edit.rule.type) ? <AutomationTagsField id="exit-rule-tags" inModal value={edit.rule.tags || []} data={tags}
                onChange={values => this.change({...edit.rule, tags: Array.from(new Set(values.map(fixTag).filter(Boolean)))})} /> :
                <AutomationListField id="exit-rule-lists" multiple value={edit.rule.list_ids || []} options={lists}
                  onChange={list_ids => this.change({...edit.rule, list_ids})} />}
            </div>}
            {['missing_tag', 'not_in_list'].includes(edit.rule.type) && <p className="help-block">This also matches contacts who never had any of the selected tags or list memberships.</p>}
            <p className="help-block">Matching contacts exit even while paused. An email already in flight may finish; future steps stop. Tag/list changes are checked through background processing, with another check before execution.</p>
          </div>}
          {error && <div className="alert alert-danger" role="alert">{error}</div>}
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={this.close}>Cancel</Button>
          <Button bsStyle="primary" disabled={!edit || disabled || !!exitRuleError(edit.rule, lists)} onClick={this.save}>Save rule</Button>
        </Modal.Footer>
      </Modal>
    </div>;
  }
}
