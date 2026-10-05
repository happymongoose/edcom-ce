import React, {Component} from 'react';
import {Button, Modal} from 'react-bootstrap';

const key = id => 'automation-publish-reminder:' + id;

// A browser preference, not an automation execution/persistence field.
export function shouldRemindAfterSave(id) {
  if (!id || id === 'new') return false;
  try { return window.localStorage.getItem(key(id)) !== 'off'; }
  catch (error) { return true; }
}

export default class AutomationSaveReminder extends Component {
  state = {remember: false};

  choose = publish => {
    if (this.finished) return;
    this.finished = true;
    if (this.state.remember) {
      try { window.localStorage.setItem(key(this.props.id), 'off'); }
      catch (error) { /* Saving and publication must work when storage is unavailable. */ }
    }
    this.props.onChoose(publish);
  }

  render() {
    return <Modal show onHide={() => this.choose(false)} aria-labelledby="automation-save-reminder-title">
      <Modal.Header closeButton><Modal.Title id="automation-save-reminder-title">Draft saved</Modal.Title></Modal.Header>
      <Modal.Body>
        <p>Saving does not update the live automation. Would you like to publish these changes too?</p>
        <p className="help-block">Publishing will check the workflow and ask where contacts should go if any occupied steps were removed.</p>
        <label><input type="checkbox" checked={this.state.remember}
          onChange={event => this.setState({remember: event.target.checked})} />{' '}
          Don't ask me this again for this automation.
        </label>
        <p className="help-block">Remembered in this browser. You can still use Publish at any time.</p>
      </Modal.Body>
      <Modal.Footer>
        <Button onClick={() => this.choose(false)}>Stay in draft</Button>
        <Button bsStyle="primary" onClick={() => this.choose(true)}>Review and publish</Button>
      </Modal.Footer>
    </Modal>;
  }
}
