import React, { Component } from "react";
import { Button, FormControl } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import shortid from "shortid";
import LoaderButton from "../components/LoaderButton";
import LoaderPanel from "../components/LoaderPanel";
import SaveNavbar from "../components/SaveNavbar";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel } from "../components/FormControls";
import { EDFormSection, EDFormBox, EDTable, EDTableRow } from "../components/EDDOM";
import getvalue from "../utils/getvalue";
import notify from "../utils/notify";

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
    draft: {
      nodes: data.draft.nodes,
    },
  };
}

class Automation extends Component {
  goBack = () => {
    this.props.history.push('/automations');
  }

  handleChange = event => {
    this.props.update({[event.target.id]: {$set: getvalue(event)}});
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

  handleSubmit = async event => {
    const isclose = this.props.formClose(event);

    const saved = await this.save();

    if (saved && isclose) {
      this.goBack();
    }
  }

  navbarButtons = () => {
    return (
      <LoaderButton
        id="automation-buttons-dropdown"
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
    );
  }

  renderNodeConfig(node, index) {
    if (node.type !== 'add_tag') {
      return null;
    }

    return (
      <FormControlLabel
        id="draft_tag"
        label="Draft tag config"
        obj={node}
        onChange={this.nodeChange.bind(this, index)}
        placeholder="Tag name to add later"
        help="Draft-only configuration. This is not validated or executable yet."
        space
      />
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
              <h4>Entry</h4>
              <p>Manual enrolment</p>
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
    entry: {
      type: 'manual',
    },
    draft: {
      nodes: [],
    },
  },
  get: async ({id}) => normalizeAutomation((await axios.get('/api/automations/' + id)).data),
  patch: ({id, data}) => axios.patch('/api/automations/' + id, patchPayload(data)),
});
