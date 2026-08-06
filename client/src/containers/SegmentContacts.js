import React, { Component } from "react";
import { Button, FormControl, Table } from "react-bootstrap";
import axios from "axios";
import moment from "moment";
import LoaderPanel from "../components/LoaderPanel";
import LoaderButton from "../components/LoaderButton";
import MenuNavbar from "../components/MenuNavbar";
import TitlePage from "../components/TitlePage";
import { EDTableSection } from "../components/EDDOM";
import notify from "../utils/notify";
import { automationImpersonatedHref } from "./Automation";

function errorMessage(error, fallback) {
  const data = error && error.response && error.response.data;
  if (data) {
    return data.description || data.title || fallback;
  }
  return fallback;
}

export default class SegmentContacts extends Component {
  state = {
    segment: null,
    contacts: [],
    page: 1,
    pageSize: 50,
    total: 0,
    totalPages: 1,
    search: "",
    appliedSearch: "",
    isLoading: false,
  }

  componentDidMount() {
    this.reload();
  }

  segmentId() {
    return this.props.match && this.props.match.params && this.props.match.params.id;
  }

  contactHref(email) {
    return automationImpersonatedHref(
      "/contacts/editcontact?id=" + encodeURIComponent(email),
      this.props.loggedInImpersonate
    );
  }

  reload = async () => {
    const segmentId = this.segmentId();
    this.setState({isLoading: true});
    try {
      const data = (await axios.get("/api/segments/" + segmentId + "/contacts", {
        params: {
          page: this.state.page,
          page_size: this.state.pageSize,
          search: this.state.appliedSearch,
        },
      })).data;
      this.setState({
        segment: data.segment || null,
        contacts: data.contacts || [],
        page: data.page || 1,
        pageSize: data.page_size || 50,
        total: data.total || 0,
        totalPages: data.total_pages || 1,
      });
    } catch (error) {
      notify.show(errorMessage(error, "Unable to load segment contacts"), "error");
    } finally {
      this.setState({isLoading: false});
    }
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

  renderRows() {
    if (!this.state.contacts.length) {
      return (
        <tr>
          <td colSpan="3" className="text-center">No contacts match this segment.</td>
        </tr>
      );
    }
    return this.state.contacts.map(contact => (
      <tr key={contact.contact_id || contact.email}>
        <td>
          <a href={this.contactHref(contact.email)}>{contact.email}</a>
        </td>
        <td>{contact.contact_id}</td>
        <td>{contact.added ? moment(contact.added).format("lll") : ""}</td>
      </tr>
    ));
  }

  render() {
    const segment = this.state.segment || {};
    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="Segment Contacts" />
        <EDTableSection className="white-table-section">
          <LoaderPanel isLoading={this.state.isLoading}>
            <div style={{marginBottom: "14px"}}>
              <h4>{segment.name || ""}</h4>
              <p>{this.state.total.toLocaleString()} matching contacts</p>
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
                  <th>Email</th>
                  <th>Contact ID</th>
                  <th>Added</th>
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
