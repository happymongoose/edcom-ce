import React, { Component } from "react";
import { Button, Table } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
import LoaderPanel from "../components/LoaderPanel";
import MenuNavbar from "../components/MenuNavbar";
import TitlePage from "../components/TitlePage";
import { EDTableSection } from "../components/EDDOM";
import notify from "../utils/notify";

import "./TransactionalLog.css";

function sourceIdsSummary(log) {
  const sourceIds = log.source_ids || {};
  const parts = _.map(sourceIds, (value, key) => key + "=" + value);
  if (parts.length) return parts.join(", ");
  return log.source_id || "";
}

function sourceJson(log) {
  return JSON.stringify(
    {
      source_type: log.source_type || "",
      source_id: log.source_id || "",
      source_ids: log.source_ids || {},
      metadata: log.metadata || {},
      route_id: log.route_id || "",
      backend_id: log.backend_id || "",
    },
    null,
    2
  );
}

export default class DebugEmailLogs extends Component {
  constructor(props) {
    super(props);
    this.state = {
      isLoading: false,
      logs: [],
      expandedLogId: null,
    };
  }

  componentDidMount() {
    this.reload();
  }

  reload = async () => {
    this.setState({isLoading: true});
    try {
      const response = await axios.get('/api/debug-email-logs');
      this.setState({logs: response.data || []});
    } catch (error) {
      notify.show('Unable to load debug email logs', 'error');
    } finally {
      this.setState({isLoading: false});
    }
  }

  toggleExpanded = log => {
    this.setState({
      expandedLogId: this.state.expandedLogId === log.id ? null : log.id,
    });
  }

  renderLogRows() {
    return _.map(this.state.logs, log => {
      const expanded = this.state.expandedLogId === log.id;
      return (
        <tbody key={log.id}>
          <tr>
            <td>
              <Button bsSize="xsmall" onClick={this.toggleExpanded.bind(this, log)}>
                {expanded ? 'Hide' : 'View'}
              </Button>
            </td>
            <td>{moment(log.timestamp).format('l LTS')}</td>
            <td>{log.recipient_email || log.recipient || ''}</td>
            <td>{log.subject || ''}</td>
            <td>{log.source_type || ''}</td>
            <td>{sourceIdsSummary(log)}</td>
          </tr>
          {
            expanded &&
            <tr>
              <td colSpan="6">
                <div className="debug-email-log-detail">
                  <h4>HTML Body</h4>
                  <iframe
                    title={"debug-email-log-preview-" + log.id}
                    sandbox=""
                    srcDoc={log.html || ''}
                    style={{width: '100%', height: '360px', border: '1px solid #ddd', backgroundColor: '#fff'}}
                  />
                  <h4>Metadata</h4>
                  <pre className="code-box" style={{whiteSpace: 'pre-wrap', wordBreak: 'break-word'}}>
                    {sourceJson(log)}
                  </pre>
                </div>
              </td>
            </tr>
          }
        </tbody>
      );
    });
  }

  render() {
    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="Debug Email Logs" />
        <EDTableSection className="white-table-section">
          <LoaderPanel isLoading={this.state.isLoading}>
            {
              this.state.logs.length ?
                <Table className="space15 log-table" responsive>
                  <thead>
                    <tr>
                      <th></th>
                      <th>Timestamp</th>
                      <th>Recipient</th>
                      <th>Subject</th>
                      <th>Source Type</th>
                      <th>Source IDs</th>
                    </tr>
                  </thead>
                  {this.renderLogRows()}
                </Table>
              :
                <div className="text-center space-top-sm">
                  <h4>No debug email logs found.</h4>
                  <h5>Emails sent through a debug_log backend will appear here.</h5>
                </div>
            }
          </LoaderPanel>
        </EDTableSection>
      </MenuNavbar>
    );
  }
}
