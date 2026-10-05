import React, { Component } from "react";
import { Button, DropdownButton, FormControl, MenuItem, Modal, Nav, NavItem, Tooltip, OverlayTrigger } from "react-bootstrap";
import { Link } from "react-router-dom";
import axios from "axios";
import _ from "underscore";
import LoaderPanel from "../components/LoaderPanel";
import ConfirmDropdown from "../components/ConfirmDropdown";
import TitlePage from "../components/TitlePage";
import withLoadSave from "../components/LoadSave";
import MenuNavbar from "../components/MenuNavbar";
import notify from "../utils/notify";
import { EDTableSection, EDTable, EDTableRow, EDTabs } from "../components/EDDOM";
import TablePie from "../components/TablePie";
import ContactsAll from './ContactsAll';

import "./Contacts.css";

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

function automationIsEnrollable(automation) {
  return automation.status === 'published' || (automation.status === 'paused' && (automation.published || automation.published_at));
}

class Contacts extends Component {
  constructor(props) {
    super(props);

    this.state = {
      bulkList: null,
      bulkAutomationId: '',
      bulkEnrolling: false,
      bulkResult: null,
      showingSearchResults: false,
    };
  }

  createClicked = () => {
    this.props.history.push("/contacts/add?id=new");
  }

  searchVisibilityChange = showingSearchResults => this.setState({showingSearchResults});

  deleteConfirmClicked = async id => {
    await axios.delete('/api/lists/' + id);
    await this.props.reload();
  }

  addDataClicked = id => {
    this.props.history.push("/contacts/add?id=" + id);
  }

  addUnsubsClicked = id => {
    this.props.history.push("/contacts/addunsubs?id=" + id);
  }

  editNameClicked = id => {
    this.props.history.push("/contacts/edit?id=" + id);
  }

  viewDomainsClicked = id => {
    this.props.history.push("/contacts/domains?id=" + id);
  }

  exportClicked = async id => {
    await axios.post('/api/lists/' + id + '/export');

    notify.show('Download your export file from the Data Exports page', "success");
  }

  automationOptions = () => {
    return _.map(
      _.sortBy(
        _.filter(this.props.automations || [], automationIsEnrollable),
        automation => (automation.name || '').toLowerCase()
      ),
      automation => ({
        id: automation.id,
        name: automation.name || automation.id,
      })
    );
  }

  addToAutomationClicked = list => {
    const options = this.automationOptions();
    this.setState({
      bulkList: list,
      bulkAutomationId: options.length ? options[0].id : '',
      bulkEnrolling: false,
      bulkResult: null,
    });
  }

  closeBulkEnrolmentModal = () => {
    if (this.state.bulkEnrolling) {
      return;
    }

    this.setState({
      bulkList: null,
      bulkAutomationId: '',
      bulkResult: null,
    });
  }

  handleBulkAutomationChange = event => {
    this.setState({bulkAutomationId: event.target.value});
  }

  pollBulkEnrolment = async gatherId => {
    while (!this._unmounted) {
      await delay(2000);
      const response = (await axios.get('/api/automation-list-enrolments/' + gatherId)).data;
      if (response.error) {
        throw new Error(response.error);
      }
      if (response.complete) {
        return response.result;
      }
    }
    return null;
  }

  bulkEnrolmentResultText = result => {
    if (!result) {
      return '';
    }
    return this.num(result.enrolled_count) + ' enrolled, ' +
      this.num(result.skipped_count) + ' skipped, ' +
      this.num(result.error_count) + ' errors';
  }

  confirmBulkEnrolment = async () => {
    const list = this.state.bulkList;
    const automationId = this.state.bulkAutomationId;
    if (!list || !automationId) {
      return;
    }

    this.setState({bulkEnrolling: true, bulkResult: null});
    try {
      const response = (await axios.post('/api/automations/' + automationId + '/enrolments/list', {
        list_id: list.id,
      })).data;
      const result = response.result || (response.id ? await this.pollBulkEnrolment(response.id) : null);
      if (!result) {
        return;
      }

      this.setState({bulkResult: result});
      notify.show('Automation enrolment complete: ' + this.bulkEnrolmentResultText(result), result.error_count ? 'warning' : 'success', 15000);
      await this.props.reload();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to add list to automation'), 'error');
    } finally {
      if (!this._unmounted) {
        this.setState({bulkEnrolling: false});
      }
    }
  }

  componentDidMount() {
    this._unmounted = false;
    this._interval = setInterval(() => {
      if (_.find(this.props.data, l => l.processing)) {
        this.props.reload();
      }
    }, 10000);
  }

  componentWillUnmount() {
    this._unmounted = true;
    clearInterval(this._interval);
  }

  num(n) {
    if (!n) n = 0;
    return n.toLocaleString();
  }

  pctnum(l, n, prop) {
    if (!prop)
      prop = 'count'
    if (!l[prop] || !n)
      return 0;
    var v = (n/l[prop])*100;
    return Math.round(v);
  }

  pct(l, n, prop) {
    if (!prop)
      prop = 'count'
    if (!l[prop] || !n)
      return '0.0%'
    var v = (n/l[prop])*100;
    var r = Math.round(v)
    if (r < 10) {
      return v.toFixed(1) + '%';
    } else {
      return r + '%';
    }
  }

  switchView = url => {
    this.props.history.push(url);
  }

  viewAllContactsClicked = () => {
    this.props.history.push('/contacts/all');
  }

  render() {
    let minWidth = '600px';
    let maxWidth = '1200px';
    const automationOptions = this.automationOptions();
    const bulkList = this.state.bulkList;
    const bulkResult = this.state.bulkResult;

    return (
      <div className="contacts">
        <MenuNavbar {...this.props}>
          <Modal show={!!bulkList} onHide={this.closeBulkEnrolmentModal}>
            <Modal.Header closeButton={!this.state.bulkEnrolling}>
              <Modal.Title>Add Contact List to Automation</Modal.Title>
            </Modal.Header>
            <Modal.Body>
              {
                bulkList &&
                <div>
                  <p>
                    <strong>Contact list:</strong> {bulkList.name}
                  </p>
                  <p>
                    <strong>Estimated contacts:</strong> {this.num(bulkList.count)}
                  </p>
                  {
                    automationOptions.length ?
                      <div>
                        <label className="control-label" htmlFor="bulkAutomationId">Automation</label>
                        {' '}
                        <FormControl
                          id="bulkAutomationId"
                          componentClass="select"
                          value={this.state.bulkAutomationId}
                          onChange={this.handleBulkAutomationChange}
                          disabled={this.state.bulkEnrolling}
                        >
                          {
                            _.map(automationOptions, automation =>
                              <option key={automation.id} value={automation.id}>{automation.name}</option>
                            )
                          }
                        </FormControl>
                        <p className="help-block">
                          Re-entry rules may skip contacts that have already entered this automation or already have an active pass.
                        </p>
                      </div>
                    :
                      <p>No published or paused automations are available.</p>
                  }
                  {
                    this.state.bulkEnrolling &&
                    <p className="text-info">Adding contacts to automation...</p>
                  }
                  {
                    bulkResult &&
                    <div>
                      <hr />
                      <h4>Result</h4>
                      <p>{this.bulkEnrolmentResultText(bulkResult)}</p>
                      {
                        bulkResult.skipped && bulkResult.skipped.length > 0 &&
                        <div>
                          <h5>Skipped</h5>
                          <ul>
                            {
                              _.map(bulkResult.skipped.slice(0, 5), (skipped, index) =>
                                <li key={index}>{skipped.contact_email || skipped.contact_id}: {skipped.description || skipped.reason}</li>
                              )
                            }
                          </ul>
                        </div>
                      }
                      {
                        bulkResult.errors && bulkResult.errors.length > 0 &&
                        <div>
                          <h5>Errors</h5>
                          <ul>
                            {
                              _.map(bulkResult.errors.slice(0, 5), (error, index) =>
                                <li key={index}>{error.contact_email || error.contact_id || 'Error'}: {error.description || error.reason || error.message}</li>
                              )
                            }
                          </ul>
                        </div>
                      }
                    </div>
                  }
                </div>
              }
            </Modal.Body>
            <Modal.Footer>
              <Button onClick={this.closeBulkEnrolmentModal} disabled={this.state.bulkEnrolling}>
                {bulkResult ? 'Close' : 'Cancel'}
              </Button>
              {
                !bulkResult &&
                <Button
                  bsStyle="primary"
                  onClick={this.confirmBulkEnrolment}
                  disabled={this.state.bulkEnrolling || !this.state.bulkAutomationId || !automationOptions.length}
                >
                  {this.state.bulkEnrolling ? 'Adding...' : 'Add to automation'}
                </Button>
              }
            </Modal.Footer>
          </Modal>
          <TitlePage title="Contact Lists" leftsize={9} rightsize={3} button={
            <div className="form-inline">
              <DropdownButton id="contacts-actions-dropdown" title="Actions" pullRight>
                <MenuItem onClick={this.viewAllContactsClicked}>View All Contacts</MenuItem>
              </DropdownButton>
              {' '}
              <Button bsStyle="primary" onClick={this.createClicked}>Create Contact List</Button>
            </div>
          } tabs={
            <EDTabs>
              <Nav className="nav-tabs space15" activeKey="1">
                <NavItem eventKey="1" disabled>Contact Lists</NavItem>
                <NavItem eventKey="2" onClick={this.switchView.bind(null, '/contacts/alltags')}>Tags</NavItem>
                {
                  this.props.user && !this.props.user.nodataexport &&
                  <NavItem eventKey="3" onClick={this.switchView.bind(null, '/contacts/retrieval')}>GDPR Retrieval &amp; Erasure</NavItem>
                }
              </Nav>
            </EDTabs>
          }/>
          <ContactsAll embedded loggedInImpersonate={this.props.loggedInImpersonate} onResultsVisibilityChange={this.searchVisibilityChange} />
          {!this.state.showingSearchResults && <LoaderPanel isLoading={this.props.isLoading}>
            <EDTableSection>
            {
              this.props.data.length ?
                <EDTable className="growing-margin-left extra-pad" minWidth={minWidth} maxWidth={maxWidth}>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Active</th>
                      <th>30 Day Active</th>
                      <th>60 Day Active</th>
                      <th>90 Day Active</th>
                      <th>Domains</th>
                      <th></th>
                    </tr>
                  </thead>
                    {
                    _.map(this.props.data, (l, index) =>
                        <EDTableRow key={l.id} index={index} extra={
                          <tr>
                            <td colSpan="7" className="contacts-extra-td">
                              <div className="contacts-extra">
                                <div className="contacts-extra-cell">
                                  90 day active: <span className="contacts-extra-num">{this.num(l.active90)}</span>
                                </div>
                                <div className="contacts-extra-cell">
                                  Unsubscribed: <span className="contacts-extra-num">{this.num(l.unsubscribed)}</span>
                                </div>
                                <div className="contacts-extra-cell">
                                  Soft Bounced: <span className="contacts-extra-num">{this.num(l.soft_bounced)}</span>
                                </div>
                                <div className="contacts-extra-cell">
                                  Hard Bounced: <span className="contacts-extra-num">{this.num(l.bounced)}</span>
                                </div>
                                <div className="contacts-extra-cell">
                                  Complained: <span className="contacts-extra-num">{this.num(l.complained)}</span>
                                </div>
                                <div className="contacts-extra-cell">
                                  Inactive: <span className="contacts-extra-num">{this.num((l.bounced || 0) + (l.unsubscribed || 0) + (l.complained || 0))}</span>
                                </div>
                                <div className="contacts-extra-cell">
                                  Total: <span className="contacts-extra-num">{this.num(l.count)}</span>
                                </div>
                              </div>
                            </td>
                          </tr>
                        }>
                          <td style={{paddingTop:'28px',paddingBottom:'28px', minWidth: '250px'}}>
                            <ul className="list-inline" style={{whiteSpace: 'normal', borderRight: '1px solid', borderImage: 'linear-gradient(rgba(151, 151, 151, 0), #979797, rgba(151, 151, 151, 0)) 1'}}>
                              <li>
                                <h4>
                                  <Link to={'/contacts/find?id=' + l.id}>
                                    {l.name}
                                  </Link>
                                </h4>
                                {
                                  l.processing_error &&
                                  <p className="text-danger">
                                    {l.processing_error}
                                  </p>
                                }
                                {
                                  l.unapproved &&
                                  <OverlayTrigger placement="bottom" overlay={
                                    <Tooltip id="tooltip">
                                      Our team is reviewing the deliverability of your list data. We will notify you as soon as your data is approved for sending.
                                    </Tooltip>
                                  }>
                                    <p style={{
                                      color: '#8a6d3b',
                                    }}>
                                      Awaiting Approval
                                    </p>
                                  </OverlayTrigger>
                                }
                              </li>
                            </ul>
                          </td>
                          <td>
                            <h4>
                              {l.processing?
                                <span className="text-info">{l.processing}</span>
                                :
                                <span>{this.num((l.count || 0) - (l.bounced || 0) - (l.unsubscribed || 0) - (l.complained || 0))}</span>
                              }
                            </h4>
                          </td>
                          <td>
                            <ul className="list-inline m0">
                              <li className="graph-container center-over-graph">
                                <TablePie value={this.pctnum(l, l.active30)} size={60} thickness={7} color="#2dcca1"/>
                              </li>
                              <li className="graph-caption">
                                <h5 className="green-perc">{this.pct(l, l.active30)}</h5>
                                <p>{this.num(l.active30)}</p>
                              </li>
                            </ul>
                          </td>
                          <td>
                            <ul className="list-inline m0">
                              <li className="graph-container center-over-graph">
                                <TablePie value={this.pctnum(l, l.active60)} size={60} thickness={7} color="#4b7efe"/>
                              </li>
                              <li className="graph-caption">
                                <h5 className="blue-perc">{this.pct(l, l.active60)}</h5>
                                <p>{this.num(l.active60)}</p>
                              </li>
                            </ul>
                          </td>
                          <td>
                            <ul className="list-inline m0">
                              <li className="graph-container center-over-graph">
                                <TablePie value={this.pctnum(l, l.active90)} size={60} thickness={7} color="#f46767"/>
                              </li>
                              <li className="graph-caption">
                                <h5 className="red-perc">{this.pct(l, l.active90)}</h5>
                                <p>{this.num(l.active90)}</p>
                              </li>
                            </ul>
                          </td>
                          <td>
                            {
                              !l.domaincount ?
                                <div className="domain-count">
                                  {this.num(l.domaincount)}
                                </div>
                              :
                                <Link to={'/contacts/domains?id=' + l.id}>
                                  <div className="domain-count">
                                    {this.num(l.domaincount)}
                                  </div>
                                </Link>
                            }
                          </td>
                          <td className="last-cell">
                            <ConfirmDropdown
                              id={l.id + '-split'}
                              text="Actions"
                              menu="Delete"
                              title="Confirm Contact List Delete"
                              extra={true}
                              prompt={"Are you sure you wish to delete '" + l.name + "'?"}
                              onConfirm={this.deleteConfirmClicked.bind(this, l.id)}
                            >
                              <MenuItem onClick={() => {this.props.history.push('/contacts/find?id=' + l.id)}}>View Contacts</MenuItem>
                              <MenuItem disabled={(l.processing||l.unapproved)?true:false} onClick={this.addDataClicked.bind(this, l.id)}>Add Contacts</MenuItem>
                              <MenuItem disabled={(l.processing||l.unapproved)?true:false} onClick={this.addToAutomationClicked.bind(this, l)}>Add to Automation</MenuItem>
                              <MenuItem disabled={(l.processing||l.unapproved)?true:false} onClick={this.addUnsubsClicked.bind(this, l.id)}>Unsubscribe Contacts</MenuItem>
                              <MenuItem onClick={this.editNameClicked.bind(this, l.id)}>Edit Name</MenuItem>
                              {
                              this.props.user && !this.props.user.nodataexport &&
                              <MenuItem disabled={l.processing?true:false} onClick={this.exportClicked.bind(this, l.id)}>Export</MenuItem>
                              }
                            </ConfirmDropdown>
                          </td>
                        </EDTableRow>
                    )
                  }
                </EDTable>
                :
                <div className="text-center space-top-sm">
                  <h4>No contact lists yet!</h4>
                  <h5>Contact lists are flexible databases for your contacts. They store information about each contact in any combination of user-defined properties.</h5>
                </div>
            }
            </EDTableSection>
          </LoaderPanel>}
        </MenuNavbar>
      </div>
    );
  }
}

export default withLoadSave({
  extend: Contacts,
  initial: [],
  get: async () => _.sortBy((await axios.get('/api/lists')).data, l => l.name.toLowerCase()),
  extra: {
    automations: async () => (await axios.get('/api/automations')).data,
  },
});
