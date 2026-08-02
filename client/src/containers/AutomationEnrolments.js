import React, { Component } from "react";
import { Button, FormControl, Table } from "react-bootstrap";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
import LoaderPanel from "../components/LoaderPanel";
import LoaderButton from "../components/LoaderButton";
import MenuNavbar from "../components/MenuNavbar";
import TitlePage from "../components/TitlePage";
import { EDTableSection } from "../components/EDDOM";
import notify from "../utils/notify";
import { automationEnrolmentAction } from "./Automation";

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

function initialView(props) {
  const params = new URLSearchParams(props.location.search);
  return params.get("view") === "active" ? "active" : "all";
}

export default class AutomationEnrolments extends Component {
  constructor(props) {
    super(props);
    this.state = {
      automation: null,
      enrolments: [],
      summary: {},
      page: 1,
      pageSize: 50,
      total: 0,
      totalPages: 1,
      view: initialView(props),
      search: "",
      appliedSearch: "",
      isLoading: false,
      runningEnrolmentId: null,
      reenrollingEnrolmentId: null,
    };
  }

  componentDidMount() {
    this.reload();
  }

  automationId() {
    return this.props.match && this.props.match.params && this.props.match.params.id;
  }

  reload = async () => {
    const automationId = this.automationId();
    this.setState({isLoading: true});
    try {
      const [automationResponse, enrolmentsResponse] = await Promise.all([
        axios.get("/api/automations/" + automationId),
        axios.get("/api/automations/" + automationId + "/enrolments", {
          params: {
            view: this.state.view,
            page: this.state.page,
            page_size: this.state.pageSize,
            search: this.state.appliedSearch,
          },
        }),
      ]);
      const data = enrolmentsResponse.data;
      this.setState({
        automation: automationResponse.data,
        enrolments: data.enrolments || [],
        summary: data.summary || {},
        page: data.page || 1,
        pageSize: data.page_size || 50,
        total: data.total || 0,
        totalPages: data.total_pages || 1,
      });
    } catch (error) {
      notify.show(errorMessage(error, "Unable to load automation enrolments"), "error");
    } finally {
      this.setState({isLoading: false});
    }
  }

  changeView = view => {
    this.setState({view: view, page: 1}, this.reload);
  }

  searchChange = event => {
    this.setState({search: event.target.value});
  }

  submitSearch = event => {
    event.preventDefault();
    this.setState({appliedSearch: this.state.search.trim(), page: 1}, this.reload);
  }

  pageChange = page => {
    this.setState({page: page}, this.reload);
  }

  runNext = async (enrolment, options) => {
    const automationId = this.automationId();
    this.setState({runningEnrolmentId: enrolment.id});
    try {
      const url = "/api/automations/" + automationId + "/enrolments/" + enrolment.id + "/run-next" +
        (options && options.skip_wait ? "?skip_wait=true" : "");
      await axios.post(url, options || {});
      notify.show(options && options.skip_wait ? "Automation wait skipped" : "Automation test step ran", "success");
      await this.reload();
    } catch (error) {
      notify.show(errorMessage(error, "Unable to run next automation step"), "error");
    } finally {
      this.setState({runningEnrolmentId: null});
    }
  }

  reEnrolContact = async enrolment => {
    const automationId = this.automationId();
    this.setState({reenrollingEnrolmentId: enrolment.id});
    try {
      await axios.post("/api/automations/" + automationId + "/enrolments", {email: enrolment.contact_email});
      notify.show("Automation test restarted", "success");
      await this.reload();
    } catch (error) {
      notify.show(errorMessage(error, "Unable to restart automation test"), "error");
    } finally {
      this.setState({reenrollingEnrolmentId: null});
    }
  }

  renderAction(enrolment) {
    const action = automationEnrolmentAction(enrolment, this.state.automation || {});
    if (action.type === "run_next" || action.type === "continue_wait") {
      return (
        <Button
          bsSize="small"
          disabled={this.state.runningEnrolmentId === enrolment.id}
          onClick={this.runNext.bind(this, enrolment)}
        >
          {this.state.runningEnrolmentId === enrolment.id ? "Running..." : action.label}
        </Button>
      );
    }
    if (action.type === "skip_wait") {
      return (
        <div>
          <div style={{whiteSpace: "nowrap", marginBottom: "6px"}}>{action.waitLabel}</div>
          <Button
            bsSize="small"
            disabled={this.state.runningEnrolmentId === enrolment.id}
            onClick={this.runNext.bind(this, enrolment, {skip_wait: true})}
          >
            {this.state.runningEnrolmentId === enrolment.id ? "Moving..." : action.label}
          </Button>
        </div>
      );
    }
    if (action.type === "reenrol") {
      return (
        <Button
          bsSize="small"
          disabled={this.state.reenrollingEnrolmentId === enrolment.id}
          onClick={this.reEnrolContact.bind(this, enrolment)}
        >
          {this.state.reenrollingEnrolmentId === enrolment.id ? "Starting..." : action.label}
        </Button>
      );
    }
    return null;
  }

  renderRows() {
    if (!this.state.enrolments.length) {
      return (
        <tr>
          <td colSpan="6" className="text-center">No contacts match this view.</td>
        </tr>
      );
    }
    return _.map(this.state.enrolments, enrolment => (
      <tr key={enrolment.id}>
        <td>{enrolment.contact_email}</td>
        <td>{enrolment.status || ""}</td>
        <td>{enrolment.current_node_id || ""}</td>
        <td>{enrolment.source || ""}</td>
        <td>{enrolment.created ? moment(enrolment.created).format("lll") : ""}</td>
        <td>{this.renderAction(enrolment)}</td>
      </tr>
    ));
  }

  render() {
    const title = this.state.view === "active" ? "Active Automation Contacts" : "Enrolled Automation Contacts";
    const summary = this.state.summary || {};

    return (
      <MenuNavbar {...this.props}>
        <TitlePage title={title} />
        <EDTableSection className="white-table-section">
          <LoaderPanel isLoading={this.state.isLoading}>
            <div className="flex-items space-between" style={{marginBottom: "14px", gap: "12px"}}>
              <div>
                <h4>{this.state.automation ? this.state.automation.name : ""}</h4>
                <p>Active {summary.active || 0} / Enrolled {summary.enrolled || 0}</p>
              </div>
              <div>
                <Button
                  bsStyle={this.state.view === "active" ? "primary" : "default"}
                  onClick={this.changeView.bind(this, "active")}
                >
                  Active contacts
                </Button>
                {" "}
                <Button
                  bsStyle={this.state.view === "all" ? "primary" : "default"}
                  onClick={this.changeView.bind(this, "all")}
                >
                  All enrolled contacts
                </Button>
              </div>
            </div>
            <form className="form-inline" onSubmit={this.submitSearch} style={{marginBottom: "14px"}}>
              <FormControl
                type="email"
                value={this.state.search}
                onChange={this.searchChange}
                placeholder="Search by email"
                style={{width: "280px"}}
              />
              {" "}
              <LoaderButton
                type="submit"
                bsStyle="default"
                text="Search"
                loadingText="Searching..."
                isLoading={this.state.isLoading}
              />
            </form>
            <p>
              Showing {this.state.total ? (((this.state.page - 1) * this.state.pageSize) + 1) : 0}
              -
              {Math.min(this.state.page * this.state.pageSize, this.state.total)}
              {' '}of {this.state.total} contacts
            </p>
            <Table className="space15 log-table" responsive>
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
              <tbody>{this.renderRows()}</tbody>
            </Table>
            {
              this.state.totalPages > 1 ?
                <div className="flex-items space-between">
                  <Button
                    disabled={this.state.page <= 1}
                    onClick={this.pageChange.bind(this, this.state.page - 1)}
                  >
                    Previous
                  </Button>
                  <span>Page {this.state.page} of {this.state.totalPages}</span>
                  <Button
                    disabled={this.state.page >= this.state.totalPages}
                    onClick={this.pageChange.bind(this, this.state.page + 1)}
                  >
                    Next
                  </Button>
                </div>
              :
                null
            }
          </LoaderPanel>
        </EDTableSection>
      </MenuNavbar>
    );
  }
}
