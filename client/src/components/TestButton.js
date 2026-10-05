import React, { Component } from "react";
import { FormGroup, Modal, Button, Checkbox } from "react-bootstrap";
import { SelectLabel, FormControlLabel } from "./FormControls";
import _ from "underscore";
import notify from "../utils/notify";
import { routesHelp } from "../utils/template-utils";

import "react-select2-wrapper/css/select2.css";

import "./TestButton.css";

export default class TestButton extends Component {
  constructor(props) {
    super(props);

    this.state = {
      showModal: false,
      to: '',
      route: props.routes && props.routes.length ? props.routes[0].id : null,
      alert: '',
      alertred: false,
      json: '',
      includeInLog: false,
      editMode: !(props.emails && props.emails.to),
      totext: (props.emails && props.emails.to) || '',
      totextedit: '',
    };
  }

  componentWillReceiveProps(props) {
    var p = {};
    if (props.lasttest) {
      if (!this.state.to && props.lasttest.to) {
        if (this.hasEmail((props.emails && props.emails.to) || '', props.lasttest.to)) {
          p.to = props.lasttest.to;
        }
      }
      if (!this.state.route && props.lasttest.route && _.find(props.routes, r => r.id === props.lasttest.route)) {
        p.route = props.lasttest.route;
      }
      if (!this.state.json && props.lasttest.json) {
        p.json = props.lasttest.json;
      }
    }
    if (!this.state.totext && props.emails && props.emails.to) {
      p.totext = (props.emails && props.emails.to) || '';
      if (p.totext) {
        p.editMode = false;
      }
    }
    if (!(p.totext || this.state.totext)) {
      p.editMode = true;
      p.totextedit = '';
    }
    if (_.size(p)) {
      this.setState(p);
    }
  }

  validateForm() {
    return this.state.to || this.emailDefault();
  }

  handleChange = event => {
    var val = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    this.setState({[event.target.id]: val, alert: '', alertred: false});
  }

  onClick = () => {
    if (this.props.preCheck) {
      var msg = this.props.preCheck();
      if (msg) {
        notify.show(msg, "error");
        return;
      }
    }

    if (this.props.toggleModal) {
      this.props.toggleModal(true)
      this.setState({alert: '', alertred: false, includeInLog: false})
    } else {
      this.setState({showModal: true, alert: '', alertred: false, includeInLog: false});
    }
  }

  editClicked = () => {
    this.setState({editMode: true, totextedit: this.state.totext});
  }

  hasEmail(text, email) {
    return _.find(this.emailArray(text), e => e === email.toLowerCase());
  }

  emailArray(text) {
    return _.filter(_.map(text.split(/\s+/), e => e.toLowerCase()), e => e);
  }

  emailDefault() {
    var a = this.emailArray(this.state.totext);
    if (!a.length) {
      return '';
    }
    return a[0];
  }

  saveClicked = () => {
    var p = {editMode: false, totext: this.state.totextedit};
    if (!this.hasEmail(this.state.totextedit, this.state.to)) {
      p.to = '';
    }
    this.setState(p, () => {
      this.props.onUpdate({to: this.state.totextedit});
    });
  }

  confirmClicked = yes => {
    if (yes && this.props.useJson && this.state.json) {
      try {
        JSON.parse(this.state.json);
      } catch (e) {
        this.setState({alert: "Invalid JSON: " + e, alertred: true})
        return;
      }
    }

    var p = {alert: '', alertred: false};
    if (this.state.editMode) {
      p.editMode = false;
    }

    if (this.props.toggleModal) {
      this.props.toggleModal(false)
    } else {
      p.showModal = false;
    }

    this.setState(p);

    if (yes) {
      this.props.onConfirm(this.state.to || this.emailDefault(), this.state.route, this.state.json, this.state.includeInLog);
    }
  }

  render() {
    var cn = 'btn_camp green_btn next';
    if (!this.props.left)
      cn += ' pull-right';
    return (
      <button type="button" className={cn} onClick={this.onClick} disabled={this.props.disabled}>
        Send Test Email
        <Modal show={typeof this.props.showModal === 'boolean' ? this.props.showModal : this.state.showModal} id="testmodal">
          <Modal.Header>
            <Modal.Title>Send Test Email</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            {
              this.state.alert &&
              <div className="text-center">
                <p>
                  <span style={{color:'white', backgroundColor: this.state.alertred?'#c12c2c':'#70d352', paddingTop: '4px', paddingBottom: '4px',
                                paddingLeft: '10px', paddingRight: '10px'}}>
                    {this.state.alert}
                  </span>
                </p>
              </div>
            }
            {
              this.state.editMode ?
                <FormGroup className="space10">
                  <label>Enter Up to 10 Email Addresses:</label>
                  <FormControlLabel
                    id="totextedit"
                    obj={this.state}
                    onChange={this.handleChange}
                    rows="6"
                    componentClass="textarea"
                  />
                  <Button bsSize="xs" style={{marginTop: '10px', padding: '1px 5px', fontWeight: '500'}} className="pull-right" onClick={this.saveClicked} disabled={this.emailArray(this.state.totextedit).length < 1 || this.emailArray(this.state.totextedit).length > 10} bsStyle="primary">Save Email Addresses</Button>
                  <div className="clearfix"/>
                </FormGroup>
              :
              <div>
                <FormGroup className="space10">
                  <label>Select Email Address to Send to:</label>
                  <SelectLabel
                    id="to"
                    obj={this.state}
                    onChange={this.handleChange}
                    options={_.map(this.emailArray(this.state.totext), e => ({id: e, name: e}))}
                  />
                  <Button bsSize="xs" style={{marginTop: '10px'}} className="pull-right" onClick={this.editClicked}>Edit Email Addresses</Button>
                  <div className="clearfix"/>
                </FormGroup>
                {
                  this.props.useJson &&
                    <FormControlLabel
                      id="json"
                      label="JSON Variable Data"
                      obj={this.state}
                      onChange={this.handleChange}
                      componentClass="textarea"
                      rows="4"
                    />
                }
                {
                  !this.props.routes
                  ?
                    null
                  :
                  <SelectLabel
                    id="route"
                    label="Send via Route"
                    obj={this.state}
                    onChange={this.handleChange}
                    options={this.props.routes}
                    help={routesHelp(this.props.routes)}
                  />
                }
                {
                  this.props.showIncludeInLogCheckbox &&
                    <FormGroup className="space10">
                      <Checkbox id="includeInLog" checked={this.state.includeInLog} onChange={this.handleChange}>
                        Include in transactional log
                      </Checkbox>
                    </FormGroup>
                }
              </div>
            }
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={this.confirmClicked.bind(this, true)} bsStyle="primary" style={{display: this.state.editMode?'none':undefined}} disabled={!this.validateForm() || this.state.editMode}>Send</Button>
            <Button onClick={this.confirmClicked.bind(this, false)}>Cancel</Button>
          </Modal.Footer>
        </Modal>
      </button>
    );
  }
}
