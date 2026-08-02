import React, { Component } from "react";
import { Link } from "react-router-dom";
import { Button, Modal, Nav, Navbar, NavItem, NavDropdown} from "react-bootstrap";
import RouteNavItem from "./RouteNavItem";
import LoaderIcon from "./LoaderIcon";
import axios from "axios";
import _ from "underscore";
import moment from "moment";
import { FormControlLabel } from "../components/FormControls";

import './MenuNavbar.css';

/* eslint import/no-webpack-loader-syntax: off */
import BackendNavigationCustomersIcon from '-!svg-react-loader!../svg/menu-icons/backend-navigation-customers.svg';
import BackendNavigationMTAIcon from '-!svg-react-loader!../svg/menu-icons/backend-navigation-mta.svg';
import BackendNavigationAPIIcon from '-!svg-react-loader!../svg/menu-icons/backend-navigation-api.svg';
import BackendNavigationReportsIcon from '-!svg-react-loader!../svg/menu-icons/backend-navigation-reports.svg';
import BackendDropdownMenuCustomerAccountsIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-customer-accounts.svg';
import BackendDropdownMenuPostalRoutesIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-postal-routes.svg';
import BackendDropdownMenuSignupPageIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-signup-page.svg';
import BackendDropdownMenuServersIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-servers.svg';
import BackendDropdownMenuDeliveryPoliciesIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-delivery-policies.svg';
import BackendDropdownMenuWarmupsIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-warmups.svg';
import BackendDropdownMenuCustomerBroadcastsIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-customer-broadcasts.svg';
import BackendDropdownMenuIpDeliveryIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-ip-reports.svg';
import BackendDropdownMenuDashboardIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-dashboard.svg';
import BackendDropdownMenuPostmasterActivityIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-postmaster-activity.svg';
import FrontendNavigationMessagesIcon from '-!svg-react-loader!../svg/menu-icons/frontend-navigation-messages.svg';
import FrontendNavigationContactsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-navigation-contacts.svg';
import FrontendNavigationCCIcon from '-!svg-react-loader!../svg/menu-icons/frontend-navigation-cc.svg';
import FrontendNavigationIntegrateIcon from '-!svg-react-loader!../svg/menu-icons/frontend-navigation-integrate.svg';
import FrontendDropdownMenuBroadcastsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-broadcasts.svg';
import FrontendDropdownMenuFunnelsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-funnels.svg';
import FrontendDropdownMenuAutomationsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-automations.svg';
import FrontendDropdownMenuTransactionalIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-transactional.svg';
import FrontendDropdownMenuContactsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-contacts.svg';
import FrontendDropdownMenuSegmentsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-segments.svg';
import FrontendDropdownMenuSuppressionIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-suppression.svg';
import FrontendDropdownMenuFormsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-forms.svg';
import FrontendDropdownMenuAPISMTPIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-apismtp.svg';
import FrontendDropdownMenuWebhooksIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-webhooks.svg';
import FrontendDropdownMenuIntegrationsIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-integrations.svg';
import FrontendDropdownMenuPabblyIcon from '-!svg-react-loader!../svg/menu-icons/frontend-dropdown-menu-pabbly.svg';
import UserDropdownMenuThrottlesIcon from '-!svg-react-loader!../svg/menu-icons/user-dropdown-menu-throttles.svg';
import UserDropdownMenuDataExportsIcon from '-!svg-react-loader!../svg/menu-icons/user-dropdown-menu-data-exports.svg';
import UserDropdownMenuPasswordIcon from '-!svg-react-loader!../svg/menu-icons/user-dropdown-menu-password.svg';
import UserDropdownMenuLogOffIcon from '-!svg-react-loader!../svg/menu-icons/user-dropdown-menu-log-off.svg';
import BackendDropdownMenuMailgunIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-mailgun.svg';
import BackendDropdownMenuSESIcon from '-!svg-react-loader!../svg/menu-icons/backend-dropdown-menu-ses.svg';
import { canViewAutomationDiagnostics } from "../utils/automationDiagnostics";

export default class MenuNavbar extends Component {
  constructor(props) {
    super(props);

    this._userInterval = null;

    this.state = {
      alertDismissed: false,
      alertDismissed2: false,
      userMenuOpen: false,
      showModal: false,
      description: '',
      contacts: '',
      volume: '',
      isSaving: false,
    };
  }

  dismiss = () => {
    this.setState({alertDismissed: true});

    axios.post('/api/reset/limitalert');
  }

  dismiss2 = () => {
    this.setState({alertDismissed2: true});

    axios.post('/api/reset/probationalert');
  }

  upgrade = e => {
    //this.props.history.push('/upgrade');
    e.preventDefault();
  }

  userMenuToggle = isOpen => {
    if (isOpen) {
      if (this._userInterval === null && this.props.user) {
        this.props.reloadUser();
        this._userInterval = setInterval(this.props.reloadUser, 1000*30);
      }
    } else {
      if (this._userInterval !== null) {
        clearInterval(this._userInterval);
        this._userInterval = null;
      }
    }
    this.setState({userMenuOpen: isOpen});
  }

  componentWillUnmount() {
    if (this._userInterval !== null) {
      clearInterval(this._userInterval);
      this._userInterval = null;
    }
  }

  limitHit() {
    var u = this.props.user;
    if (u.limit !== null && !_.isUndefined(u.limit) && u.sent !== null && !_.isUndefined(u.sent)) {
      return u.sent >= u.limit;
    }
    return false;
  }

  daysLeft() {
    if (!this.props.user || !this.props.user.trialend) {
      return null;
    }

    var m = moment(this.props.user.trialend);
    var d = m.diff(moment());
    var days = m.diff(moment(), 'days');

    if (d < 0) {
      return 0;
    }

    return days + 1;
  }

  showSubmit = e => {
    e.preventDefault();

    var p = {
      showModal: true,
    };

    this.setState(p);
  }

  modalChange = e => {
    this.setState({[e.target.id]: e.target.value});
  }

  modalConfirm = async yes => {
    if (!yes) {
      this.setState({showModal: false});
      return;
    }

    try {
      await axios.patch('/api/moderationinfo', {info:
        'Description:\n\n' + this.state.description + '\n\n' +
        'No. of Contacts:\n\n' + this.state.contacts + '\n\n' +
        'No. of Broadcasts:\n\n' + this.state.volume
      });

      await this.props.reloadUser();
    } finally {
      this.setState({showModal: false});
    }
  }

  render() {
    var props = this.props;

    var daysleft = this.daysLeft();

    return (
      <div>
        <Modal show={this.state.showModal}>
          <Modal.Header>
            <Modal.Title>Enable Account</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <p>We need a little bit of information about your blog or business before you can send emails. Just fill out the boxes below and we'll review it today!</p>
            <p>Until then, you can still use everything in your account, but you can only send test messages. You can still create broadcasts and funnels as well as import subscribers.</p>
            <FormControlLabel
              id="description"
              label="Describe your business or blog topic in a sentence or two:"
              componentClass="textarea"
              obj={this.state}
              onChange={this.modalChange}
              space
              rows={3}
            />
            <FormControlLabel
              id="contacts"
              label="How many contacts do you have?"
              obj={this.state}
              onChange={this.modalChange}
              space
              autoComplete="off"
            />
            <FormControlLabel
              id="volume"
              label="How many broadcasts will you send per week?"
              obj={this.state}
              onChange={this.modalChange}
              space
              autoComplete="off"
            />
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={this.modalConfirm.bind(this, true)} bsStyle="primary" disabled={!this.state.description || !this.state.contacts || !this.state.volume || this.state.isSaving}>
              Submit
            </Button>
            <Button onClick={this.modalConfirm.bind(this, false)}>Cancel</Button>
          </Modal.Footer>
        </Modal>
        {
          props.user && !props.user.admin && !props.user.paid && props.user.inreview && !props.user.hasmoderation &&
          <div className="alert alert-danger alert-server" role="alert">
            <strong>Review Needed</strong> Your account can only send test messages until you are approved for a free trial. Click <a href="#s" onClick={this.showSubmit}>here</a> to get approval.
          </div>
        }
        {
          props.user && !props.user.admin && !props.user.paid && !props.user.inreview && props.user.trialend && moment(props.user.trialend).isBefore(moment()) &&
          <div className="alert alert-warning alert-server" role="alert">
            <strong>Trial Ended</strong> Your free trial has expired. Click <Link to="/openticket">here</Link> to ask us a question or leave a comment.
          </div>
        }
        {
          props.loggedInImpersonate &&
          <div className="alert alert-info alert-server" role="alert">
            This is the customer data view. <strong>Close this browser tab to exit.</strong>
          </div>
        }
        <header className={`menu-navbar ${props.loggedInUID ? 'logged-in' : 'not-logged-in'}`}>
          {!props.loggedInUID ?
            <div className="login-navbar">
              <Navbar fluid>
                <Navbar.Header>
                  <Navbar.Brand>
                    {
                       !this.props.noLogin ?
                        <Link to="/login">
                          <img className="logoimg" src={props.image || '/img/logo.png'} alt="logo" />
                        </Link>
                       :
                        <a href="#logo" onClick={e => e.preventDefault()} style={{pointerEvents: 'none'}}>
                          <img className="logoimg" src={props.image || '/img/logo.png'} alt="logo" />
                        </a>
                    }
                  </Navbar.Brand>
                </Navbar.Header>
                <Nav className="pull-right login-header-link">
                  { !this.props.noLogin &&
                  <RouteNavItem href="/login">Login</RouteNavItem>
                  }
                </Nav>
              </Navbar>
            </div>
            :
            <Navbar fluid className={props.isAdmin ? 'backend' : undefined}>
              <Navbar.Header>
                <Navbar.Brand>
                  <Link to="/">
                    {
                      props.isAdmin ?
                        <img className="logoimg" src="/img/logo.png" alt="logo" />
                      :
                        (props.user && props.user.frontend &&
                        <img className="logoimg" src={props.user.frontend.image || '/img/logo.png'} alt="logo" />)
                    }
                  </Link>
                </Navbar.Brand>
                <Navbar.Toggle />
              </Navbar.Header>
              <Navbar.Collapse>
                {props.user ?
                  props.user.admin && !props.loggedInImpersonate ?
                    <Nav className="nav-left">
                      <NavDropdown id="customers" title={<span>
                        <BackendNavigationCustomersIcon className="nav-icon tie-guy"/>
                        Customers
                      </span>}>
                        <RouteNavItem href="/customers">
                          <BackendDropdownMenuCustomerAccountsIcon className="dropdown-icon three-people"/>
                          Customer Accounts
                        </RouteNavItem>
                        <RouteNavItem href="/routes">
                          <BackendDropdownMenuPostalRoutesIcon className="dropdown-icon route-signs"/>
                          Postal Routes
                        </RouteNavItem>
                        <RouteNavItem href="/signupsettings">
                          <BackendDropdownMenuSignupPageIcon className="dropdown-icon signup-page"/>
                          Sign-up Page
                        </RouteNavItem>
                      </NavDropdown>
                      <NavDropdown id="hosted" title={<span>
                        <BackendNavigationMTAIcon className="nav-icon strategy"/>
                        MTA
                      </span>}>
                        <RouteNavItem href="/servers">
                          <BackendDropdownMenuServersIcon className="dropdown-icon server-stack"/>
                          Velocity MTA Servers
                        </RouteNavItem>
                        <RouteNavItem href="/policies">
                          <BackendDropdownMenuDeliveryPoliciesIcon className="dropdown-icon brain-guy"/>
                          MTA Delivery Policies
                        </RouteNavItem>
                        <RouteNavItem href="/warmups">
                          <BackendDropdownMenuWarmupsIcon className="dropdown-icon thermometer"/>
                          IP Warmups
                        </RouteNavItem>
                      </NavDropdown>
                      <NavDropdown id="api" title={<span>
                        <BackendNavigationAPIIcon className="nav-icon plug"/>
                        Connect
                      </span>}>
                      <RouteNavItem href="/smtprelays">
                          <img alt="" className="dropdown-icon smtprelay" src="/img/smtprelay.png"/>
                          SMTP Relay
                        </RouteNavItem>
                        <RouteNavItem href="/mailgun">
                          <BackendDropdownMenuMailgunIcon className="dropdown-icon mailgun"/>
                          Mailgun API
                        </RouteNavItem>
                        <RouteNavItem href="/ses">
                          <BackendDropdownMenuSESIcon className="dropdown-icon ses"/>
                          Amazon SES API
                        </RouteNavItem>
                        <RouteNavItem href="/sparkpost">
                          <img alt="" className="dropdown-icon sparkpost" src="/img/sparkpost.png"/>
                          SparkPost API
                        </RouteNavItem>
                        <RouteNavItem href="/easylink">
                          <img alt="" className="dropdown-icon easylink" src="/img/easylink.png"/>
                          Easylink API
                        </RouteNavItem>
                      </NavDropdown>
                      <NavDropdown id="admin-reports" title={<span>
                        <BackendNavigationReportsIcon className="nav-icon reports-graph"/>
                        Reports
                      </span>}>
                        <RouteNavItem href="/custbcs">
                          <BackendDropdownMenuCustomerBroadcastsIcon className="dropdown-icon"/>
                          Customer Broadcasts
                        </RouteNavItem>
                        <RouteNavItem href="/emaildelivery">
                          <BackendDropdownMenuDashboardIcon className="dropdown-icon"/>
                          Email Delivery
                        </RouteNavItem>
                        <RouteNavItem href="/ipdelivery">
                          <BackendDropdownMenuIpDeliveryIcon className="dropdown-icon"/>
                          IP Delivery
                        </RouteNavItem>
                        <RouteNavItem href="/adminlog">
                          <BackendDropdownMenuPostmasterActivityIcon className="dropdown-icon"/>
                          Postmaster Activity
                        </RouteNavItem>
                      </NavDropdown>
                    </Nav>
                    :
                    <Nav className="nav-left">
                      <NavDropdown id="broadcasts" noCaret title={<span>
                        <FrontendNavigationMessagesIcon className="nav-icon envelope"/>
                        Messages
                      </span>}>
                        <RouteNavItem href="/broadcasts">
                          <FrontendDropdownMenuBroadcastsIcon className="dropdown-icon"/>
                          Broadcasts
                        </RouteNavItem>
                        <RouteNavItem href="/funnels">
                          <FrontendDropdownMenuFunnelsIcon className="dropdown-icon"/>
                          Funnels
                        </RouteNavItem>
                        <RouteNavItem href="/automations">
                          <FrontendDropdownMenuAutomationsIcon className="dropdown-icon"/>
                          Automations
                        </RouteNavItem>
                        {
                          canViewAutomationDiagnostics(this.props) &&
                          <RouteNavItem href="/debug-email-logs">
                            <FrontendDropdownMenuTransactionalIcon className="dropdown-icon"/>
                            Debug Email Logs
                          </RouteNavItem>
                        }
                        {
                          canViewAutomationDiagnostics(this.props) &&
                          <RouteNavItem href="/automation-trigger-events">
                            <FrontendDropdownMenuAutomationsIcon className="dropdown-icon"/>
                            Automation Trigger Events
                          </RouteNavItem>
                        }
                        {
                          canViewAutomationDiagnostics(this.props) &&
                          <RouteNavItem href="/automation-processing-status">
                            <FrontendDropdownMenuAutomationsIcon className="dropdown-icon"/>
                            Automation Processing Status
                          </RouteNavItem>
                        }
                        <RouteNavItem href="/transactional">
                          <FrontendDropdownMenuTransactionalIcon className="dropdown-icon"/>
                          Transactional
                        </RouteNavItem>
                        <RouteNavItem href="/domainthrottles">
                          <UserDropdownMenuThrottlesIcon className="dropdown-icon"/>
                          Throttles
                        </RouteNavItem>
                      </NavDropdown>
                      <NavDropdown id="contacts" noCaret title={<span>
                        <FrontendNavigationContactsIcon className="nav-icon contacts-book"/>
                        Contacts
                      </span>}>
                        <RouteNavItem href="/contacts">
                          <FrontendDropdownMenuContactsIcon className="dropdown-icon id-card"/>
                          Contact Lists
                        </RouteNavItem>
                        <RouteNavItem href="/segments">
                          <FrontendDropdownMenuSegmentsIcon className="dropdown-icon"/>
                          Segments
                        </RouteNavItem>
                        <RouteNavItem href="/suppression">
                          <FrontendDropdownMenuSuppressionIcon className="dropdown-icon not-allowed-guy"/>
                          Suppression
                        </RouteNavItem>
                        <RouteNavItem href="/forms">
                          <FrontendDropdownMenuFormsIcon className="dropdown-icon"/>
                          Forms
                        </RouteNavItem>
                      </NavDropdown>
                      <NavDropdown id="integrate" noCaret title={<span>
                        <FrontendNavigationIntegrateIcon className="nav-icon"/>
                        Integrate
                      </span>}>
                        <RouteNavItem href="/connect">
                          <FrontendDropdownMenuAPISMTPIcon className="dropdown-icon"/>
                          API &amp; SMTP
                        </RouteNavItem>
                        <RouteNavItem href="/customdomains">
                          <FrontendDropdownMenuAPISMTPIcon className="dropdown-icon"/>
                          Custom Domains
                        </RouteNavItem>
                        <RouteNavItem href="/webhooks">
                          <FrontendDropdownMenuWebhooksIcon className="dropdown-icon"/>
                          Webhooks
                        </RouteNavItem>
                        <RouteNavItem href="/zapier">
                          <FrontendDropdownMenuIntegrationsIcon className="dropdown-icon"/>
                          Zapier
                        </RouteNavItem>
                        <RouteNavItem href="/pabbly">
                          <FrontendDropdownMenuPabblyIcon className="dropdown-icon"/>
                          Pabbly
                        </RouteNavItem>
                      </NavDropdown>
                    </Nav>
                  :
                  <Nav className="nav-left">
                    <NavItem disabled>
                      <LoaderIcon/>
                    </NavItem>
                  </Nav>
                }
                <Nav pullRight>
                  <NavDropdown
                    id="useractions"
                    open={this.state.userMenuOpen}
                    onToggle={this.userMenuToggle}
                    title={props.user ?
                      <div className="user-container">
                        <span className="user-photo">
                          {props.user.photo ?
                            <img src={props.user.photo} alt={props.user.fullname} />
                            :
                            <span className="user-initials">{props.user.fullname.trim()[0]}</span>
                          }
                        </span>
                        <div>
                          <span className="user-fullname">{props.user.fullname}</span>
                          <span className="user-companyname">{props.user.companyname}</span>
                        </div>
                        <i className="fa fa-caret-down"></i>
                      </div>
                      :
                      <LoaderIcon/>}>
                    {
                      props.user && !props.user.nodataexport && (!props.user.admin || props.loggedInImpersonate) &&
                        <RouteNavItem href="/exports">
                          <UserDropdownMenuDataExportsIcon className="dropdown-icon"/>
                          Data Exports
                        </RouteNavItem>
                    }
                    <RouteNavItem href="/changepass">
                      <UserDropdownMenuPasswordIcon className="dropdown-icon"/>
                      Change Password...
                    </RouteNavItem>
                    <NavItem onClick={props.doLogout}>
                      <UserDropdownMenuLogOffIcon className="dropdown-icon"/>
                      Logout
                    </NavItem>
                  </NavDropdown>
                </Nav>
                {
                  props.user && !props.user.admin && !props.user.paid && !props.noUpgrade && !props.user.trialend && props.user.inreview && props.user.hasmoderation &&
                    <Nav pullRight>
                      <NavItem className="billing-nav no-link">
                        IN REVIEW
                      </NavItem>
                    </Nav>
                }
                {
                  props.user && !props.user.admin && !props.user.paid && !props.noUpgrade && props.user.trialend &&
                    <Nav pullRight>
                        {
                          daysleft === 0 ?
                            <NavItem onClick={this.upgrade} className="billing-nav">
                              <FrontendNavigationCCIcon className="dropdown-icon"/>
                              UPGRADE
                            </NavItem>
                          :
                            <NavItem onClick={this.upgrade} className="billing-nav">
                              {daysleft.toLocaleString()}{' '}{daysleft===1?'Day':'Days'} Left
                            </NavItem>
                        }
                    </Nav>
                }
              </Navbar.Collapse>
            </Navbar>
          }
          {props.children}
          {
            props.user && !props.user.admin && this.limitHit() &&
            <div className="space50">&nbsp;</div>
          }
        </header>
        {
          props.user && !props.user.admin && this.limitHit() && !props.user.inreview &&
          <div style={{position:'fixed', bottom: 0, left: 0, zIndex:1, paddingRight: '100px'}} className="alert alert-warning alert-server" role="alert">
            <strong>Daily Limit Hit</strong> You've hit your daily send limit. Any mail to your contacts will be queued until tomorrow at {moment(props.user.limitresettime).format('LT')}. You can still send test messages in the meantime.
          </div>
        }
      </div>
    );
  }
}
