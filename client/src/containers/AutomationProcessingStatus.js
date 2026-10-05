import React, { Component } from "react";
import { Label, Table } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
import LoaderPanel from "../components/LoaderPanel";
import MenuNavbar from "../components/MenuNavbar";
import TitlePage from "../components/TitlePage";
import { EDTableSection } from "../components/EDDOM";
import notify from "../utils/notify";

import "./TransactionalLog.css";

const STATUSES = [
  "ready",
  "waiting",
  "held",
  "paused_ready",
  "paused_waiting",
  "running",
  "stale_running",
  "failed",
  "completed",
  "exited",
  "cancelled",
  "total",
];

function statusLabel(status) {
  return status.replace(/_/g, " ");
}

function countFor(counts, status) {
  return (counts && counts[status]) || 0;
}

function formatDate(value) {
  return value ? moment(value).format("l LTS") : "";
}

function flagLabel(value) {
  return value ? <Label bsStyle="success">Enabled</Label> : <Label>Disabled</Label>;
}

export default class AutomationProcessingStatus extends Component {
  constructor(props) {
    super(props);
    this.state = {
      isLoading: false,
      summary: {},
      automations: [],
      recentFailures: [],
      staleRunning: [],
      flags: {},
    };
  }

  componentDidMount() {
    this.reload();
  }

  reload = async () => {
    this.setState({isLoading: true});
    try {
      const response = await axios.get("/api/automation-processing-status");
      this.setState({
        summary: response.data.summary || {},
        automations: response.data.automations || [],
        recentFailures: response.data.recent_failures || [],
        staleRunning: response.data.stale_running || [],
        flags: response.data.flags || {},
      });
    } catch (error) {
      notify.show("Unable to load automation processing status", "error");
    } finally {
      this.setState({isLoading: false});
    }
  }

  renderSummary() {
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            {_.map(STATUSES, status => <th key={status}>{statusLabel(status)}</th>)}
          </tr>
        </thead>
        <tbody>
          <tr>
            {_.map(STATUSES, status => <td key={status}>{countFor(this.state.summary, status)}</td>)}
          </tr>
        </tbody>
      </Table>
    );
  }

  renderFlags() {
    const flags = this.state.flags || {};
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            <th>Automation Processing</th>
            <th>Trigger Processing</th>
            <th>Trigger Emission</th>
            <th>Manual Trigger Events (debug)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{flagLabel(flags.automation_processing_enabled)}</td>
            <td>{flagLabel(flags.automation_triggers_enabled)}</td>
            <td>{flagLabel(flags.automation_trigger_emission_enabled)}</td>
            <td>{flagLabel(flags.automation_trigger_manual_events_enabled_debug)}</td>
          </tr>
        </tbody>
      </Table>
    );
  }

  renderAutomationRows() {
    return _.map(this.state.automations, automation => (
      <tr key={automation.automation_id}>
        <td>{automation.automation_name || ""}</td>
        <td>{automation.automation_status || ""}</td>
        <td>{automation.published_revision || ""}</td>
        {_.map(STATUSES, status => (
          <td key={status}>{countFor(automation.counts, status)}</td>
        ))}
      </tr>
    ));
  }

  renderAutomations() {
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            <th>Automation</th>
            <th>Status</th>
            <th>Revision</th>
            {_.map(STATUSES, status => <th key={status}>{statusLabel(status)}</th>)}
          </tr>
        </thead>
        <tbody>
          {this.state.automations.length ? this.renderAutomationRows() : (
            <tr>
              <td colSpan={STATUSES.length + 3} className="text-center">No automation enrolments found.</td>
            </tr>
          )}
        </tbody>
      </Table>
    );
  }

  renderFailures() {
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            <th>Failed At</th>
            <th>Automation</th>
            <th>Contact</th>
            <th>Current Node</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {this.state.recentFailures.length ? _.map(this.state.recentFailures, failure => (
            <tr key={failure.enrolment_id}>
              <td>{formatDate(failure.failed_at)}</td>
              <td>{failure.automation_name || failure.automation_id}</td>
              <td>{failure.contact_email || ""}</td>
              <td>{failure.current_node_id || ""}</td>
              <td>{failure.error || ""}</td>
            </tr>
          )) : (
            <tr>
              <td colSpan="5" className="text-center">No recent failed enrolments.</td>
            </tr>
          )}
        </tbody>
      </Table>
    );
  }

  renderStaleRunning() {
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            <th>Claimed At</th>
            <th>Automation</th>
            <th>Contact</th>
            <th>Claimed Node</th>
            <th>Running Status</th>
            <th>Revision</th>
          </tr>
        </thead>
        <tbody>
          {this.state.staleRunning.length ? _.map(this.state.staleRunning, item => (
            <tr key={item.enrolment_id}>
              <td>{formatDate(item.claimed_at)}</td>
              <td>{item.automation_name || item.automation_id}</td>
              <td>{item.contact_email || ""}</td>
              <td>{item.claimed_node_id || ""}</td>
              <td>{item.running_status || ""}</td>
              <td>{item.claimed_published_revision || ""}</td>
            </tr>
          )) : (
            <tr>
              <td colSpan="6" className="text-center">No stale running claims.</td>
            </tr>
          )}
        </tbody>
      </Table>
    );
  }

  render() {
    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="Automation Processing Status" />
        <EDTableSection className="white-table-section">
          <LoaderPanel isLoading={this.state.isLoading}>
            <h4>Feature Flags</h4>
            {this.renderFlags()}
            <h4>Account Summary</h4>
            {this.renderSummary()}
            <h4>By Automation</h4>
            {this.renderAutomations()}
            <h4>Recent Failures</h4>
            {this.renderFailures()}
            <h4>Stale Running Claims</h4>
            {this.renderStaleRunning()}
          </LoaderPanel>
        </EDTableSection>
      </MenuNavbar>
    );
  }
}
