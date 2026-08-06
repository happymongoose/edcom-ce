import React, { Component } from "react";
import axios from "axios";
import LoaderPanel from "../components/LoaderPanel";
import LoaderButton from "../components/LoaderButton";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel, SelectLabel } from "../components/FormControls";
import { Button, Row, Col, Table } from "react-bootstrap";
import SaveNavbar from "../components/SaveNavbar";
import { EDFormSection, EDFormBox } from "../components/EDDOM";
import parse from "../utils/parse";
import Select2 from 'react-select2-wrapper';
import _ from 'lodash';
import notify from "../utils/notify";
import moment from "moment";
import { automationImpersonatedHref } from "./Automation";

const builtIn = ['Email', 'Opened', 'Clicked', 'Unsubscribed', 'Bounced', 'Complained', 'Soft Bounced'];

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

class ContactEdit extends Component {
  constructor(props) {
    super(props);

    this.state = {
      automationId: '',
      isEnrolling: false,
      emailHistory: null,
      emailHistoryPage: 1,
      isEmailHistoryLoading: false,
      memberships: null,
      isMembershipsLoading: false,
    };
    this.emailHistoryRequest = 0;
    this.membershipsRequest = 0;
  }

  componentDidMount() {
    if (this.props.data && this.props.data.email) {
      this.loadEmailHistory(1);
      this.loadMemberships();
    }
  }

  componentWillReceiveProps(nextProps) {
    const currentEmail = this.props.data && this.props.data.email;
    const nextEmail = nextProps.data && nextProps.data.email;
    if (nextEmail && nextEmail !== currentEmail) {
      this.loadEmailHistory(1, nextEmail);
      this.loadMemberships(nextEmail);
    }
  }

  handleChange = event => {
    this.props.update({properties: {[event.target.id]: {$set: event.target.value}}})
  }

  handleAutomationChange = event => {
    this.setState({automationId: event.target.value});
  }

  handleSubmit = async event => {
    var isclose = this.props.formClose(event);

    await this.props.save();

    if (isclose) {
      this.goBack();
    }
  }

  goBack = () => {
    var p = parse(this);
    this.props.history.push("/contacts/find?id=" + p.listid);
  }

  navbarButtons = () => {
    return (
      <LoaderButton
        id="contacts-list-buttons-dropdown"
        text="Save and Close"
        loadingText="Saving..."
        className="green"
        disabled={this.props.isSaving}
        onClick={this.props.formSubmit.bind(null, true)}
        splitItems={[
          { text: 'Save', onClick: this.props.formSubmit },
          { text: 'Cancel', onClick: this.goBack }
        ]}
      />
    )
  }

  addField = (event) => {
    const field = event.params.data.id;
    if (!field.trim() || this.props.data.properties.hasOwnProperty(field) || builtIn.includes(field)) {
      return;
    }
    if (field.includes('!') || field.includes(',')) {
      notify.show("Invalid field name, cannot match an existing field or contain '!' or ','", "error");
      return;
    }

    this.props.update({properties: {[field]: {$set: ''}}});
  }

  deleteField = (field, event) => {
    event.preventDefault();

    this.props.update({properties: {$unset: [field]}});
  }

  addSelectItem = (prop, event) => {
    if (!_.find(this.props.data[prop], t => t === event.params.data.id))
      this.props.update({[prop]: {$push: [event.params.data.id]}});
  }

  removeItem = (prop, index) => {
    this.props.update({[prop]: {$splice: [[index, 1]]}});
  }

  isValidNewField = (field) => {
    const trimmed = field.trim();
    return field && !this.props.data.properties.hasOwnProperty(trimmed) && !builtIn.includes(trimmed) && !trimmed.includes('!') && !trimmed.includes(',');
  }

  automationOptions() {
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

  enrolInAutomation = async () => {
    const automationId = this.state.automationId;
    if (!automationId || !this.props.data.email) {
      return;
    }

    this.setState({isEnrolling: true});
    try {
      await axios.post('/api/automations/' + automationId + '/enrolments', {
        email: this.props.data.email,
      });
      notify.show('Contact added to automation', 'success');
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to add contact to automation'), 'error');
    } finally {
      this.setState({isEnrolling: false});
    }
  }

  loadEmailHistory = async (page, email) => {
    const contactEmail = email || (this.props.data && this.props.data.email);
    if (!contactEmail) {
      return;
    }

    const requestId = ++this.emailHistoryRequest;
    this.setState({isEmailHistoryLoading: true, emailHistoryPage: page});
    try {
      const response = await axios.get('/api/contactdata/' + encodeURIComponent(contactEmail) + '/email-history', {
        params: {page},
      });
      if (requestId === this.emailHistoryRequest) {
        this.setState({emailHistory: response.data});
      }
    } catch (error) {
      if (requestId === this.emailHistoryRequest) {
        notify.show(errorMessage(error, 'Unable to load email history'), 'error');
      }
    } finally {
      if (requestId === this.emailHistoryRequest) {
        this.setState({isEmailHistoryLoading: false});
      }
    }
  }

  emailHistoryMaxPage() {
    const history = this.state.emailHistory;
    if (!history || !history.total) {
      return 1;
    }
    return Math.ceil(history.total / history.page_size);
  }

  previousEmailHistoryPage = () => {
    if (this.state.emailHistoryPage <= 1) {
      return;
    }
    this.loadEmailHistory(this.state.emailHistoryPage - 1);
  }

  nextEmailHistoryPage = () => {
    if (this.state.emailHistoryPage >= this.emailHistoryMaxPage()) {
      return;
    }
    this.loadEmailHistory(this.state.emailHistoryPage + 1);
  }

  loadMemberships = async email => {
    const contactEmail = email || (this.props.data && this.props.data.email);
    if (!contactEmail) {
      return;
    }

    const requestId = ++this.membershipsRequest;
    this.setState({isMembershipsLoading: true});
    try {
      const response = await axios.get('/api/contactdata/' + encodeURIComponent(contactEmail) + '/memberships');
      if (requestId === this.membershipsRequest) {
        this.setState({memberships: response.data});
      }
    } catch (error) {
      if (requestId === this.membershipsRequest) {
        notify.show(errorMessage(error, 'Unable to load contact memberships'), 'error');
      }
    } finally {
      if (requestId === this.membershipsRequest) {
        this.setState({isMembershipsLoading: false});
      }
    }
  }

  renderMembershipList(items, emptyText, hrefForItem) {
    if (!items || !items.length) {
      return <p>{emptyText}</p>;
    }
    return (
      <ul className="list-unstyled">
        {
          _.map(items, item =>
            <li key={item.id} style={{marginBottom: '6px'}}>
              <a href={hrefForItem(item)} target="_blank" rel="noopener noreferrer">
                {item.name || item.id}
              </a>
              {
                _.isNumber(item.count) &&
                <span className="text-muted"> ({item.count.toLocaleString()} contacts)</span>
              }
            </li>
          )
        }
      </ul>
    );
  }

  renderMemberships() {
    const memberships = this.state.memberships;
    if (this.state.isMembershipsLoading && !memberships) {
      return <p>Loading contact memberships...</p>;
    }

    const impersonateId = this.props.loggedInImpersonate;
    return (
      <div>
        <Row>
          <Col xs={12} md={6}>
            <h5>Contact lists</h5>
            {this.renderMembershipList(
              (memberships && memberships.lists) || [],
              'This contact is not currently in any contact lists.',
              item => automationImpersonatedHref('/contacts/find?id=' + item.id, impersonateId)
            )}
          </Col>
          <Col xs={12} md={6}>
            <h5>Segments</h5>
            {this.renderMembershipList(
              (memberships && memberships.segments) || [],
              'This contact is not currently in any segments.',
              item => automationImpersonatedHref('/segments/' + item.id + '/contacts?search=' + encodeURIComponent(this.props.data.email), impersonateId)
            )}
          </Col>
        </Row>
        {
          this.state.isMembershipsLoading &&
          <p>Refreshing contact memberships...</p>
        }
      </div>
    );
  }

  renderEmailHistory() {
    const history = this.state.emailHistory;
    const records = (history && history.records) || [];
    const maxPage = this.emailHistoryMaxPage();

    if (this.state.isEmailHistoryLoading && !history) {
      return <p>Loading email history...</p>;
    }

    if (!records.length) {
      return (
        <div>
          <p>No recent automation or transactional emails found for this contact.</p>
          {
            this.state.isEmailHistoryLoading &&
            <p>Refreshing email history...</p>
          }
        </div>
      );
    }

    return (
      <div>
        <Table responsive className="space15">
          <thead>
            <tr>
              <th>Sent</th>
              <th>Type</th>
              <th>Name / Source</th>
              <th>Subject</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {
              _.map(records, record =>
                <tr key={record.id}>
                  <td>{record.sent_at ? moment(record.sent_at).format('l LTS') : ''}</td>
                  <td>{record.source_type}</td>
                  <td>{record.source_name}</td>
                  <td>{record.subject}</td>
                  <td>{record.status}</td>
                </tr>
              )
            }
          </tbody>
        </Table>
        {
          maxPage > 1 &&
          <div className="form-inline space-bottom" style={{display: 'flex', gap: '16px', alignItems: 'center'}}>
            <Button
              type="button"
              style={{width: '120px'}}
              onClick={this.previousEmailHistoryPage}
              disabled={this.state.isEmailHistoryLoading || this.state.emailHistoryPage <= 1}
            >
              Previous
            </Button>
            <span>Page {this.state.emailHistoryPage} of {maxPage}</span>
            <Button
              type="button"
              style={{width: '120px'}}
              onClick={this.nextEmailHistoryPage}
              disabled={this.state.isEmailHistoryLoading || this.state.emailHistoryPage >= maxPage}
            >
              Next
            </Button>
          </div>
        }
        {
          this.state.isEmailHistoryLoading &&
          <p>Refreshing email history...</p>
        }
      </div>
    );
  }

  render() {
    var tagitems = _.map(_.filter(this.props.tags, l => !_.find(this.props.data.tags, id => id === l)), t => ({id: t, text: t}));
    var fields = _.filter(this.props.allfields, f => this.isValidNewField(f));
    var automationOptions = this.automationOptions();

    return (
      <SaveNavbar onBack={this.goBack} id={this.props.id} user={this.props.user}
                  title={"Edit Contact: " + this.props.id} buttons={this.navbarButtons()}
                  isSaving={this.props.isSaving}>
        <LoaderPanel isLoading={this.props.isLoading}>
          <EDFormSection onSubmit={this.handleSubmit} formRef={this.props.formRef}>
            <EDFormBox>
              <div className="text-center">
                <p>To create a new tag or field, type it into the input box and hit enter.</p>
              </div>
              <div className="campaign_box">
                <div className="edit_txt">
                  <Select2
                    data={tagitems}
                    value=""
                    onSelect={this.addSelectItem.bind(null, 'tags')}
                    style={{width:'240px'}}
                    options={{
                      tags: true,
                      placeholder: 'Add or Create Tag'
                    }}
                  />
                </div>
                <div className="form-group form_style">
                    <label>Tags</label>
                </div>
                {
                  (!this.props.data.tags || this.props.data.tags.length === 0) && <p className="text-center">None Selected</p>
                }
                <ul className="list-inline color_tag">
                  {
                    _.map(this.props.data.tags, (id, index) =>
                      <li key={id}>
                        <a href="#t" className={'gray_tag'} onClick={this.removeItem.bind(null, 'tags', index)}>
                          {id}
                        </a>
                      </li>
                    )
                  }
                </ul>
              </div>
              <div className="campaign_box space30">
                <div className="contact_box" style={{display: 'flex', justifyContent: 'space-between'}}>
                  <div className="form-group form_style">
                    <label>Fields</label>
                  </div>
                  <div className="edit_txt text-left">
                    <Select2
                      data={fields}
                      value=""
                      onSelect={this.addField}
                      style={{width:'240px'}}
                      options={{
                        tags: true,
                        placeholder: 'Add or Create Field'
                      }}
                    />
                  </div>
                </div>
                <Row>
                  <Col className="space15" xs={12} md={6} lg={4}>
                    <FormControlLabel
                      id="email"
                      readOnly={true}
                      label="Email"
                      obj={this.props.data}
                    />
                  </Col>
                  {
                    _.map(_.sortBy(_.keys(this.props.data.properties), p => p.toLowerCase()), key => {
                      if (builtIn.includes(key)) {
                        return;
                      }
                      return (
                        <Col className="space15" xs={12} md={6} lg={4} key={key}>
                          <FormControlLabel
                            id={key}
                            labelStyle={{width: '100%'}}
                            label={<div style={{display: 'flex', justifyContent: 'space-between'}}>
                                     <div>{key}</div>
                                     <div>
                                       <a href="#d" style={{fontSize: '14px'}} onClick={this.deleteField.bind(null, key)}>
                                         <i className="fa fa-trash"></i>
                                       </a>
                                     </div>
                                   </div>}
                            obj={this.props.data.properties}
                            onChange={this.handleChange}
                          />
                        </Col>
                      );
                    })
                  }
                </Row>
              </div>
            </EDFormBox>
            <EDFormBox space>
              <h4>List and Segment Memberships</h4>
              {this.renderMemberships()}
            </EDFormBox>
            <EDFormBox space>
              <h4>Automation Enrolment</h4>
              {
                automationOptions.length ?
                  <div className="form-inline">
                    <SelectLabel
                      id="automationId"
                      label="Automation"
                      obj={this.state}
                      onChange={this.handleAutomationChange}
                      options={automationOptions}
                      emptyVal="Select automation"
                      inline
                    />
                    {' '}
                    <Button
                      type="button"
                      bsStyle="primary"
                      disabled={this.state.isEnrolling || !this.state.automationId || !this.props.data.email}
                      onClick={this.enrolInAutomation}
                    >
                      {this.state.isEnrolling ? 'Adding...' : 'Add to automation'}
                    </Button>
                  </div>
                :
                  <p>No published or paused automations are available.</p>
              }
            </EDFormBox>
            <EDFormBox space>
              <h4>Recent automation and transactional emails</h4>
              {this.renderEmailHistory()}
            </EDFormBox>
          </EDFormSection>
        </LoaderPanel>
      </SaveNavbar>
    );
  }
}

export default withLoadSave({
  extend: ContactEdit,
  initial: {},
  get: async ({id}) => (await axios.get('/api/contactdata/' + id)).data,
  patch: async ({id, data}) => (await axios.patch('/api/contactdata/' + id, {
    tags: data.tags,
    properties: data.properties,
  })).data,
  extra: {
    tags: async() => (await axios.get('/api/recenttags')).data,
    allfields: async () => (await axios.get('/api/allfields')).data,
    automations: async () => (await axios.get('/api/automations')).data,
  },
});
