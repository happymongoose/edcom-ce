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

export default class ContactsAll extends Component {
  state = {
    contacts: [],
    page: 1,
    pageSize: 50,
    total: 0,
    totalPages: 1,
    search: "",
    appliedSearch: "",
    isLoading: false,
    hasSearched: false,
  }

  componentDidMount() {
    if (!this.props.embedded) this.reload();
  }

  componentWillUnmount() { this.request = (this.request || 0) + 1; }

  componentDidUpdate(previousProps, previousState) {
    if (previousState.hasSearched !== this.state.hasSearched && this.props.onResultsVisibilityChange) {
      this.props.onResultsVisibilityChange(this.state.hasSearched);
    }
  }

  clearSearch = () => {
    this.request = (this.request || 0) + 1;
    this.setState({search: '', appliedSearch: '', contacts: [], page: 1, total: 0, totalPages: 1,
      hasSearched: false, isLoading: false});
  }

  contactHref(email) {
    return automationImpersonatedHref(
      "/contacts/editcontact?id=" + encodeURIComponent(email),
      this.props.loggedInImpersonate
    );
  }

  reload = async () => {
    const request = this.request = (this.request || 0) + 1;
    this.setState({isLoading: true});
    try {
      const data = (await axios.get("/api/contacts", {
        params: {
          page: this.state.page,
          page_size: this.state.pageSize,
          search: this.state.appliedSearch,
          ...(this.props.embedded ? {include_unlisted: true} : {}),
        },
      })).data;
      if (request !== this.request) return;
      this.setState({
        hasSearched: true,
        contacts: data.contacts || [],
        page: data.page || 1,
        pageSize: data.page_size || 50,
        total: data.total || 0,
        totalPages: data.total_pages || 1,
      });
    } catch (error) {
      if (request !== this.request) return;
      this.setState({hasSearched: false});
      notify.show(errorMessage(error, "Unable to load contacts"), "error");
    } finally {
      if (request === this.request) this.setState({isLoading: false});
    }
  }

  searchChange = event => {
    this.setState({search: event.target.value});
  }

  submitSearch = event => {
    event.preventDefault();
    if (this.props.embedded && !this.state.search.trim()) return;
    this.setState({appliedSearch: this.state.search.trim(), page: 1}, this.reload);
  }

  pageChange = page => {
    this.setState({page: page}, this.reload);
  }

  renderRows() {
    if (!this.state.contacts.length) {
      return (
        <tr>
          <td colSpan="4" className="text-center">No contacts match this search.</td>
        </tr>
      );
    }
    return this.state.contacts.map(contact => (
      <tr key={contact.contact_id || contact.email}>
        <td>
          <a href={this.contactHref(contact.email)}>{contact.email}</a>
        </td>
        <td>{contact.name || ''}</td>
        <td>{contact.contact_id}</td>
        <td>{contact.added ? moment(contact.added).format("lll") : ""}</td>
      </tr>
    ));
  }

  renderSearch() {
    return (
        <EDTableSection className="white-table-section">
          <LoaderPanel isLoading={this.state.isLoading}>
            {this.props.embedded && <h4>Find a contact across all lists</h4>}
            <form className="form-inline" onSubmit={this.submitSearch} style={{marginBottom: "14px"}}>
              <FormControl
                type="search"
                aria-label="Search contacts by email or name"
                value={this.state.search}
                onChange={this.searchChange}
                placeholder="Search by email or name"
                style={{width: "280px"}}
              />
              {" "}
              <LoaderButton
                type="submit"
                bsStyle="default"
                text="Search"
                loadingText="Searching..."
                isLoading={this.state.isLoading}
                disabled={this.props.embedded && !this.state.search.trim()}
              />
              {this.props.embedded && this.state.hasSearched && <Button type="button" onClick={this.clearSearch} style={{marginLeft: '8px'}}>Back to lists</Button>}
            </form>
            {this.state.hasSearched && <div>
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
                  <th>Name</th>
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
            </div>}
          </LoaderPanel>
        </EDTableSection>
    );
  }

  render() {
    if (this.props.embedded) return this.renderSearch();
    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="All Contacts" />
        {this.renderSearch()}
      </MenuNavbar>
    );
  }
}
