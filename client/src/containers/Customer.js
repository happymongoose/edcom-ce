import React, { Component } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Nav, NavItem, Button, Modal } from "react-bootstrap";
import LoaderPanel from "../components/LoaderPanel";
import LoaderButton from "../components/LoaderButton";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel, SelectLabel, CheckboxLabel } from "../components/FormControls";
import getvalue from "../utils/getvalue";
import SaveNavbar from "../components/SaveNavbar";
import TitlePage from "../components/TitlePage";
import { EDTabs, EDFormSection, EDFormBox, EDFormGroup } from "../components/EDDOM";
import Select2 from "react-select2-wrapper";
import _ from "underscore";
import Datetime from "react-datetime";
import moment from "moment";

import "react-select2-wrapper/css/select2.css";

function uppercaseFirst(s) {
  if (!s) { return s; }
  return s.charAt(0).toUpperCase() + s.slice(1);
}

class Customer extends Component {
  constructor(props) {
    super(props);

    this.state = {
      showModal: null,
    };
  }

  modalChanged = event => {
    this.setState({[event.target.id]: getvalue(event)});
  }

  validateForm() {
    const d = this.props.data;
    return d.name && d.frontend && d.routes && d.routes.length && d.minlimit !== null && d.hourlimit !== null && d.daylimit !== null && d.monthlimit !== null;
  }

  handleChange = event => {
    this.props.update({[event.target.id]: {$set: getvalue(event)}})
  }

  handleDateChange = v => {
    this.props.update({trialend: {$set: v?v.format():v}})
  }

  handleSubmit = async event => {
    event.preventDefault();

    var id = (await this.props.save()).data.id;

    if (!id) {
      this.props.history.push('/customers');
    } else {
      this.props.history.push('/customers/edit-users?id=' + id);
    }
  }

  switchView = url => {
    this.props.history.push(url);
  }

  goBack = () => {
    this.props.history.push('/customers');
  }

  updateCredits = name => {
    this.setState({showModal: name, newcredits: this.props.credits[name]});
  }

  formatAutomationFlag = value => value ? 'Enabled' : 'Disabled'

  renderAutomationOperations = () => {
    if (this.props.id === 'new') {
      return null;
    }

    const operations = this.props.automationOperations;
    const flags = (operations && operations.flags) || {};
    const summary = (operations && operations.summary) || {};
    const statuses = [
      ['ready', 'Ready'],
      ['waiting', 'Waiting'],
      ['held', 'Held'],
      ['paused_ready', 'Paused ready'],
      ['paused_waiting', 'Paused waiting'],
      ['running', 'Running'],
      ['stale_running', 'Stale running'],
      ['failed', 'Failed'],
      ['completed', 'Completed'],
      ['exited', 'Exited'],
      ['cancelled', 'Cancelled'],
      ['total', 'Total'],
    ];

    return (
      <EDFormBox>
        <h3>Automation Operations</h3>
        <CheckboxLabel
          id="automation_processing_enabled"
          label="Enable automation processing for this customer"
          obj={this.props.data}
          onChange={this.handleChange}
          help="Scheduled and batch automation processing will only run when the global feature flag is also enabled."
          space
        />
        <CheckboxLabel
          id="automation_diagnostics_visible"
          label="Show automation diagnostics to customer users"
          obj={this.props.data}
          onChange={this.handleChange}
          help="Admin impersonation can view diagnostics regardless of this setting."
          space
        />
        {
          operations ?
            <div>
              <h4>Global Automation Flags</h4>
              <table className="table table-striped table-bordered">
                <tbody>
                  {
                    _.map(_.keys(flags).sort(), key => (
                      <tr key={key}>
                        <th>{key}</th>
                        <td>{this.formatAutomationFlag(flags[key])}</td>
                      </tr>
                    ))
                  }
                </tbody>
              </table>
              {
                this.props.data.automation_processing_enabled && !flags.automation_processing_enabled &&
                  <p className="text-warning">
                    Customer automation processing is enabled, but the global automation processing flag is disabled.
                  </p>
              }
              <h4>Customer Enrolment Summary</h4>
              <table className="table table-striped table-bordered">
                <tbody>
                  {
                    _.map(statuses, ([key, label]) => (
                      <tr key={key}>
                        <th>{label}</th>
                        <td>{summary[key] || 0}</td>
                      </tr>
                    ))
                  }
                </tbody>
              </table>
              <p className="help-block">
                Diagnostic pages are available from the customer portal when diagnostics are visible, or while an admin is impersonating this customer.
              </p>
            </div>
          :
            <p className="help-block">Loading automation operations status...</p>
        }
      </EDFormBox>
    );
  }

  navbarButtons = () => {
    return (
      <LoaderButton
        id="customer-settings-buttons-dropdown"
        text="Save and Close"
        loadingText="Saving..."
        className="green"
        disabled={!this.validateForm() || this.props.isSaving}
        onClick={this.handleSubmit}
        splitItems={[
          { text: 'Cancel', onClick: this.goBack }
        ]}
      />
    )
  }

  modalClose = async ok => {
    var name = this.state.showModal;

    this.setState({showModal: null});
  
    if (!ok) {
      return;
    }
  
    await axios.patch('/api/companies/' + this.props.id + '/credits', {
      [name]: this.state.newcredits,
    });

    this.props.reloadExtra();
  }

  render() {
    var routeitems = _.map(this.props.routes, r => ({id: r.id, text: r.name}));
    const params = this.props.data.params;

    return (
      <SaveNavbar isAdmin={true} title={this.props.id === 'new'?'Create Customer':'Customer Settings'} disabled={!this.validateForm()}
                  onBack={this.goBack} buttons={this.navbarButtons()} isSaving={this.props.isSaving}>
        {
          this.props.id !== 'new' && 
            <TitlePage tabs={
              <EDTabs>
                <Nav className="nav-tabs" activeKey="1">
                  <NavItem eventKey="1" disabled>Settings</NavItem>
                  <NavItem eventKey="2" onClick={this.switchView.bind(null, '/customers/edit-users?id=' + this.props.id)}>Users</NavItem>
                  <NavItem eventKey="3" onClick={this.switchView.bind(null, '/customers/list-approval?id=' + this.props.id)}>List Approval</NavItem>
                </Nav>
              </EDTabs>
            }/>
        }
        <LoaderPanel isLoading={this.props.isLoading}>
          <EDFormSection onSubmit={this.handleSubmit} noShadow>
          {
            this.props.routes && !this.props.routes.length &&
              <h4 className="text-center space-top">
                No postal routes are configured. This customer will not be able to send mail until you <Link to="/routes/edit?id=new">create a postal route</Link>.
              </h4>
          }
          {
            this.props.frontends && !this.props.frontends.length ?
            <h4 className="text-center space-top">
              No frontends are configured. You should <Link to="/frontends/edit?id=new">create a frontend</Link> before you configure any customers.
            </h4>
            :
            <EDFormBox>
              <FormControlLabel
                id="name"
                label="Company Name"
                obj={this.props.data}
                onChange={this.handleChange}
              />
              {
                params &&
                <div className="space-top-sm">
                  <label className="control-label">Sign-up Info</label>
                  <table className="table table-striped table-bordered">
                    <thead>
                      <tr>
                        {
                          _.keys(params).sort().map(p => (
                            <th key={p}>{uppercaseFirst(p)}</th>
                          ))
                        }
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        {
                          _.keys(params).sort().map(p => (
                            <td style={{padding: '16px'}} key={p}>{params[p]}</td>
                          ))
                        }
                      </tr>
                    </tbody>
                  </table>
                </div>
              }
              <SelectLabel
                id="frontend"
                label="Frontend"
                obj={this.props.data}
                onChange={this.handleChange}
                options={this.props.frontends}
                space
              />
              <EDFormGroup space>
                <label>Postal Routes</label>
                <div>
                  <Select2
                    id="routes"
                    multiple
                    data={routeitems}
                    value={this.props.data.routes}
                    onChange={this.handleChange}
                    style={{width:'100%'}}
                  />
                </div>
                <span className="help-block">Selecting more than one postal route will allow the customer to choose which route to use when sending</span>
              </EDFormGroup>
              <FormControlLabel
                id="minlimit"
                label="Send Limit per Minute"
                obj={this.props.data}
                onChange={this.handleChange}
                type="number"
                min="0"
                style={{width: '120px'}}
                space
              />
              <FormControlLabel
                id="hourlimit"
                label="Send Limit per Hour"
                obj={this.props.data}
                onChange={this.handleChange}
                type="number"
                min="0"
                style={{width: '120px'}}
                space
              />
              <FormControlLabel
                id="daylimit"
                label="Send Limit per Day"
                obj={this.props.data}
                onChange={this.handleChange}
                type="number"
                min="0"
                style={{width: '120px'}}
                space
              />
              <FormControlLabel
                id="monthlimit"
                label="Send Limit per Month"
                obj={this.props.data}
                onChange={this.handleChange}
                type="number"
                min="0"
                style={{width: '120px'}}
                space
              />
              { this.props.credits && this.props.data.paid &&
                <div style={{marginTop: '10px'}}>
                  <div>
                    <label style={{width: '150px'}}>Unlimited Credits:</label> <span style={{display: 'inline-block', minWidth: '100px'}}>{this.props.credits.unlimited}</span> <Button onClick={this.updateCredits.bind(null, 'unlimited')}>Update</Button>
                  </div>
                  <div>
                    <label style={{width: '150px'}}>Monthly Credits:</label> <span style={{display: 'inline-block', minWidth: '100px'}}>{this.props.credits.expire}</span> <Button onClick={this.updateCredits.bind(null, 'expire')}>Update</Button>
                  </div>
                </div>
              }
              <EDFormGroup space>
                <label>Trial Expiration:</label>
                <div style={{width: '250px'}}>
                  <Datetime value={this.props.data.trialend?moment(this.props.data.trialend):''} onChange={this.handleDateChange} />
                </div>
              </EDFormGroup>
              <CheckboxLabel
                id="exampletemplate"
                label="Example Data Template"
                obj={this.props.data}
                onChange={this.handleChange}
                help="Only one customer can be the example template at a time. If checked, broadcast, contact, segment and funnel data from this customer will be copied to every new customer in the system."
                space
              />
              <CheckboxLabel
                id="reverse_funnel_order"
                label="Reverse Funnel Order"
                obj={this.props.data}
                onChange={this.handleChange}
                help={
                  <span>
                    Default: First in, first out.<br/>
                    Reverse: Last in, first out.
                  </span>
                }
                space
              />
              <CheckboxLabel
                id="skip_list_validation"
                label="Don't Validate Lists"
                obj={this.props.data}
                onChange={this.handleChange}
                help="If unchecked, all contact lists uploaded by this customer will require backend admin approval."
                space
              />
            </EDFormBox>
          }
          {this.renderAutomationOperations()}
          </EDFormSection>
          <Modal show={this.state.showModal !== null} bsSize="small">
            <Modal.Header>
              <Modal.Title>
                Update Credits
              </Modal.Title>
            </Modal.Header>
            <Modal.Body>
              <FormControlLabel
                id="newcredits"
                obj={this.state}
                type="number"
                min="0"
                onChange={this.modalChanged}
                label="Credits"
                style={{width: '100px'}}
              />
            </Modal.Body>
            <Modal.Footer>
              <Button onClick={this.modalClose.bind(this, true)} bsStyle="primary" disabled={this.state.newcredits === null}>Save</Button>
              <Button onClick={this.modalClose.bind(this, false)}>Cancel</Button>
            </Modal.Footer>
          </Modal>
        </LoaderPanel>
      </SaveNavbar>
    );
  }
}

export default withLoadSave({
  extend: Customer,
  initial: {
    name: '',
    frontend: '',
    routes: [],
    minlimit: 999999999,
    hourlimit: 999999999,
    daylimit: 999999999,
    monthlimit: 999999999,
    exampletemplate: false,
    price: null,
    period: 'monthly',
    credits: null,
    overageprice: null,
    overagecredits: null,
    minlimitpostupgrade: 999999999,
    hourlimitpostupgrade: 999999999,
    daylimitpostupgrade: 999999999,
    monthlimitpostupgrade: 999999999,
    skip_list_validation: true,
    automation_processing_enabled: false,
    automation_diagnostics_visible: false,
  },
  get: async ({id}) => (await axios.get('/api/companies/' + id)).data,
  post: ({data}) => axios.post('/api/companies', data),
  patch: ({id, data}) => axios.patch('/api/companies/' + id, data),
  extra: {
    frontends: async () => (await axios.get('/api/frontends')).data,
    routes: async () => _.filter((await axios.get('/api/routes')).data, r => r.published),
    credits: async ({id}) => {
      if (id === 'new')
        return null;
      return (await axios.get('/api/companies/' + id + '/credits')).data;
    },
    automationOperations: async ({id}) => {
      if (id === 'new')
        return null;
      return (await axios.get('/api/companies/' + id + '/automation-operations')).data;
    },
  },
  extramerge: {
    frontend: 'frontends',
  }
});
