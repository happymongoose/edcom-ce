import React, {Component} from 'react';
import {Button, Modal, Alert} from 'react-bootstrap';
import axios from 'axios';

const rate = value => value === null || value === undefined ? '—' : (value * 100).toFixed(2) + '%';
const message = error => (error.response && error.response.data && (error.response.data.description || error.response.data.title)) || 'Unable to update experiment. Refresh its status before trying again.';

export default class AutomationSubjectTests extends Component {
  state = {tests: [], loading: true, busy: false, error: '', variants: [{subject: '', weight: 50}, {subject: '', weight: 50}], maximum: 2000, hours: 24, metric: 'ctr', weights: {}, challenger: '', confirmation: null};
  componentDidMount() {this.refresh();}
  url = () => '/api/automations/' + this.props.automationId + '/emails/' + this.props.emailId + '/subject-tests';
  refresh = async () => {
    this.setState({loading: true, error: ''});
    try {
      const tests = (await axios.get(this.url())).data;
      const current = tests.find(t => t.status !== 'archived');
      const weights = {}; if (current) current.variants.forEach(v => {weights[v.id] = v.weight;});
      this.setState({tests, weights});
    } catch (error) {this.setState({error: message(error)});}
    finally {this.setState({loading: false});}
  }
  command = async payload => {
    if (this.state.busy) return;
    this.setState({busy: true, error: ''});
    try {
      if (payload.action === 'start' && !(await this.props.saveEmail())) return;
      await axios.post(this.url(), payload);
      this.setState({confirmation: null, challenger: ''});
      await this.refresh();
    } catch (error) {this.setState({confirmation: null, error: message(error)});}
    finally {this.setState({busy: false});}
  }
  changeVariant = (index, field, value) => this.setState({variants: this.state.variants.map((v, i) => i === index ? {...v, [field]: value} : v)});
  action = (test, action, extra) => ({action, experiment_id: test.id, version: test.version, ...extra});
  renderStats = stats => <div style={{overflowX: 'auto'}}><table className="table table-condensed"><thead><tr>
    {['Subject', 'Assigned', 'Recipients', 'Accepted', 'Deliveries', 'Opens', 'Clicks', 'OR', 'CTR', 'CTOR'].map(x => <th key={x}>{x}</th>)}
  </tr></thead><tbody>{stats.map(v => <tr key={v.id}><td>{v.subject}</td><td>{v.assigned}</td><td>{v.recipients}</td><td>{v.accepted}</td><td>{v.deliveries}</td><td>{v.opens}</td><td>{v.clicks}</td><td>{rate(v.or_rate)}</td><td>{rate(v.ctr)}</td><td>{rate(v.ctor)}</td></tr>)}</tbody></table></div>;
  render() {
    const current = this.state.tests.find(t => t.status !== 'archived');
    const disabled = this.state.busy || this.state.loading;
    const confirmation = this.state.confirmation;
    return <section aria-label="Subject-line experiments" style={{marginTop: 20, marginBottom: 20}}>
      <h4>Subject-line A/B testing</h4>
      <p>Variants share the saved email body. Experiment controls affect future live sends immediately; publishing the automation is not required. Each eligible send is randomised; retries keep their assignment.</p>
      {this.state.error && <Alert bsStyle="danger">{this.state.error}</Alert>}
      <Button type="button" bsSize="small" disabled={disabled} onClick={this.refresh}>Refresh experiment</Button>
      {this.state.loading && <p role="status">Loading experiment…</p>}
      {current && <div>
        <p><strong>{current.status === 'selected' ? 'Winner selected' : !current.deadline ? 'Not started — waiting for first eligible send' : current.status === 'observing' ? 'Observing results — later arrivals wait' : 'Collecting sample'}</strong></p>
        <p>Maximum {current.maximum_sends} test sends · {current.hours} {current.hours === 1 ? 'hour' : 'hours'} · Winner by {current.metric.toUpperCase()}{current.deadline ? ' · Deadline: ' + new Date(current.deadline).toLocaleString() : ''}</p>
        {current.winner_id && <p>Current winning subject: <strong>{current.variants.find(v => v.id === current.winner_id).subject}</strong></p>}
        {this.renderStats(current.statistics || [])}
        <p className="text-muted">Test-cohort results only. Rates use confirmed deliveries; opens/clicks are counted once per delivered message. Accepted does not mean delivered. Missing delivery callbacks leave rates unavailable. OR and CTOR are affected by mail privacy features. A higher observed rate is not proof of statistical significance.</p>
        {current.variants.map(v => <div key={v.id} style={{display: 'flex', gap: 10, alignItems: 'center', marginBottom: 8}}>
          <span style={{flex: 1}}>{v.subject}{v.id === current.control_id ? ' (control)' : ''}</span>
          {current.status === 'collecting' && <label>Weight <input aria-label={'Weight for ' + v.subject} type="number" min="0" max="100" disabled={disabled} value={this.state.weights[v.id] === undefined ? v.weight : this.state.weights[v.id]} onChange={e => this.setState({weights: {...this.state.weights, [v.id]: Number(e.target.value)}})} style={{width: 65}} /></label>}
          <Button type="button" bsSize="small" disabled={disabled || current.winner_id === v.id} onClick={() => this.setState({confirmation: this.action(current, 'winner', {variant_id: v.id})})}>Use this subject</Button>
        </div>)}
        {current.status === 'collecting' && <div>
          <p>Weights are relative; 0 pauses new assignments to that variant. Changing allocation or adding challengers can make comparisons less balanced.</p>
          <Button type="button" disabled={disabled} onClick={() => this.command(this.action(current, 'allocation', {weights: this.state.weights}))}>Save allocation</Button>
          <label style={{marginLeft: 12}}>New challenger <input aria-label="New challenger subject" disabled={disabled} value={this.state.challenger} onChange={e => this.setState({challenger: e.target.value})} /></label>
          <Button type="button" disabled={disabled || !this.state.challenger.trim() || current.variants.length >= 10} onClick={() => this.command(this.action(current, 'challenger', {subject: this.state.challenger, weight: 50}))}>Add challenger</Button>
        </div>}
        {current.decision && <details><summary>Decision evidence — {current.decision.reason.replace(/_/g, ' ')}</summary><p>{new Date(current.decision.at).toLocaleString()}. This snapshot is fixed; later events update the live report only.</p>{this.renderStats(current.decision.statistics)}</details>}
        {(current.changes || []).filter(c => c.request.action === 'winner').map((c, i) => <p key={i}>Manual selection: {current.variants.find(v => v.id === c.request.variant_id).subject} · {new Date(c.at).toLocaleString()}</p>)}
      </div>}
      {(!current || current.status === 'selected') && !this.state.loading && <div>
        <h5>{current ? 'Start another experiment' : 'Create an experiment'}</h5>
        <p>The first subject is the control, used for ties, no engagement or unavailable rates. Maximum volume is a cap, not a guaranteed sample. The clock starts at the first committed test-send attempt and keeps running while paused. Later sample recipients have less observation time.</p>
        {current && <Button type="button" bsSize="small" disabled={disabled} onClick={() => this.changeVariant(0, 'subject', current.variants.find(v => v.id === current.winner_id).subject)}>Use previous winner as control</Button>}
        {this.state.variants.map((v, i) => <div key={i} style={{display: 'flex', gap: 10, marginBottom: 8}}>
          <label style={{flex: 1}}>Subject {i + 1}{i === 0 ? ' (control)' : ''}<input className="form-control" aria-label={'Test subject ' + (i + 1)} disabled={disabled} value={v.subject} onChange={e => this.changeVariant(i, 'subject', e.target.value)} /></label>
          <label>Weight<input className="form-control" aria-label={'Test weight ' + (i + 1)} style={{width: 80}} type="number" min="0" max="100" disabled={disabled} value={v.weight} onChange={e => this.changeVariant(i, 'weight', Number(e.target.value))} /></label>
        </div>)}
        <Button type="button" bsSize="small" disabled={disabled || this.state.variants.length >= 10} onClick={() => this.setState({variants: this.state.variants.concat([{subject: '', weight: 50}])})}>Add subject</Button>
        <label style={{margin: 10}}>Maximum test sends <input aria-label="Maximum test sends" type="number" min="1" disabled={disabled} value={this.state.maximum} onChange={e => this.setState({maximum: Number(e.target.value)})} /></label>
        <label style={{margin: 10}}>Duration (hours) <input aria-label="Experiment hours" type="number" min="1" max="8760" disabled={disabled} value={this.state.hours} onChange={e => this.setState({hours: Number(e.target.value)})} /></label>
        <label>Winning metric <select aria-label="Winning metric" disabled={disabled} value={this.state.metric} onChange={e => this.setState({metric: e.target.value})}><option value="ctr">CTR</option><option value="or">OR</option></select></label>
        <p>Reaching the cap makes later contacts wait at Send Email until selection. At the deadline the highest observed rate wins, even for an underfilled sample. Paused contacts remain paused. A manual winner can release the gate early. Changing tested subject text requires a new challenger or experiment.</p>
        <Button type="button" bsStyle="primary" disabled={disabled || this.state.variants.some(v => !v.subject.trim())} onClick={() => this.setState({confirmation: {action: 'start', previous_id: current ? current.id : null, variants: this.state.variants, maximum_sends: this.state.maximum, hours: this.state.hours, metric: this.state.metric}})}>Start experiment</Button>
      </div>}
      {this.state.tests.filter(t => t.status === 'archived').map(t => <details key={t.id}><summary>Previous experiment · {new Date(t.created).toLocaleString()}</summary>{this.renderStats(t.statistics)}{t.decision && <div><p>Frozen decision: {t.decision.reason}</p>{this.renderStats(t.decision.statistics)}</div>}</details>)}
      <Modal show={!!confirmation} onHide={() => !this.state.busy && this.setState({confirmation: null})} keyboard={!this.state.busy} backdrop={this.state.busy ? 'static' : true}>
        <Modal.Header closeButton={!this.state.busy}><Modal.Title>Confirm subject experiment</Modal.Title></Modal.Header>
        <Modal.Body>{confirmation && confirmation.action === 'start' ? 'Save this email and start the experiment for future eligible sends? This is a live change.' : 'Use this subject for future unassigned sends and release waiting contacts? Already committed sends and historical results stay unchanged.'}</Modal.Body>
        <Modal.Footer><Button type="button" disabled={this.state.busy} onClick={() => this.setState({confirmation: null})}>Cancel</Button><Button type="button" bsStyle="primary" disabled={this.state.busy} onClick={() => this.command(confirmation)}>{this.state.busy ? 'Applying…' : 'Confirm'}</Button></Modal.Footer>
      </Modal>
    </section>;
  }
}
