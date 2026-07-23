import React, { Component } from "react";
import { Button, Row, Col } from "react-bootstrap";
import axios from "axios";
import Beforeunload from "react-beforeunload";
import { Prompt } from "react-router-dom";
import TemplateEditor from "../components/TemplateEditor";
import TemplateRawEditor from "../components/TemplateRawEditor";
import TemplateWYSIWYGEditor from "../components/TemplateWYSIWYGEditor";
import TemplateBeefreeEditor from "../components/TemplateBeefreeEditor";
import TestButton from "../components/TestButton";
import LoaderButton from "../components/LoaderButton";
import LoaderPanel from "../components/LoaderPanel";
import SaveNavbar from "../components/SaveNavbar";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel } from "../components/FormControls";
import { EDFormSection, EDFormBox } from "../components/EDDOM";
import getvalue from "../utils/getvalue";
import notify from "../utils/notify";

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

function normalizeEmail(email) {
  email.name = email.name || 'New automation email';
  email.subject = email.subject || 'Click Here to Edit';
  email.preheader = email.preheader || '';
  email.fromname = email.fromname || '';
  email.fromemail = email.fromemail || '';
  email.replyto = email.replyto || '';
  email.returnpath = email.returnpath || '';
  if (email.type === undefined || email.type === null) {
    email.type = 'raw';
  }
  email.rawText = email.rawText || '';
  email.parts = email.parts || [];
  email.bodyStyle = email.bodyStyle || {};
  if (!email.type && !email.parts.length) {
    email.initialize = true;
  }
  return email;
}

function patchPayload(data) {
  return {
    name: data.name,
    subject: data.subject,
    preheader: data.preheader || '',
    fromname: data.fromname || '',
    fromemail: data.fromemail || '',
    replyto: data.replyto || '',
    returnpath: data.returnpath || '',
    type: data.type || '',
    rawText: data.rawText || '',
    parts: data.parts || [],
    bodyStyle: data.bodyStyle || {},
  };
}

class AutomationEmail extends Component {
  constructor(props) {
    super(props);

    this.state = {
      changed: false,
      showTestEmailModal: false,
      showReplyTo: false,
      showFromEmail: false,
    };

    this._saveCB = null;
    this._fromSet = false;
  }

  componentWillReceiveProps(nextProps) {
    if (
      nextProps.user &&
      !nextProps.data.fromname &&
      !nextProps.data.returnpath &&
      !this._fromSet
    ) {
      nextProps.update({
        fromname: {$set: nextProps.user.fullname},
        returnpath: {$set: nextProps.user.username},
      });
    }
  }

  goBack = () => {
    this.setState({changed: false}, () => {
      this.props.history.push('/automations/' + this.props.data.automation_id);
    });
  }

  update = (u, cb) => {
    this.setState({changed: true});
    this.props.update(u, cb);
  }

  handleChange = event => {
    if (event.target.id === 'fromname' || event.target.id === 'returnpath') {
      this._fromSet = true;
    }
    this.update({[event.target.id]: {$set: getvalue(event)}});
  }

  showReplyTo = event => {
    event.preventDefault();
    this.setState({showReplyTo: true});
  }

  showFromEmail = event => {
    event.preventDefault();
    this.setState({showFromEmail: true});
  }

  replyToVisible = () => {
    return this.state.showReplyTo || this.props.data.replyto;
  }

  fromEmailVisible = () => {
    return this.state.showFromEmail || this.props.data.fromemail;
  }

  save = async () => {
    if (this._saveCB) {
      await this._saveCB();
    }

    if (!this.props.data.name || !this.props.data.name.trim()) {
      notify.show('Email name is required', 'error');
      return false;
    }
    if (!this.props.data.subject || !this.props.data.subject.trim()) {
      notify.show('Subject is required', 'error');
      return false;
    }

    try {
      await this.props.save(patchPayload(this.props.data));
      this.setState({changed: false});
      notify.show('Automation email saved', 'success');
      return true;
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to save automation email'), 'error');
      return false;
    }
  }

  handleSubmit = async event => {
    const isclose = this.props.formClose(event);
    const saved = await this.save();
    if (saved && isclose) {
      this.goBack();
    }
  }

  saveAndClose = async () => {
    const saved = await this.save();
    if (saved) {
      this.goBack();
    }
  }

  updateEmails = emails => {
    axios.patch('/api/testemails', emails);
  }

  toggleTestEmailModal = () => {
    this.setState({showTestEmailModal: true});
  }

  setTestEmailModal = show => {
    this.setState({showTestEmailModal: show});
  }

  sendTest = async (to, route, json, includeInLog) => {
    const saved = await this.save();
    if (!saved) {
      return;
    }

    try {
      await axios.post('/api/automations/' + this.props.automation_id + '/emails/' + this.props.email_id + '/test', {
        to: to,
        route: route,
        include_in_log: includeInLog,
      });

      await this.props.reloadUser();
      this.props.reloadExtra();

      notify.show('Test email submitted', "success", 5000);
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to send test email'), 'error');
    }
  }

  navbarButtons = () => {
    return (
      <div>
        <LoaderButton
          id="automation-email-test-button"
          text="Send Test Email"
          loadingText="Saving..."
          disabled={this.props.isSaving}
          onClick={this.toggleTestEmailModal}
        />
        {' '}
        <Button
          bsStyle="primary"
          disabled={this.props.isSaving}
          onClick={this.save}
        >
          Save
        </Button>
        {' '}
        <LoaderButton
          id="automation-email-buttons-dropdown"
          text="Save and Close"
          loadingText="Saving..."
          className="green"
          disabled={this.props.isSaving}
          onClick={this.saveAndClose}
          splitItems={[
            { text: 'Cancel', onClick: this.goBack }
          ]}
        />
      </div>
    );
  }

  renderEditor() {
    const data = this.props.data;

    if (!data.type) {
      return (
        <TemplateEditor
          user={this.props.user}
          data={data}
          update={this.update}
          fields={this.props.allfields}
        />
      );
    }

    if (data.type === 'beefree') {
      return (
        <TemplateBeefreeEditor
          data={data}
          update={this.update}
          onChange={() => this.setState({changed: true})}
          setSaveCB={cb => this._saveCB = cb}
          fullScreen={true}
          fields={this.props.allfields}
          loggedInImpersonate={this.props.loggedInImpersonate}
          user={this.props.user}
          nospace
        />
      );
    }

    if (data.type === 'raw') {
      return (
        <TemplateRawEditor
          data={data}
          update={this.update}
          fields={this.props.allfields}
        />
      );
    }

    return (
      <TemplateWYSIWYGEditor
        data={data}
        update={this.update}
        fields={this.props.allfields}
        loggedInUID={this.props.loggedInUID}
        loggedInCookie={this.props.loggedInCookie}
        loggedInImpersonate={this.props.loggedInImpersonate}
        nospace
      />
    );
  }

  render() {
    const title = 'Edit Automation Email';

    return (
      <SaveNavbar title={title} user={this.props.user} isSaving={this.props.isSaving}
        onBack={this.goBack} buttons={this.navbarButtons()} id={this.props.data.id}>
        <LoaderPanel isLoading={this.props.isLoading}>
          <div className="automation-email-editor-page">
          {
            this.state.changed &&
              <Beforeunload onBeforeunload={() => "Are you sure you want to exit without saving?"} />
          }
          <span style={{display: 'none'}}>
            <TestButton
              emails={this.props.testemails}
              onConfirm={this.sendTest}
              onUpdate={this.updateEmails}
              disabled={this.props.isSaving}
              routes={this.props.routes}
              toggleModal={this.setTestEmailModal}
              showModal={this.state.showTestEmailModal}
              lasttest={this.props.lasttest}
              showIncludeInLogCheckbox={true}
            />
          </span>
          <Prompt when={this.state.changed} message="Are you sure you want to exit without saving?" />
          <EDFormSection onSubmit={this.handleSubmit} formRef={this.props.formRef}>
            <EDFormBox>
              <FormControlLabel
                id="name"
                label="Internal name"
                obj={this.props.data}
                onChange={this.handleChange}
                required
              />
              <FormControlLabel
                id="subject"
                label="Subject"
                obj={this.props.data}
                onChange={this.handleChange}
                required
                space
              />
              <FormControlLabel
                id="preheader"
                label="Preheader"
                obj={this.props.data}
                onChange={this.handleChange}
                space
              />
              <Row>
                <Col md={6}>
                  <FormControlLabel
                    id="fromname"
                    label="From Name"
                    obj={this.props.data}
                    onChange={this.handleChange}
                    space
                  />
                </Col>
                <Col md={6}>
                  <FormControlLabel
                    id="returnpath"
                    label="Sender Email Address"
                    obj={this.props.data}
                    onChange={this.handleChange}
                    space
                  />
                  { !this.replyToVisible() &&
                    <div>
                      <a href="#replyto" onClick={this.showReplyTo}>Add alternate Reply-To address</a>
                    </div>
                  }
                  { !this.fromEmailVisible() &&
                    <div>
                      <a href="#mailfrom" onClick={this.showFromEmail}>Add alternate From Email address</a>
                    </div>
                  }
                </Col>
              </Row>
              <Row>
                <Col md={6}>
                  { this.fromEmailVisible() &&
                    <FormControlLabel
                      id="fromemail"
                      label="From Email"
                      obj={this.props.data}
                      onChange={this.handleChange}
                    />
                  }
                </Col>
                <Col md={6}>
                  { this.replyToVisible() &&
                    <FormControlLabel
                      id="replyto"
                      label="Reply-To Email"
                      obj={this.props.data}
                      onChange={this.handleChange}
                    />
                  }
                </Col>
              </Row>
            </EDFormBox>
            <EDFormBox space>
              {this.renderEditor()}
            </EDFormBox>
          </EDFormSection>
          </div>
        </LoaderPanel>
      </SaveNavbar>
    );
  }
}

export default withLoadSave({
  extend: AutomationEmail,
  initial: {
    name: '',
    subject: '',
    preheader: '',
    fromname: '',
    fromemail: '',
    replyto: '',
    returnpath: '',
    type: 'raw',
    rawText: '',
    parts: [],
    bodyStyle: {},
  },
  get: async ({automation_id, email_id}) => normalizeEmail((await axios.get('/api/automations/' + automation_id + '/emails/' + email_id)).data),
  patch: ({automation_id, email_id, data}) => axios.patch('/api/automations/' + automation_id + '/emails/' + email_id, patchPayload(data)),
  extra: {
    allfields: async () => (await axios.get('/api/allfields')).data,
    testemails: async () => (await axios.get('/api/testemails')).data,
    routes: async () => (await axios.get('/api/userroutes')).data,
    lasttest: async () => (await axios.get('/api/lasttest')).data,
  },
});
