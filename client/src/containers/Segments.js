import React, { Component } from "react";
import { Modal, Button, FormControl, MenuItem, Row, Col } from "react-bootstrap";
import { Link } from "react-router-dom";
import axios from "axios";
import _ from "underscore";
import LoaderPanel from "../components/LoaderPanel";
import { EDCardsContainer, EDCard } from "../components/EDDOM";
import ConfirmDropdown from "../components/ConfirmDropdown";
import TitlePage from "../components/TitlePage";
import withLoadSave from "../components/LoadSave";
import MenuNavbar from "../components/MenuNavbar";
import notify from "../utils/notify";
import SearchControl from "../components/SearchControl";
import fixTag from "../utils/fixtag";
import getvalue from "../utils/getvalue";
import Select2 from "react-select2-wrapper";
import { automationImpersonatedHref } from "./Automation";

import "react-select2-wrapper/css/select2.css";
import './Segments.css';

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

class Segments extends Component {
  state = {
    searchTerm: '',
    filteredSegments: [].concat(this.props.data),
    showTagModal: null,
    untag: false,
    tagging: false,
    tags: [],
    tagName: '',
    bulkSegment: null,
    bulkAutomationId: '',
    bulkEnrolling: false,
    bulkResult: null,
  }

  createClicked = () => {
    this.props.history.push("/segments/edit?id=new");
  }

  tagData() {
    if (!this.props.tags)
      return [];
    return this.props.tags;
  }

  onTagChange = event => {
    setTimeout(() => {
      this.setState({[event.target.id]: getvalue(event)});
    });
  }

  deleteConfirmClicked = async id => {
    await axios.delete('/api/segments/' + id);
    await this.props.reload();
  }

  duplicateClicked = async id => {
    await axios.post('/api/segments/' + id + '/duplicate');
    await this.props.reload();
  }

  tagClicked = id => {
    this.setState({tags: [], showTagModal: id, tagName: _.find(this.props.data, s => s.id === id).name, untag: false});
  }

  untagClicked = id => {
    this.setState({tags: [], showTagModal: id, tagName: _.find(this.props.data, s => s.id === id).name, untag: true});
  }

  tagClose = async ok => {
    var id = this.state.showTagModal;

    this.setState({showTagModal: null});

    if (!ok) {
      return;
    }

    if (this.state.untag) {
      await axios.post('/api/segments/' + id + '/tag', {
        removetags: this.state.tags,
      });
      notify.show("Untag request submitted", "success");
    } else {
      await axios.post('/api/segments/' + id + '/tag', {
        tags: this.state.tags,
      });
      notify.show("Tag request submitted", "success");
    }
  }

  exportClicked = async id => {
    await axios.post('/api/segments/' + id + '/export');

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

  addToAutomationClicked = segment => {
    const options = this.automationOptions();
    this.setState({
      bulkSegment: segment,
      bulkAutomationId: options.length ? options[0].id : '',
      bulkEnrolling: false,
      bulkResult: null,
    });
  }

  viewContactsClicked = segment => {
    const href = automationImpersonatedHref(
      '/segments/' + segment.id + '/contacts',
      this.props.loggedInImpersonate
    );
    window.open(href, '_blank', 'noopener,noreferrer');
  }

  closeBulkEnrolmentModal = () => {
    if (this.state.bulkEnrolling) {
      return;
    }

    this.setState({
      bulkSegment: null,
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
      const response = (await axios.get('/api/automation-segment-enrolments/' + gatherId)).data;
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
    const segment = this.state.bulkSegment;
    const automationId = this.state.bulkAutomationId;
    if (!segment || !automationId) {
      return;
    }

    this.setState({bulkEnrolling: true, bulkResult: null});
    try {
      const response = (await axios.post('/api/automations/' + automationId + '/enrolments/segment', {
        segment_id: segment.id,
      })).data;
      const result = response.result || (response.id ? await this.pollBulkEnrolment(response.id) : null);
      if (!result) {
        return;
      }

      this.setState({bulkResult: result});
      notify.show('Automation enrolment complete: ' + this.bulkEnrolmentResultText(result), result.error_count ? 'warning' : 'success', 15000);
      await this.props.reload();
    } catch (error) {
      notify.show(errorMessage(error, 'Unable to add segment to automation'), 'error');
    } finally {
      if (!this._unmounted) {
        this.setState({bulkEnrolling: false});
      }
    }
  }

  componentDidMount() {
    this._unmounted = false;
    this._interval = setInterval(() => {
      if (_.find(this.props.data, l => !_.isNumber(l.count) && l.count.startsWith("Loading"))) {
        this.props.reload();
      }
    }, 10000);
  }

  componentWillUnmount() {
    this._unmounted = true;
    clearInterval(this._interval);
  }

  componentWillReceiveProps(nextProps) {
    this.setState({filteredSegments: [].concat(nextProps.data)})
  }

  filterSegmentsList = (searchTerm) => {
    this.setState({
      searchTerm: searchTerm,
      filteredSegments: this.props.data.filter(s => s.name.toLowerCase().includes(searchTerm.toLowerCase()))
    })
  }

  num(n) {
    if (!n) n = 0;
    return n.toLocaleString();
  }

  segmentCountText(segment) {
    if (!segment) {
      return '';
    }
    if (_.isNumber(segment.count)) {
      return this.num(segment.count);
    }
    return segment.count || 'Unknown';
  }

  render() {
    const automationOptions = this.automationOptions();
    const bulkSegment = this.state.bulkSegment;
    const bulkResult = this.state.bulkResult;

    return (
      <div className="segments">
        <MenuNavbar {...this.props}>
        <Modal show={!!bulkSegment} onHide={this.closeBulkEnrolmentModal}>
          <Modal.Header closeButton={!this.state.bulkEnrolling}>
            <Modal.Title>Add Segment to Automation</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            {
              bulkSegment &&
              <div>
                <p>
                  <strong>Segment:</strong> {bulkSegment.name}
                </p>
                <p>
                  <strong>Estimated contacts:</strong> {this.segmentCountText(bulkSegment)}
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
        <TitlePage title="Segments" button={
          <Button bsStyle="primary" onClick={this.createClicked}>Create Segment</Button>
        } />
        <LoaderPanel isLoading={this.props.isLoading}>
          {this.props.data.length > 0 ?
            <div>
              <div className="pull-right" style={{paddingTop: '8px', paddingBottom: '8px', paddingRight: '49px'}}>
                <SearchControl onChange={this.filterSegmentsList} value={this.state.searchTerm}/>
              </div>
              <Modal show={this.state.showTagModal !== null}>
                <Modal.Header>
                  <Modal.Title>
                    {
                      this.state.untag ?
                      'Untag Segment'
                      :
                      'Tag Segment'
                    }
                  </Modal.Title>
                </Modal.Header>
                <Modal.Body>
                  <h5>Enter tags to {this.state.untag?'remove':'add'} to all the contacts in "{this.state.tagName}"</h5>
                  <Select2
                    id="tags"
                    multiple
                    value={this.state.tags}
                    data={this.props.tags}
                    onChange={this.onTagChange}
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
                </Modal.Body>
                <Modal.Footer>
                  <Button onClick={this.tagClose.bind(this, true)} bsStyle="primary" disabled={this.state.tagging}>
                    {
                      this.state.untag ? 'Remove' : 'Add'
                    }
                  </Button>
                  <Button onClick={this.tagClose.bind(this, false)}>Cancel</Button>
                </Modal.Footer>
              </Modal>
              <EDCardsContainer>
                {this.state.filteredSegments.map((s, index) => (
                  <EDCard key={s.id} header={
                    <div>
                      <span className="pre-title">SEGMENT</span>
                      <h3 className="segment-name">
                        <Link to={'/segments/edit?id=' + s.id}>
                          {s.name}
                        </Link>
                      </h3>
                    </div>
                  }>
                    <Row>
                      <Col xs={12} className="text-center">
                        {typeof s.count === 'number' ?
                          <div className="circle">
                            <div className="content">
                              <span className="count">{_.isNumber(s.count)?s.count.toLocaleString():s.count}</span>
                              <span className="caption">{
                              _.isNumber(s.count) && s.count === 1 ?
                              'CONTACT' : 'CONTACTS'
                              }</span>
                            </div>
                          </div>
                          :
                          <p className="count-error-message" style={{height: '140px', paddingTop: '45px'}}>
                            {s.count.toLocaleString()}
                          </p>
                        }
                      </Col>
                      <Col xs={12} className="text-center space25">
                        <ConfirmDropdown
                          id={s.id + '-split'}
                          text="Actions"
                          extra={true}
                          menu="Delete"
                          title="Delete Segment Confirmation"
                          prompt={`Are you sure you wish to delete '${s.name}'?`}
                          onConfirm={this.deleteConfirmClicked.bind(this, s.id)}>
                          <MenuItem onClick={() => this.props.history.push('/segments/edit?id=' + s.id)}>Edit</MenuItem>
                          <MenuItem onClick={this.viewContactsClicked.bind(this, s)}>View Contacts</MenuItem>
                          <MenuItem onClick={this.tagClicked.bind(this, s.id)}>Tag</MenuItem>
                          <MenuItem onClick={this.untagClicked.bind(this, s.id)}>Untag</MenuItem>
                          <MenuItem onClick={this.addToAutomationClicked.bind(this, s)}>Add to Automation</MenuItem>
                          {
                          this.props.user && !this.props.user.nodataexport &&
                          <MenuItem onClick={this.exportClicked.bind(this, s.id)}>Export</MenuItem>
                          }
                          <MenuItem onClick={this.duplicateClicked.bind(this, s.id)}>Duplicate</MenuItem>
                        </ConfirmDropdown>
                      </Col>
                    </Row>
                  </EDCard>
                ))}
              </EDCardsContainer>
            </div>
            :
            <div className="text-center space-top-sm">
              <h4>You don&apos;t have any segments!</h4>
              <h5>Segments let you organize contacts using flexible rules.</h5>
            </div>
          }
          </LoaderPanel>
        </MenuNavbar>
      </div>
    );
  }
}

export default withLoadSave({
  extend: Segments,
  initial: [],
  get: async () => _.sortBy((await axios.get('/api/segments')).data, s => s.modified).reverse(),
  extra: {
    tags: async() => (await axios.get('/api/recenttags')).data,
    automations: async () => (await axios.get('/api/automations')).data,
  },
});
