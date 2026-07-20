import React, { Component } from "react";
import { Button, FormControl, MenuItem, Modal } from "react-bootstrap";
import { Link } from "react-router-dom";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
import ConfirmDropdown from "../components/ConfirmDropdown";
import LoaderPanel from "../components/LoaderPanel";
import MenuNavbar from "../components/MenuNavbar";
import TitlePage from "../components/TitlePage";
import withLoadSave from "../components/LoadSave";
import { EDFormGroup, EDTableSection, EDTable, EDTableRow } from "../components/EDDOM";
import notify from "../utils/notify";

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

class Automations extends Component {
  constructor(props) {
    super(props);

    this.state = {
      showNameModal: false,
      modalMode: 'create',
      automationId: null,
      name: '',
      isSaving: false,
    };
  }

  createClicked = () => {
    this.setState({
      showNameModal: true,
      modalMode: 'create',
      automationId: null,
      name: '',
    });
  }

  renameClicked = automation => {
    this.setState({
      showNameModal: true,
      modalMode: 'rename',
      automationId: automation.id,
      name: automation.name,
    });
  }

  openClicked = automation => {
    this.props.history.push('/automations/' + automation.id);
  }

  closeNameModal = () => {
    if (this.state.isSaving) {
      return;
    }

    this.setState({
      showNameModal: false,
      automationId: null,
      name: '',
    });
  }

  nameChanged = event => {
    this.setState({name: event.target.value});
  }

  saveName = async event => {
    event.preventDefault();

    const name = this.state.name.trim();
    if (!name) {
      return;
    }

    this.setState({isSaving: true});
    try {
      if (this.state.modalMode === 'create') {
        await axios.post('/api/automations', {name: name});
      } else {
        await axios.patch('/api/automations/' + this.state.automationId, {name: name});
      }

      this.setState({
        showNameModal: false,
        automationId: null,
        name: '',
      });
      await this.props.reload();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to save automation'), 'error');
    } finally {
      this.setState({isSaving: false});
    }
  }

  deleteConfirmClicked = async automation => {
    try {
      await axios.delete('/api/automations/' + automation.id);
      await this.props.reload();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to delete automation'), 'error');
    }
  }

  renderNameModal() {
    const creating = this.state.modalMode === 'create';

    return (
      <Modal show={this.state.showNameModal}>
        <form onSubmit={this.saveName}>
          <Modal.Header>
            <Modal.Title>{creating ? 'Create Automation' : 'Rename Automation'}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <EDFormGroup space>
              <label>Name</label>
              {' '}
              <FormControl
                id="name"
                autoFocus
                value={this.state.name}
                onChange={this.nameChanged}
                required={true}
              />
            </EDFormGroup>
          </Modal.Body>
          <Modal.Footer>
            <Button
              type="submit"
              bsStyle="primary"
              disabled={this.state.isSaving || !this.state.name.trim()}
            >
              {this.state.isSaving ? 'Saving...' : 'Save'}
            </Button>
            <Button onClick={this.closeNameModal} disabled={this.state.isSaving}>Cancel</Button>
          </Modal.Footer>
        </form>
      </Modal>
    );
  }

  render() {
    let minWidth = '600px';
    let maxWidth = '1024px';

    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="Automations" button={
          <Button bsStyle="primary" onClick={this.createClicked}>Create New Automation</Button>
        } />
        <LoaderPanel isLoading={this.props.isLoading}>
          <EDTableSection className="contact drop-blue">
            {
              this.props.data.length ?
                <EDTable className="growing-margin-left" minWidth={minWidth} maxWidth={maxWidth}>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Status</th>
                      <th>Modified</th>
                      <th></th>
                    </tr>
                  </thead>
                  {
                    _.map(this.props.data, (automation, index) =>
                      <EDTableRow key={automation.id} index={index}>
                        <td>
                          <ul className="list-inline first-tr">
                            <li>
                              <h4 style={{whiteSpace: 'nowrap'}}>
                                <Link to={'/automations/' + automation.id}>
                                  {automation.name}
                                </Link>
                              </h4>
                            </li>
                          </ul>
                        </td>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>
                            Draft
                          </h4>
                        </td>
                        <td>
                          <h4 style={{whiteSpace: 'nowrap'}}>
                            {automation.modified ? moment(automation.modified).format('lll') : ''}
                          </h4>
                        </td>
                        <td style={{minWidth:'112px'}} className="last-cell">
                          <ConfirmDropdown
                            id={automation.id + '-split'}
                            text="Actions"
                            menu="Delete"
                            extra={true}
                            title="Delete Automation Confirmation"
                            prompt={`Are you sure you wish to delete '${automation.name}'?`}
                            onConfirm={this.deleteConfirmClicked.bind(this, automation)}
                          >
                            <MenuItem onClick={this.openClicked.bind(this, automation)}>Open</MenuItem>
                            <MenuItem onClick={this.renameClicked.bind(this, automation)}>Rename</MenuItem>
                          </ConfirmDropdown>
                        </td>
                      </EDTableRow>
                    )
                  }
                </EDTable>
              :
                <div className="text-center space-top-sm">
                  <h4>You don&apos;t have any automations yet!</h4>
                </div>
            }
          </EDTableSection>
        </LoaderPanel>
        {this.renderNameModal()}
      </MenuNavbar>
    );
  }
}

export default withLoadSave({
  extend: Automations,
  initial: [],
  get: async () => {
    try {
      return _.sortBy((await axios.get('/api/automations')).data, automation => automation.name.toLowerCase());
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to load automations'), 'error');
      return [];
    }
  },
});
