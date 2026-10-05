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

function formatDate(value) {
  return value ? moment(value).format("l LTS") : "";
}

function flagLabel(value) {
  return value ? <Label bsStyle="success">Enabled</Label> : <Label>Disabled</Label>;
}

function baselineLabel(snapshot) {
  if (!snapshot || !snapshot.exists) {
    return <Label bsStyle="warning">Baseline needed</Label>;
  }
  if (snapshot.stale_claim) {
    return <Label bsStyle="danger">Stale claim</Label>;
  }
  if (snapshot.running) {
    return <Label bsStyle="info">Running</Label>;
  }
  if (snapshot.baseline_complete) {
    return <Label bsStyle="success">Complete</Label>;
  }
  return <Label bsStyle="warning">Incomplete</Label>;
}

function referenceSummary(segment) {
  const references = segment.referenced_by || [];
  const text = _.map(references, ref => {
    const name = ref.automation_name || ref.automation_id || "";
    return name + " / " + (ref.trigger_type || "");
  }).join(", ");
  const extra = (segment.referenced_by_count || 0) - references.length;
  return extra > 0 ? text + " +" + extra + " more" : text;
}

function progressText(snapshot) {
  if (!snapshot || !snapshot.exists) {
    return "";
  }
  const parts = [];
  if (snapshot.hashlimit) {
    parts.push("hashlimit " + snapshot.hashlimit);
  }
  if (snapshot.last_hashval !== null && snapshot.last_hashval !== undefined) {
    parts.push("bucket " + snapshot.last_hashval);
  }
  return parts.join(" / ");
}

export default class AutomationSegmentTriggerStatus extends Component {
  constructor(props) {
    super(props);
    this.state = {
      isLoading: false,
      summary: {},
      segments: [],
      flags: {},
      eventWindowDays: null,
    };
  }

  componentDidMount() {
    this.reload();
  }

  reload = async () => {
    this.setState({isLoading: true});
    try {
      const response = await axios.get("/api/automation-segment-trigger-status");
      this.setState({
        summary: response.data.summary || {},
        segments: response.data.segments || [],
        flags: response.data.flags || {},
        eventWindowDays: response.data.event_window_days,
      });
    } catch (error) {
      notify.show("Unable to load segment trigger status", "error");
    } finally {
      this.setState({isLoading: false});
    }
  }

  renderFlags() {
    const flags = this.state.flags || {};
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            <th>Baseline Scanner</th>
            <th>Diff Scanner</th>
            <th>Trigger Processing</th>
            <th>Customer Processing</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{flagLabel(flags.automation_segment_trigger_baseline_enabled)}</td>
            <td>{flagLabel(flags.automation_segment_trigger_diff_enabled)}</td>
            <td>{flagLabel(flags.automation_triggers_enabled)}</td>
            <td>{flagLabel(flags.customer_automation_processing_enabled)}</td>
          </tr>
        </tbody>
      </Table>
    );
  }

  renderSummary() {
    const summary = this.state.summary || {};
    const recentEvents = summary.recent_events || {};
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            <th>Referenced Segments</th>
            <th>Returned</th>
            <th>Missing Baselines</th>
            <th>Complete</th>
            <th>Incomplete</th>
            <th>Running</th>
            <th>Stale Claims</th>
            <th>Members</th>
            <th>Recent Entered</th>
            <th>Recent Left</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{summary.referenced_segments || 0}</td>
            <td>{summary.returned_segments || 0}</td>
            <td>{summary.missing_snapshots || 0}</td>
            <td>{summary.baseline_complete || 0}</td>
            <td>{summary.baseline_incomplete || 0}</td>
            <td>{summary.running || 0}</td>
            <td>{summary.stale_claims || 0}</td>
            <td>{summary.members || 0}</td>
            <td>{recentEvents.segment_entered || 0}</td>
            <td>{recentEvents.segment_left || 0}</td>
          </tr>
        </tbody>
      </Table>
    );
  }

  renderRows() {
    return _.map(this.state.segments, segment => {
      const snapshot = segment.snapshot || {};
      const recentEvents = segment.recent_events || {};
      return (
        <tr key={segment.segment_id}>
          <td>
            <div>{segment.segment_name || "(missing segment)"}</div>
            <small>{segment.segment_id}</small>
          </td>
          <td>{referenceSummary(segment)}</td>
          <td>{snapshot.status || ""}</td>
          <td>{baselineLabel(snapshot)}</td>
          <td>{progressText(snapshot)}</td>
          <td>{snapshot.member_count || 0}</td>
          <td>{formatDate(snapshot.last_completed_at)}</td>
          <td>{snapshot.claimed_at ? formatDate(snapshot.claimed_at) : ""}</td>
          <td>
            entered {recentEvents.segment_entered || 0}
            <br />
            left {recentEvents.segment_left || 0}
          </td>
          <td>{snapshot.last_error || snapshot.skipped_reason || ""}</td>
        </tr>
      );
    });
  }

  renderSegments() {
    return (
      <Table className="space15 log-table" responsive>
        <thead>
          <tr>
            <th>Segment</th>
            <th>Referenced By</th>
            <th>Snapshot Status</th>
            <th>Baseline</th>
            <th>Progress</th>
            <th>Members</th>
            <th>Last Completed</th>
            <th>Claimed At</th>
            <th>Recent Events</th>
            <th>Last Error</th>
          </tr>
        </thead>
        <tbody>
          {this.state.segments.length ? this.renderRows() : (
            <tr>
              <td colSpan="10" className="text-center">No published segment entry triggers are referenced.</td>
            </tr>
          )}
        </tbody>
      </Table>
    );
  }

  render() {
    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="Segment Trigger Status" />
        <EDTableSection className="white-table-section">
          <LoaderPanel isLoading={this.state.isLoading}>
            <h4>Feature Flags</h4>
            {this.renderFlags()}
            <h4>Account Summary</h4>
            {this.renderSummary()}
            <h4>Referenced Segments</h4>
            {this.renderSegments()}
            {
              this.state.eventWindowDays ?
                <p className="text-muted">Recent event counts cover the last {this.state.eventWindowDays} days.</p>
              :
                null
            }
          </LoaderPanel>
        </EDTableSection>
      </MenuNavbar>
    );
  }
}
