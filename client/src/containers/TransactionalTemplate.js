import React, { Component } from "react";
import withLoadSave from "../components/LoadSave";
import LoaderPanel from "../components/LoaderPanel";
import { FormControlLabel } from "../components/FormControls";
import TemplateEditor from "../components/TemplateEditor";
import TemplateRawEditor from "../components/TemplateRawEditor";
import TemplateWYSIWYGEditor from "../components/TemplateWYSIWYGEditor";
import TemplateBeefreeEditor from "../components/TemplateBeefreeEditor";
import { ControlLabel, FormGroup, Row, Col } from "react-bootstrap";
import axios from "axios";
import SaveNavbar from "../components/SaveNavbar";
import TestButton from "../components/TestButton";
import notify from "../utils/notify";
import { EDFormSection, EDFormBox } from "../components/EDDOM";
import _ from "underscore";
import LoaderButton from "../components/LoaderButton";
import TemplateHeader from "../components/TemplateHeader";
import fixTag from "../utils/fixtag";
import Select2 from "react-select2-wrapper";
import getvalue from "../utils/getvalue";
import Beforeunload from "react-beforeunload"
import { Prompt } from "react-router-dom";

class TransactionalTemplate extends Component {
  constructor(props) {
    super(props);

    this.state = {
      changed: false,
    };

    this._saveCB = null;
  }

  save = async () => {
    if (this._saveCB) {
      await this._saveCB();
    }
    
    return this.props.save();
  }

  handleSubmit = async event => {
    var isclose = this.props.formClose(event);

    await this.save();
    await this.props.reloadUser(); // for footer

    if (isclose) {
      this.goBack();
    } else {
      this.setState({changed: false});
    }
  }

  goBack = () => {
    this.setState({changed: false}, () => {
      this.props.history.push('/transactional/templates');
    });
  }

  onChange = event => {
    var id = event.target.id;
    var val = getvalue(event);
    this.setState({changed: true});
    this.props.update({[id]: {$set: val}});
  }

  validateForm = () => {
    if (!this.props.data.name) {
      return "Please enter a template name to send tests";
    }
    return null;
  }

  updateEmails = emails => {
    axios.patch('/api/testemails', emails);
  }

  sendTest = async (to, route, json, includeInLog) => {
    await this.save();

    await axios.post('/api/transactional/templates/' + this.props.id + '/test', {
      to: to,
      route: route,
      json: json,
      include_in_log: includeInLog,
    });

    await this.props.reloadUser();

    this.props.reloadExtra();

    notify.show('Test email submitted', "success", 5000);
  }

  navbarButtons = () => {
    return (
      <LoaderButton
        id="template-buttons-dropdown"
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

  tagData() {
    if (!this.props.tags)
      return [];
    if (_.isUndefined(this._tags)) {
      if (this.props.data.tag) {
        this._tags = _.uniq(this.props.tags.concat([this.props.data.tag]));
      } else {
        this._tags = _.uniq(this.props.tags);
      }
    }
    return this._tags;
  }

  onTagChange = event => {
    var id = event.target.id;
    var val = getvalue(event);
    this.setState({changed: true});
    this.props.update({[id]: {$set: val}});
  }

  update = (u, cb) => {
    this.setState({changed: true});
    this.props.update(u, cb);
  }

  render() {
    return (
      <LoaderPanel isLoading={this.props.isLoading}>
        {
          this.state.changed &&
            <Beforeunload onBeforeunload={() => "Are you sure you want to exit without saving?"} />
        }
        <Prompt when={this.state.changed} message="Are you sure you want to exit without saving?" />
        <SaveNavbar title="Edit Template" user={this.props.user} buttons={this.navbarButtons()}
          isSaving={this.props.isSaving} onBack={this.goBack} id={this.props.id}>
          <EDFormSection onSubmit={this.handleSubmit} formRef={this.props.formRef} nobottomspace={true}>
            <EDFormBox>
              <FormControlLabel
                id="name"
                label="Name"
                obj={this.props.data}
                onChange={this.onChange}
                required={true}
              />
              <div className="space20"/>
              <TemplateHeader user={this.props.user} data={this.props.data} update={this.props.update} transactional={true} />
              <ControlLabel className="space20">Message Tag</ControlLabel>
              <Select2
                id="tag"
                value={this.props.data.tag}
                data={this.tagData()}
                onSelect={this.onTagChange}
                style={{width:'100%'}}
                options={{
                  tags: true,
                  createTag: function (params) {
                    const fixed = fixTag(params.term);
                    if (!fixed) {
                      return null;
                    }
                    return {
                      id: fixTag(params.term),
                      text: fixTag(params.term)
                    }
                  }
                }}
              />
              <FormControlLabel
                id="id"
                label="Template ID for API Calls"
                obj={this.props}
                readOnly
                style={{width: '250px'}}
                space
              />
            </EDFormBox>
            <Row className="space50">
              <Col md={6} sm={6}>
                {
                  this.props.data.type !== 'raw' &&
                    <FormControlLabel
                      id="preheader"
                      label="Prevew text pre-header (optional)"
                      obj={this.props.data}
                      onChange={this.onChange}
                    />
                }
              </Col>
              <Col md={6} sm={6}>
                <TestButton
                  preCheck={this.validateForm}
                  emails={this.props.testemails}
                  routes={this.props.routes}
                  onConfirm={this.sendTest}
                  disabled={this.props.isSaving}
                  onUpdate={this.updateEmails}
                  useJson={true}
                  showIncludeInLogCheckbox={true}
                />
              </Col>
            </Row>
            <FormGroup className={this.props.data.type === 'beefree' ? "nobottomspace" : ""}>
              {
                !this.props.data.type?
                  <TemplateEditor user={this.props.user} data={this.props.data} update={this.update} transactional={true} />
                :
                  this.props.data.type === 'beefree' ?
                  <TemplateBeefreeEditor data={this.props.data} update={this.update}
                    onChange={() => this.setState({changed: true})}
                    setSaveCB={cb => this._saveCB = cb}
                    loggedInImpersonate={this.props.loggedInImpersonate}
                    user={this.props.user} transactional={true} />
                  :
                    this.props.data.type === 'raw' ?
                      <TemplateRawEditor data={this.props.data} update={this.update} transactional={true} />
                    :
                      <TemplateWYSIWYGEditor data={this.props.data} update={this.update} loggedInUID={this.props.loggedInUID}
                        loggedInCookie={this.props.loggedInCookie} loggedInImpersonate={this.props.loggedInImpersonate} transactional={true} />
              }
            </FormGroup>
          </EDFormSection>
        </SaveNavbar>
      </LoaderPanel>
    );
  }
}

export default withLoadSave({
  extend: TransactionalTemplate,
  initial: [],
  get: async ({id}) => (await axios.get('/api/transactional/templates/' + id)).data,
  patch: ({id, data}) => axios.patch('/api/transactional/templates/' + id, data),
  extra: {
    testemails: async () => (await axios.get('/api/testemails')).data,
    routes: async () => (await axios.get('/api/userroutes')).data,
    tags: async () => (await axios.get('/api/transactional/recenttags')).data,
  }
});
