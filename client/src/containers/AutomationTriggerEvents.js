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

function sourceSummary(event) {
  if (event.source_type === "automation" && event.source_automation_id) {
    return event.source_automation_name ?
      event.source_automation_name + " (" + event.source_automation_id + ")" :
      event.source_automation_id;
  }
  return event.source_type || "";
}

function resultSummary(event) {
  const reasons = _.compact(_.map(event.results || [], result => result.reason || result.status));
  const errors = _.compact(_.map(event.errors || [], error => error.reason || error.description || error.status));
  const parts = reasons.concat(errors);
  return parts.length ? parts.join(", ") : "";
}

function eventJson(event) {
  return JSON.stringify(
    {
      results: event.results || [],
      errors: event.errors || [],
      source: {
        type: event.source_type || "",
        automation_id: event.source_automation_id || "",
        automation_name: event.source_automation_name || "",
      },
      correlation_id: event.correlation_id || "",
      depth: event.depth,
      processed_at: event.processed_at || "",
    },
    null,
    2
  );
}

export default class AutomationTriggerEvents extends Component {
  constructor(props) {
    super(props);
    this.state = {
      isLoading: false,
      events: [],
      expandedEventId: null,
    };
  }

  componentDidMount() {
    this.reload();
  }

  reload = async () => {
    this.setState({isLoading: true});
    try {
      const response = await axios.get("/api/automation-trigger-events");
      this.setState({events: response.data.events || []});
    } catch (error) {
      notify.show("Unable to load automation trigger events", "error");
    } finally {
      this.setState({isLoading: false});
    }
  }

  toggleExpanded = event => {
    this.setState({
      expandedEventId: this.state.expandedEventId === event.id ? null : event.id,
    });
  }

  renderEventRows() {
    return _.map(this.state.events, event => {
      const expanded = this.state.expandedEventId === event.id;
      return (
        <tbody key={event.id}>
          <tr>
            <td>
              <Button bsSize="xsmall" onClick={this.toggleExpanded.bind(this, event)}>
                {expanded ? "Hide" : "View"}
              </Button>
            </td>
            <td>{moment(event.timestamp).format("l LTS")}</td>
            <td>{event.event_type || ""}</td>
            <td>{event.contact_email || ""}</td>
            <td>{event.tag || ""}</td>
            <td>{event.status || ""}</td>
            <td>{sourceSummary(event)}</td>
            <td>{event.correlation_id || ""}</td>
            <td>{event.depth}</td>
            <td>{resultSummary(event)}</td>
          </tr>
          {
            expanded &&
            <tr>
              <td colSpan="10">
                <div className="debug-email-log-detail">
                  <h4>Results</h4>
                  <pre className="code-box" style={{whiteSpace: "pre-wrap", wordBreak: "break-word"}}>
                    {eventJson(event)}
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
        <TitlePage title="Automation Trigger Events" />
        <EDTableSection className="white-table-section">
          <LoaderPanel isLoading={this.state.isLoading}>
            {
              this.state.events.length ?
                <Table className="space15 log-table" responsive>
                  <thead>
                    <tr>
                      <th></th>
                      <th>Timestamp</th>
                      <th>Event Type</th>
                      <th>Contact</th>
                      <th>Tag</th>
                      <th>Status</th>
                      <th>Source</th>
                      <th>Correlation ID</th>
                      <th>Depth</th>
                      <th>Result</th>
                    </tr>
                  </thead>
                  {this.renderEventRows()}
                </Table>
              :
                <div className="text-center space-top-sm">
                  <h4>No automation trigger events found.</h4>
                  <h5>Recent tag-added trigger events will appear here when trigger emission or manual trigger events are enabled.</h5>
                </div>
            }
          </LoaderPanel>
        </EDTableSection>
      </MenuNavbar>
    );
  }
}
