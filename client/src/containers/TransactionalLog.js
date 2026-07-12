import React, { Component } from "react";
import { Nav, NavItem, Table, Button, FormControl } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import LoaderPanel from "../components/LoaderPanel";
import TitlePage from "../components/TitlePage";
import MenuNavbar from "../components/MenuNavbar";
import { EDTableSection, EDTabs } from "../components/EDDOM";
import moment from "moment";
import notify from "../utils/notify";
import { serializeDatetimeFilterValue } from "../utils/transactionalLog";

import "./TransactionalLog.css";

export default class TransactionalLog extends Component {
  constructor(props) {
    super(props);
    this.reloadRequest = 0;
    this.state = {
      isLoading: false,
      data: null,
      page: 1,
      search: "",
      start: "",
      end: ""
    };
  }

  async reload() {
    const requestId = ++this.reloadRequest;
    this.setState({isLoading: true});
    try {
      var data = await axios.get('/api/transactional/log', {
        params: {
          page: this.state.page,
          search: this.state.search,
          start: serializeDatetimeFilterValue(this.state.start),
          end: serializeDatetimeFilterValue(this.state.end)
        }
      });
      if (requestId === this.reloadRequest) {
        this.setState({data: data.data});
      }
    } catch (error) {
      if (requestId === this.reloadRequest) {
        notify.show('Unable to load the transactional log', 'error');
      }
    } finally {
      if (requestId === this.reloadRequest) {
        this.setState({isLoading: false});
      }
    }
  }

  previous = () => {
    if (this.state.page <= 1) return;
    this.setState({page: this.state.page - 1}, () => this.reload());
  }

  next = () => {
    if (this.state.page >= this.maxPage()) return;
    this.setState({page: this.state.page + 1}, () => this.reload());
  }

  componentDidMount() {
    this.reload();
  }

  updatePage = e => {
    const num = parseInt(e.target.value, 10);
    if (isNaN(num)) return;
    if (num < 1) return;
    if (num > this.maxPage()) return;
    this.setState({page: num}, () => this.reload());
  }

  updateSearch = e => {
    this.setState({search: e.target.value, page: 1}, () => this.reload());
  }

  updateStart = e => {
    this.setState({start: e.target.value, page: 1}, () => this.reload());
  }

  updateEnd = e => {
    this.setState({end: e.target.value, page: 1}, () => this.reload());
  }

  clearFilters = () => {
    this.setState({search: '', start: '', end: '', page: 1}, () => this.reload());
  }

  switchView = url => {
    this.props.history.push(url);
  }

  rowClass = event => {
    if (!event || event === 'Delivery') {
      return "table-success";
    } else if (event === 'Injection') {
      return "table-info";
    } else {
      return "table-danger";
    }
  }

  displayStatus = l => {
    if (l.error) return l.error;
    if (l.event === 'Injection' && l.status === 'Accepted') return 'Queued';
    return l.status || 'OK';
  }

  exportClicked = async () => {
    await axios.post('/api/transactional/log/export');

    notify.show('Download your export file from the Data Exports page', "success");
  }

  maxPage = () => {
    if (!this.state.data || !this.state.data.total) return 1;
    return Math.ceil(this.state.data.total / this.state.data.page_size);
  }

  render() {
    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="Transactional Log"
          button={
            <Button bsStyle="primary" onClick={this.exportClicked}>Export to CSV</Button>
          }
          tabs={
            <EDTabs>
              <Nav className="nav-tabs space15" activeKey="3">
                <NavItem eventKey="1" onClick={this.switchView.bind(null, '/transactional')}>Dashboard</NavItem>
                <NavItem eventKey="2" onClick={this.switchView.bind(null, '/transactional/templates')}>Templates</NavItem>
                <NavItem eventKey="3" disabled>Log</NavItem>
                <NavItem eventKey="4" onClick={this.switchView.bind(null, '/transactional/settings')}>Settings</NavItem>
              </Nav>
            </EDTabs>
          }
        />
        <EDTableSection className="white-table-section">
            <div className="log-toolbar">
              <div className="log-search-field">
                <label className="control-label">Search</label>
                <FormControl
                  type="text"
                  value={this.state.search}
                  placeholder="Search by to, from, or subject"
                  onChange={this.updateSearch}
                />
              </div>
              <div className="log-date-field">
                <label className="control-label">From</label>
                <FormControl
                  type="datetime-local"
                  value={this.state.start}
                  onChange={this.updateStart}
                  placeholder="YYYY-MM-DD HH:MM"
                />
              </div>
              <div className="log-date-field">
                <label className="control-label">To</label>
                <FormControl
                  type="datetime-local"
                  value={this.state.end}
                  onChange={this.updateEnd}
                  placeholder="YYYY-MM-DD HH:MM"
                />
              </div>
              <Button className="log-clear-button" onClick={this.clearFilters} disabled={!this.state.search && !this.state.start && !this.state.end}>Clear</Button>
            </div>
          <LoaderPanel isLoading={this.state.isLoading}>
          {
            (this.state.data && this.state.data.records && this.state.data.records.length) ?
              <div>
                <Table className="space15 log-table" responsive>
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>From</th>
                      <th>To</th>
                      <th>Subject</th>
                      <th>Tag</th>
                      <th>Date</th>
                      <th>Status</th>
                      <th className="text-center">Opened</th>
                      <th className="text-center">Clicked</th>
                      <th className="text-center">Unsubscribed</th>
                      <th className="text-center">Complained</th>
                    </tr>
                  </thead>
                  <tbody>
                    {
                    _.map(this.state.data.records, l =>
                        <tr key={l.id} className={this.rowClass(l.event)}>
                          <td>
                            {l.event || 'Delivery'}
                          </td>
                          <td>
                            {l.fromname ? l.fromname + ' <' + l.fromemail + '>' : l.fromemail}
                          </td>
                          <td>
                            {l.toname ? l.toname + ' <' + l.to + '>' : l.to}
                          </td>
                          <td>
                            {l.subject}
                          </td>
                          <td>
                            {l.tag || 'untagged'}
                          </td>
                          <td>
                            {moment(l.ts).format('l LTS')}
                          </td>
                          <td>
                            {this.displayStatus(l)}
                          </td>
                          <td className="text-center">
                            {l.open ? <i className="fa fa-check-square-o" /> : ''}
                          </td>
                          <td className="text-center">
                            {l.click ? <i className="fa fa-check-square-o" /> : ''}
                          </td>
                          <td className="text-center">
                            {l.unsub ? <i className="fa fa-check-square-o" /> : ''}
                          </td>
                          <td className="text-center">
                            {l.complaint ? <i className="fa fa-check-square-o" /> : ''}
                          </td>
                        </tr>
                    )
                  }
                  </tbody>
                </Table>
                {
                  this.maxPage() > 1 &&
                  <div className="form-inline space-bottom" style={{display: 'flex', gap: '16px', alignItems: 'center'}}>
                    <Button style={{width: '120px'}} onClick={this.previous} disabled={this.state.page <= 1}>Previous</Button>
                    <span>
                      Page{' '}
                      <FormControl
                        className="table-page-input"
                        type="number"
                        min={1}
                        max={this.maxPage()}
                        step="1"
                        value={this.state.page}
                        onChange={this.updatePage}
                        style={{width: '75px', textAlign: 'right'}}
                      />
                      {' '}of {this.maxPage()}
                    </span>
                    <Button style={{width: '120px'}} onClick={this.next} disabled={this.state.page >= this.maxPage()}>Next</Button>
                  </div>
                }
              </div>
              :
              <div className="text-center space-top-sm">
                <h4>{this.state.search.trim() || this.state.start || this.state.end ? 'No transactional messages matched your filters.' : 'No transactional messages found!'}</h4>
                <h5>{this.state.search.trim() || this.state.start || this.state.end ? 'Try a different email address, subject, or date/time range.' : 'When you send them, your most recent transactional messages will appear here.'}</h5>
              </div>
          }
          </LoaderPanel>
        </EDTableSection>
      </MenuNavbar>
    );
  }
}
