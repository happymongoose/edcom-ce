import React, { Component } from "react";
import { Button, FormControl } from "react-bootstrap";
import axios from "axios";
import Beforeunload from "react-beforeunload";
import { Prompt } from "react-router-dom";
import TemplateEditor from "../components/TemplateEditor";
import TemplateRawEditor from "../components/TemplateRawEditor";
import TemplateWYSIWYGEditor from "../components/TemplateWYSIWYGEditor";
import TemplateBeefreeEditor from "../components/TemplateBeefreeEditor";
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
  email.type = email.type || 'raw';
  email.rawText = email.rawText || '';
  email.parts = email.parts || [];
  email.bodyStyle = email.bodyStyle || {};
  return email;
}

function patchPayload(data) {
  return {
    name: data.name,
    subject: data.subject,
    preheader: data.preheader || '',
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
    };

    this._saveCB = null;
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
    this.update({[event.target.id]: {$set: getvalue(event)}});
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

  navbarButtons = () => {
    return (
      <div>
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
          fixed
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
          {
            this.state.changed &&
              <Beforeunload onBeforeunload={() => "Are you sure you want to exit without saving?"} />
          }
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
              <label className="control-label" htmlFor="type">Editor</label>
              {' '}
              <FormControl
                id="type"
                componentClass="select"
                value={this.props.data.type || ''}
                onChange={this.handleChange}
              >
                <option value="beefree">Drag and drop designer</option>
                <option value="wysiwyg">WYSIWYG editor</option>
                <option value="raw">HTML editor</option>
                <option value="">Legacy component editor</option>
              </FormControl>
            </EDFormBox>
            <EDFormBox space>
              {this.renderEditor()}
            </EDFormBox>
          </EDFormSection>
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
    type: 'raw',
    rawText: '',
    parts: [],
    bodyStyle: {},
  },
  get: async ({automation_id, email_id}) => normalizeEmail((await axios.get('/api/automations/' + automation_id + '/emails/' + email_id)).data),
  patch: ({automation_id, email_id, data}) => axios.patch('/api/automations/' + automation_id + '/emails/' + email_id, patchPayload(data)),
  extra: {
    allfields: async () => (await axios.get('/api/allfields')).data,
  },
});
