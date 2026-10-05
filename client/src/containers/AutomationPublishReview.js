import React, { Component } from 'react';
import { Button, FormControl, Modal } from 'react-bootstrap';
import axios from 'axios';
import shortid from 'shortid';
import notify from '../utils/notify';

// A local change detector, not a replacement for the server's review fingerprints.
function stableJSON(value) {
  return JSON.stringify(value, (key, item) => {
    if (!item || Array.isArray(item) || typeof item !== 'object') return item;
    return Object.keys(item).sort().reduce((result, name) => ({...result, [name]: item[name]}), {});
  });
}

function inputIdentity(data) {
  return stableJSON({name: data.name, entry: data.entry, reentry: data.reentry || 'once', draft: data.draft, exit_rules: data.exit_rules || []});
}

function errorText(error, fallback) {
  const data = error && error.response && error.response.data;
  return (data && (data.description || data.title)) || fallback;
}

function validChoice(choice, destinations) {
  return choice && (choice.action === 'exit' || (choice.action === 'move' &&
    destinations.some(node => node.node_id === choice.destination_node_id)));
}

function nodeLabel(node) {
  return (node.label || node.type) + ' (' + node.node_id + ')';
}

export default class AutomationPublishReview extends Component {
  state = {phase: 'idle', impact: null, choices: {}, error: '', success: ''};
  _run = 0;
  _active = false;
  _busy = false;
  _requestBody = null;
  _reloadBeforeReview = false;
  _invalidated = false;

  componentWillUnmount() {
    this._unmounted = true;
  }

  componentDidUpdate() {
    if (this._active && !this._refreshingInputs && !this._invalidated &&
        !['reloading', 'reload_failed'].includes(this.state.phase) &&
        this._inputs !== inputIdentity(this.props.data)) {
      this._invalidated = true;
      // A submitted operation must still be resolved using its original payload.
      if (!['submitting', 'uncertain'].includes(this.state.phase)) {
        this.setState({phase: 'invalidated', choices: {}, error:
          'The automation changed while this review was open. Close this review, then Publish again to save and assess the current draft.'});
      }
    }
  }

  begin = async () => {
    if (this._active || this._busy || this.props.isSaving) return;
    const run = ++this._run;
    this._active = true;
    this._busy = true;
    this._invalidated = false;
    this._reloadBeforeReview = false;
    this._requestBody = null;
    this._wasUncertain = false;
    this._inputs = inputIdentity(this.props.data);
    this.setState({phase: 'saving', impact: null, choices: {}, error: '', success: ''});
    this.props.onActiveChange(true);
    const saved = await this.props.save();
    if (this._unmounted || run !== this._run) return;
    this._busy = false;
    if (!saved) {
      this.finish();
      return;
    }
    if (this._invalidated || this._inputs !== inputIdentity(this.props.data)) {
      this.setState({phase: 'invalidated', error: 'The draft changed during saving. Close this review and Publish again.'});
      return;
    }
    await this.assess(true);
  }

  finish = () => {
    this._run++;
    this._busy = false;
    this._active = false;
    this._requestBody = null;
    this.setState({phase: 'idle', impact: null, choices: {}, error: '', success: ''});
    this.props.onActiveChange(false);
  }

  close = () => {
    if (this._refreshingInputs || ['submitting', 'uncertain', 'reloading', 'reload_failed'].includes(this.state.phase)) return;
    const saving = this.state.phase === 'saving';
    this.finish();
    notify.show(saving ?
      'Publication cancelled. The draft save is still finishing; live publication was not changed.' : this._wasUncertain ?
      'Review closed. An earlier publication response was uncertain; reload to check the live status.' :
      'Draft saved. Live publication was not changed by this review.', 'success');
  }

  assess = async (publishIfClear = false) => {
    if (this._busy || (this._invalidated && !this._reloadBeforeReview)) return;
    const run = this._run;
    this._busy = true;
    this._requestBody = null;
    const previous = this.state.impact;
    const previousChoices = this.state.choices;
    let publishClear = false;
    this._refreshingInputs = this._reloadBeforeReview;
    this.setState({phase: 'assessing', error: ''});
    try {
      if (this._reloadBeforeReview) {
        // Reload authoritative saved inputs before reviewing a changed workflow.
        await this.props.reload();
        if (this._unmounted || run !== this._run) return;
        this._inputs = inputIdentity(this.props.data);
        this._invalidated = false;
        this._reloadBeforeReview = false;
        this._refreshingInputs = false;
      }
      const impact = (await axios.get('/api/automations/' + this.props.id + '/publish-impact')).data;
      if (this._unmounted || run !== this._run || this._invalidated) return;
      const sameReview = previous && stableJSON(previous.review) === stableJSON(impact.review);
      const choices = Object.create(null);
      if (sameReview) {
        impact.sources.forEach(source => {
          const choice = previousChoices[source.node_id];
          if (validChoice(choice, impact.destinations)) choices[source.node_id] = choice;
        });
      }
      await new Promise(resolve => this.setState({phase: 'review', impact, choices, error: ''}, resolve));
      publishClear = publishIfClear === true && !impact.sources.length && !impact.blockers.length && !impact.exit_review_required;
    } catch (error) {
      if (!this._unmounted && run === this._run && (!this._invalidated || this._reloadBeforeReview)) {
        this._refreshingInputs = false;
        this.setState({phase: 'assessment_failed', error: errorText(error, 'Unable to assess publication. Nothing was published.')});
      }
    } finally {
      if (run === this._run) {
        this._busy = false;
        this._refreshingInputs = false;
      }
    }
    if (publishClear && !this._unmounted && run === this._run) await this.submit();
  }

  choose = (sourceId, choice) => {
    if (this._busy || this.state.phase !== 'review') return;
    const choices = Object.assign(Object.create(null), this.state.choices);
    choices[sourceId] = choice;
    this.setState({choices});
  }

  canSubmit() {
    const {impact, choices, phase} = this.state;
    return this._active && phase === 'review' && !this._invalidated && impact && !impact.blockers.length &&
      impact.sources.every(source => validChoice(choices[source.node_id], impact.destinations));
  }

  submit = async () => {
    if (this._busy || !this.canSubmit()) return;
    if (this._inputs !== inputIdentity(this.props.data)) {
      this._invalidated = true;
      this.setState({phase: 'invalidated', choices: {}, error: 'The draft changed. Close this review and Publish again.'});
      return;
    }
    const resolutions = Object.create(null);
    this.state.impact.sources.forEach(source => { resolutions[source.node_id] = this.state.choices[source.node_id]; });
    // Retain the exact serialized request for an uncertain response, including its ID.
    this._requestBody = JSON.stringify({
      request_id: shortid.generate(), review: this.state.impact.review, resolutions,
      ...(this.state.impact.exit_review_required ? {accept_exit_rules: true} : {}),
    });
    await this.send();
  }

  send = async () => {
    if (this._busy || !this._requestBody) return;
    this._busy = true;
    this.setState({phase: 'submitting', error: ''});
    try {
      const result = (await axios.post('/api/automations/' + this.props.id + '/publish',
        this._requestBody, {headers: {'Content-Type': 'application/json'}})).data;
      if (this._unmounted) return;
      const receipt = result.publication_receipt;
      const outcomes = (receipt && receipt.outcomes) || [];
      const total = action => outcomes.filter(item => item.action === action)
        .reduce((sum, item) => sum + item.enrolment_count, 0);
      const success = 'Automation published.' +
        (receipt && receipt.rule_exit_count ? ' ' + receipt.rule_exit_count + ' enrolments exited by rule.' : '') +
        (outcomes.length ? ' ' + total('move') + ' enrolments moved; ' + total('exit') + ' exited immediately.' : '') +
        (total('follow') ? ' ' + total('follow') + ' followed moved steps with progress preserved.' : '') +
        (result.status === 'paused' ? ' Automation remains paused.' : '');
      this.setState({phase: 'reloading', success});
      this._requestBody = null;
      this._busy = false;
      await this.reloadAfterSuccess();
    } catch (error) {
      if (this._unmounted) return;
      const status = error.response && error.response.status;
      if (!status || status >= 500 || status === 408) {
        this._wasUncertain = true;
        this.setState({phase: 'uncertain', error:
          'The publication result is unknown. It may have committed. Retry the same request to find out; do not start another publication.'});
      } else {
        const title = error.response.data && error.response.data.title;
        this._reloadBeforeReview = title === 'Automation publish review is stale' ||
          title === 'Publication request ID was already used';
        this.setState({
          phase: this._invalidated && !this._reloadBeforeReview ? 'invalidated' : 'rejected',
          choices: this._reloadBeforeReview ? {} : this.state.choices,
          error: errorText(error, 'Publication was refused. Review the current impact before trying again.') +
            (this._wasUncertain ? ' The earlier uncertain attempt may have committed. Reload and reassess the current workflow.' : ''),
        });
        this._requestBody = null;
      }
    } finally {
      this._busy = false;
    }
  }

  reloadAfterSuccess = async () => {
    if (this._busy) return;
    this._busy = true;
    this.setState({phase: 'reloading'});
    try {
      await this.props.reload();
      if (this._unmounted) return;
      notify.show(this.state.success, 'success');
      this.finish();
    } catch (error) {
      if (!this._unmounted) this.setState({phase: 'reload_failed', error:
        'Publication succeeded, but the page could not reload. Retry loading the page; this will not publish again.'});
    } finally {
      this._busy = false;
    }
  }

  render() {
    const {phase, impact, choices, error, success} = this.state;
    const pending = ['saving', 'assessing', 'submitting', 'reloading'].includes(phase);
    const cannotClose = this._refreshingInputs || ['submitting', 'reloading', 'uncertain', 'reload_failed'].includes(phase);
    return (
      <Modal show={phase !== 'idle'} onHide={this.close} keyboard={!cannotClose}
        backdrop={cannotClose ? 'static' : true} aria-labelledby="automation-publish-title">
        <Modal.Header closeButton={!cannotClose}>
          <Modal.Title id="automation-publish-title">Publish automation</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {pending && <p role="status" aria-live="polite">{
            {saving: 'Saving draft…', assessing: 'Checking publish impact…',
              submitting: 'Publishing… Please wait. Closing this page does not cancel the server operation.',
              reloading: 'Publication succeeded. Reloading…'}[phase]
          }</p>}
          {error && <div className="alert alert-danger" role="alert">{error}</div>}
          {phase === 'reload_failed' && <p>{success}</p>}
          {!pending && !['uncertain', 'reload_failed'].includes(phase) &&
            <p className="help-block">Your draft changes remain saved. Contacts stay at their current live steps until you publish.</p>}
          {phase === 'review' && impact && <div>
            {impact.exit_review_required && <div className="alert alert-info">
              <strong>Exit rules will apply when you publish.</strong>
              <p>{(impact.rule_exits || {}).enrolment_count || 0} existing enrolments currently match and will exit, including paused contacts.</p>
              <p>Counts can change. Publishing applies these rules to all matching enrolments at commit time and blocks future entry while a rule matches. Rule exits take precedence over migration choices. Emails already in flight cannot be recalled.</p>
            </div>}
            {!!impact.blockers.length && <div className="alert alert-warning" role="alert">
              <strong>Publication is blocked</strong>
              <ul>{impact.blockers.map((blocker, index) => <li key={index}>
                <strong>{blocker.title}</strong>: {blocker.description}
                {blocker.node_id ? ' Step: ' + blocker.node_id + '.' : ''}
                {blocker.enrolment_count !== undefined ? ' Enrolments: ' + blocker.enrolment_count + '.' : ''}
              </li>)}</ul>
            </div>}
            {!!impact.sources.length && <p>Choose what happens to enrolments at each deleted step.
              Counts may change: each choice applies to everyone at that source when publication commits.</p>}
            {impact.sources.map(source => {
              const choice = choices[source.node_id] || {};
              return <div className="form-group" key={source.node_id}>
                <label htmlFor={'migration-action-' + source.node_id}>{nodeLabel(source)} — {source.enrolment_count} enrolments</label>
                <FormControl componentClass="select" id={'migration-action-' + source.node_id}
                  value={choice.action || ''} disabled={!!impact.blockers.length}
                  onChange={event => this.choose(source.node_id, {action: event.target.value})}>
                  <option value="">Choose a resolution</option>
                  <option value="move">Move to another step</option>
                  <option value="exit">Exit automation immediately</option>
                </FormControl>
                {choice.action === 'move' && <div style={{marginTop: 8}}>
                  <label htmlFor={'migration-destination-' + source.node_id}>Destination for {nodeLabel(source)}</label>
                  <FormControl componentClass="select" id={'migration-destination-' + source.node_id}
                    value={choice.destination_node_id || ''} disabled={!!impact.blockers.length}
                    onChange={event => this.choose(source.node_id, {action: 'move', destination_node_id: event.target.value})}>
                    <option value="">Choose a destination</option>
                    {impact.destinations.map(node => <option key={node.node_id} value={node.node_id}>{nodeLabel(node)}</option>)}
                  </FormControl>
                  <p className="help-block">Starts the destination fresh and resets any existing wait.
                    Paused contacts remain paused. Moving to an Exit step schedules its normal execution; it does not exit immediately.</p>
                </div>}
                {choice.action === 'exit' && <p className="help-block">Ends these enrolments immediately, even while paused.</p>}
              </div>;
            })}
          </div>}
        </Modal.Body>
        <Modal.Footer>
          {!cannotClose && <Button onClick={this.close}>Keep editing draft</Button>}
          {['review', 'rejected', 'assessment_failed'].includes(phase) &&
            <Button onClick={() => this.assess(false)}>{this._reloadBeforeReview ? 'Reload and reassess' : 'Reassess'}</Button>}
          {phase === 'review' && <Button bsStyle="primary" disabled={!this.canSubmit()}
            onClick={this.submit}>Publish</Button>}
          {phase === 'uncertain' && <Button bsStyle="primary" onClick={this.send}>Retry same publication</Button>}
          {phase === 'reload_failed' && <Button bsStyle="primary" onClick={this.reloadAfterSuccess}>Retry page reload</Button>}
        </Modal.Footer>
      </Modal>
    );
  }
}
