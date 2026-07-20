import React, { Component } from "react";
import { Button, FormControl } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
import shortid from "shortid";
import Select2 from "react-select2-wrapper";
import LoaderButton from "../components/LoaderButton";
import LoaderPanel from "../components/LoaderPanel";
import SaveNavbar from "../components/SaveNavbar";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel, SelectLabel } from "../components/FormControls";
import { EDFormSection, EDFormBox, EDTable, EDTableRow } from "../components/EDDOM";
import fixTag from "../utils/fixtag";
import getvalue from "../utils/getvalue";
import notify from "../utils/notify";

import "react-select2-wrapper/css/select2.css";

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

function normalizeAutomation(automation) {
  automation.entry = automation.entry || {type: 'manual'};
  automation.entry.type = 'manual';
  automation.reentry = automation.reentry || 'once';
  automation.draft = automation.draft || {};
  automation.draft.nodes = automation.draft.nodes || [];
  return automation;
}

function patchPayload(data) {
  return {
    name: data.name,
    entry: {
      type: 'manual',
    },
    reentry: data.reentry || 'once',
    draft: {
      nodes: data.draft.nodes,
    },
  };
}

class Automation extends Component {
  constructor(props) {
    super(props);

    this.state = {
      isPublishing: false,
      isEnrolling: false,
      runningEnrolmentId: null,
      enrolEmail: '',
    };
  }

  goBack = () => {
    this.props.history.push('/automations');
  }

  handleChange = event => {
    this.props.update({[event.target.id]: {$set: getvalue(event)}});
  }

  enrolEmailChange = event => {
    this.setState({enrolEmail: event.target.value});
  }

  nodeChange = (index, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            [event.target.id]: {$set: getvalue(event)},
          },
        },
      },
    });
  }

  nodeTagChange = (index, event) => {
    this.props.update({
      draft: {
        nodes: {
          [index]: {
            draft_tag: {$set: event.params.data.id},
          },
        },
      },
    });
  }

  tagData() {
    const tags = this.props.tags || [];
    const nodes = (this.props.data.draft && this.props.data.draft.nodes) || [];
    const draftTags = _.pluck(_.filter(nodes, node => node.type === 'add_tag' && node.draft_tag), 'draft_tag');

    return _.map(_.uniq(tags.concat(draftTags)), tag => ({id: tag, text: tag}));
  }

  addNode = type => {
    const node = {
      id: shortid.generate(),
      type: type,
      label: type === 'add_tag' ? 'Add tag' : 'Exit automation',
    };

    if (type === 'add_tag') {
      node.draft_tag = '';
    }

    this.props.update({
      draft: {
        nodes: {
          $push: [node],
        },
      },
    });
  }

  deleteNode = index => {
    this.props.update({
      draft: {
        nodes: {
          $splice: [[index, 1]],
        },
      },
    });
  }

  save = async () => {
    try {
      await this.props.save(patchPayload(this.props.data));
      notify.show('Automation saved', 'success');
      return true;
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to save automation'), 'error');
      return false;
    }
  }

  publish = async () => {
    this.setState({isPublishing: true});

    try {
      const saved = await this.save();
      if (!saved) {
        return;
      }

      await axios.post('/api/automations/' + this.props.id + '/publish');
      notify.show('Automation published', 'success');
      await this.props.reload();
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to publish automation'), 'error');
    } finally {
      this.setState({isPublishing: false});
    }
  }

  enrolContact = async event => {
    event.preventDefault();

    const email = this.state.enrolEmail.trim();
    if (!email) {
      return;
    }

    this.setState({isEnrolling: true});
    try {
      await axios.post('/api/automations/' + this.props.id + '/enrolments', {email: email});
      notify.show('Contact enrolled', 'success');
      this.setState({enrolEmail: ''});
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to enrol contact'), 'error');
    } finally {
      this.setState({isEnrolling: false});
    }
  }

  runNext = async enrolment => {
    this.setState({runningEnrolmentId: enrolment.id});

    try {
      await axios.post('/api/automations/' + this.props.id + '/enrolments/' + enrolment.id + '/run-next');
      notify.show('Automation test step ran', 'success');
      await this.props.reloadExtra();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to run next automation step'), 'error');
    } finally {
      this.setState({runningEnrolmentId: null});
    }
  }

  handleSubmit = async event => {
    const isclose = this.props.formClose(event);

    const saved = await this.save();

    if (saved && isclose) {
      this.goBack();
    }
  }

  navbarButtons = () => {
    return (
      <div>
        <Button
          bsStyle="primary"
          disabled={this.props.isSaving || this.state.isPublishing}
          onClick={this.publish}
        >
          {this.state.isPublishing ? 'Publishing...' : 'Publish'}
        </Button>
        {' '}
        <LoaderButton
          id="automation-buttons-dropdown"
          text="Save and Close"
          loadingText="Saving..."
          className="green"
          disabled={this.props.isSaving || this.state.isPublishing}
          onClick={this.props.formSubmit.bind(null, true)}
          splitItems={[
            { text: 'Save', onClick: this.props.formSubmit },
            { text: 'Cancel', onClick: this.goBack }
          ]}
        />
      </div>
    );
  }

  renderNodeConfig(node, index) {
    if (node.type !== 'add_tag') {
      return null;
    }

    return (
      <div style={{minWidth: '220px'}}>
        <Select2
          data={this.tagData()}
          value={node.draft_tag || ''}
          onSelect={this.nodeTagChange.bind(this, index)}
          style={{width:'100%'}}
          options={{
            placeholder: 'Select or create tag',
            tags: true,
            createTag: function (params) {
              const fixed = fixTag(params.term);
              if (!fixed) {
                return null;
              }
              return {
                id: fixed,
                text: fixed,
              };
            }
          }}
        />
        <span className="help-block">Draft-only configuration. This is not validated or executable yet.</span>
      </div>
    );
  }

  renderEnrolments() {
    const data = this.props.data;
    const enrolments = this.props.enrolments || [];

    if (!data.published_at) {
      return (
        <EDFormBox space>
          <h4>Enrolments</h4>
          <p>Publish this automation before contacts can be enrolled.</p>
        </EDFormBox>
      );
    }

    return (
      <EDFormBox space>
        <div className="flex-items space-between">
          <h4>Enrolments</h4>
          <form className="form-inline" onSubmit={this.enrolContact}>
            <FormControl
              type="email"
              value={this.state.enrolEmail}
              onChange={this.enrolEmailChange}
              placeholder="Existing contact email"
              style={{width: '240px'}}
              disabled={this.state.isEnrolling}
            />
            {' '}
            <LoaderButton
              type="submit"
              bsStyle="primary"
              text="Enrol Contact"
              loadingText="Enrolling..."
              isLoading={this.state.isEnrolling}
              disabled={this.state.isEnrolling || !this.state.enrolEmail.trim()}
            />
          </form>
        </div>
        {
          enrolments.length ?
            <EDTable className="growing-margin-left" minWidth="600px" maxWidth="1024px">
              <thead>
                <tr>
                  <th>Contact</th>
                  <th>Status</th>
                  <th>Current Node</th>
                  <th>Source</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              {
                _.map(enrolments, (enrolment, index) =>
                  <EDTableRow key={enrolment.id} index={index}>
                    <td>
                      <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.contact_email}</h4>
                    </td>
                    <td>
                      <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.status}</h4>
                    </td>
                    <td>
                      <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.current_node_id}</h4>
                    </td>
                    <td>
                      <h4 style={{whiteSpace: 'nowrap'}}>{enrolment.source}</h4>
                    </td>
                    <td>
                      <h4 style={{whiteSpace: 'nowrap'}}>
                        {enrolment.created ? moment(enrolment.created).format('lll') : ''}
                      </h4>
                    </td>
                    <td className="last-cell" style={{minWidth: '120px'}}>
                      {
                        enrolment.status === 'ready' ?
                          <Button
                            bsSize="small"
                            disabled={this.state.runningEnrolmentId === enrolment.id}
                            onClick={this.runNext.bind(this, enrolment)}
                          >
                            {
                              this.state.runningEnrolmentId === enrolment.id ?
                                'Running...'
                              :
                                'Run next test'
                            }
                          </Button>
                        :
                          null
                      }
                    </td>
                  </EDTableRow>
                )
              }
            </EDTable>
          :
            <div className="text-center space-top-sm">
              <h4>No contacts are enrolled yet.</h4>
            </div>
        }
      </EDFormBox>
    );
  }

  render() {
    const data = this.props.data;
    const nodes = (data.draft && data.draft.nodes) || [];

    return (
      <SaveNavbar title={'Edit Automation'} user={this.props.user} isSaving={this.props.isSaving}
        onBack={this.goBack} buttons={this.navbarButtons()} id={this.props.id}>
        <LoaderPanel isLoading={this.props.isLoading}>
          <EDFormSection onSubmit={this.handleSubmit} formRef={this.props.formRef}>
            <EDFormBox>
              <FormControlLabel
                id="name"
                label="Name"
                obj={data}
                onChange={this.handleChange}
                required={true}
              />
              <FormControlLabel
                id="status"
                label="Status"
                obj={data}
                roph
                space
              />
            </EDFormBox>
            <EDFormBox space>
              <h4>Published Definition</h4>
              {
                data.published_at ?
                  <p>
                    Published {moment(data.published_at).format('lll')}
                    {data.published_revision ? ' (revision ' + data.published_revision + ')' : ''}
                  </p>
                :
                  <p>Not published</p>
              }
            </EDFormBox>
            <EDFormBox space>
              <h4>Entry</h4>
              <p>Manual enrolment</p>
              <SelectLabel
                id="reentry"
                label="Contact re-entry"
                obj={data}
                onChange={this.handleChange}
                options={[
                  {id: 'once', name: 'Enter once'},
                  {id: 'multiple', name: 'Enter multiple times'},
                ]}
                space
              />
            </EDFormBox>
            <EDFormBox space>
              <div className="flex-items space-between">
                <h4>Draft Workflow</h4>
                <div>
                  <Button onClick={this.addNode.bind(this, 'add_tag')}>Add Tag Node</Button>
                  {' '}
                  <Button onClick={this.addNode.bind(this, 'exit')}>Add Exit Node</Button>
                </div>
              </div>
              {
                nodes.length ?
                  <EDTable className="growing-margin-left" minWidth="600px" maxWidth="1024px">
                    <thead>
                      <tr>
                        <th>Order</th>
                        <th>Type</th>
                        <th>Label</th>
                        <th>Configuration</th>
                        <th></th>
                      </tr>
                    </thead>
                    {
                      _.map(nodes, (node, index) =>
                        <EDTableRow key={node.id} index={index}>
                          <td>
                            <h4>{index + 1}</h4>
                          </td>
                          <td>
                            <h4 style={{whiteSpace: 'nowrap'}}>
                              {node.type === 'add_tag' ? 'Add tag' : 'Exit'}
                            </h4>
                          </td>
                          <td>
                            <FormControl
                              id="label"
                              value={node.label}
                              onChange={this.nodeChange.bind(this, index)}
                              required={true}
                            />
                          </td>
                          <td>
                            {this.renderNodeConfig(node, index)}
                          </td>
                          <td style={{minWidth: '92px'}} className="last-cell">
                            <Button onClick={this.deleteNode.bind(this, index)}>Delete</Button>
                          </td>
                        </EDTableRow>
                      )
                    }
                  </EDTable>
                :
                  <div className="text-center space-top-sm">
                    <h4>This draft does not have any nodes yet.</h4>
                  </div>
              }
            </EDFormBox>
            {this.renderEnrolments()}
          </EDFormSection>
        </LoaderPanel>
      </SaveNavbar>
    );
  }
}

export default withLoadSave({
  extend: Automation,
  initial: {
    name: '',
    status: 'draft',
    reentry: 'once',
    entry: {
      type: 'manual',
    },
    draft: {
      nodes: [],
    },
  },
  get: async ({id}) => normalizeAutomation((await axios.get('/api/automations/' + id)).data),
  patch: ({id, data}) => axios.patch('/api/automations/' + id, patchPayload(data)),
  extra: {
    tags: async () => (await axios.get('/api/recenttags')).data,
    enrolments: async ({id}) => (await axios.get('/api/automations/' + id + '/enrolments')).data,
  },
});
