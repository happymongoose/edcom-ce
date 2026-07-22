import React, { Component } from "react";
import axios from "axios";
import LoaderPanel from "../components/LoaderPanel";
import LoaderButton from "../components/LoaderButton";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel, SelectLabel } from "../components/FormControls";
import { Button, Row, Col } from "react-bootstrap";
import SaveNavbar from "../components/SaveNavbar";
import { EDFormSection, EDFormBox } from "../components/EDDOM";
import parse from "../utils/parse";
import Select2 from 'react-select2-wrapper';
import _ from 'lodash';
import notify from "../utils/notify";

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
    };
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
                  <p>No published automations are available.</p>
              }
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
