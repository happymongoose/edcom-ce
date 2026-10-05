import React, { Component } from "react";
import { withRouter } from "react-router-dom";
import Routes from "./Routes";
import axios from "axios";
import qs from "qs";
import Notifications from "./components/Notifications";
import notify from "./utils/notify";
import _ from "underscore";
import parse from "./utils/parse";
import LoaderPanel from "./components/LoaderPanel";

import './App.css';

class App extends Component {
  constructor(props) {
    super(props);

    var p = parse(this);

    var uid = '', cookie = '', impersonate = '';
    if (p.impersonate) {
      impersonate = p.impersonate;
      if (window.sessionStorage !== null) {
          sessionStorage['impersonateid'] = impersonate;
      }
    }
    if (window.localStorage !== null &&
      localStorage['uid'] &&
      localStorage['cookieid']) {
      uid = localStorage['uid'];
      cookie = localStorage['cookieid'];
      if (window.sessionStorage !== null) {
        impersonate = sessionStorage['impersonateid'] || '';
      }
    }

    this.state = {
      loggedInUID: uid,
      loggedInCookie: cookie,
      loggedInImpersonate: impersonate,
    };
  }

  componentWillMount() {
    axios.interceptors.response.use(null, _.bind(function(r) {
      if (r.response && r.response.config && r.response.config.url && r.response.config.url.match(/[?&]disablenotify=true/)) {
        return Promise.reject(r);
      }
      if (r.response && r.response.status === 401 && (!["/login", "/reset", "/emailreset", "/welcome", "/activate"].includes(this.props.history.location.pathname))) {
        if (r.response.data && r.response.data.title === 'Impersonation Mismatch') {
          notify.show("You cannot access the user portal from this tab, redirecting to admin portal", "error");
          this.props.history.replace("/");
        } else {
          var url = this.props.history.location.pathname;
          if (this.props.history.location.search)
            url += this.props.history.location.search;
          this.goToLogin(url);
        }
      } else {
        if (r.response) {
          if (r.response.data) {
            var d = r.response.data;
            if (d.description)
              notify.show(d.description, "error");
            else if (d.title)
              notify.show(d.title, "error");
            else if (d.message)
              notify.show(d.message, "error");
            else
              notify.show(r.response.data.toString(), "error");
          } else
            notify.show(r.response.statusText.toString(), "error");
        } else if (r.request) {
          notify.show("No HTTP response received", "error");
        } else {
          notify.show(r.message.toString(), "error");
        }
      }
      return Promise.reject(r);
    }, this));
    axios.interceptors.request.use(_.bind(function(c) {
      if (c.url !== "/api/login") {
        if (this.state.loggedInUID && this.state.loggedInCookie && c.url.startsWith("/api/")) {
          c.headers['X-Auth-UID'] = this.state.loggedInUID;
          c.headers['X-Auth-Cookie'] = this.state.loggedInCookie;
          c.headers['X-Auth-Impersonate'] = this.state.loggedInImpersonate;
        }
      }
      return c;
    }, this));

    this.reloadUser(true);
  }

  setFaviconAndCSS(url, customcss) {
    const head = document.getElementsByTagName('head')[0];
    const links = head.querySelectorAll('link');
    for (let i = links.length - 1; i >= 0; i--) {
      if (links[i].getAttribute('rel') === 'icon' || links[i].getAttribute('rel') === 'shortcut icon') {
        head.removeChild(links[i])
      }
    }

    const link = document.createElement('link');
    link.type='image/x-icon';
    link.rel='icon';
    link.href=url;
    head.appendChild(link);
    const link2 = document.createElement('link');
    link2.rel='shortcut icon';
    link2.href=url;
    head.appendChild(link2);

    const style = document.getElementById('frontend-customcss');
    if (style) {
      head.removeChild(style);
    }

    if (customcss) {
      const custom = document.createElement('style');
      custom.id = 'frontend-customcss';
      custom.innerText = customcss;
      head.appendChild(custom);
    }
  }

  resetFaviconAndCSS() {
    this.setFaviconAndCSS('/favicon.ico', null);
  }

  reloadUser = async first => {
    if (this.state.loggedInUID) {
      this.setState({user: (await axios.get('/api/users/' + this.state.loggedInUID)).data}, () => {
        if (this.state.user) {
          if (this.state.user.frontend) {
            this.setFaviconAndCSS(this.state.user.frontend.favicon || '/favicon-ed.ico', this.state.user.frontend.customcss);
          } else {
            this.setFaviconAndCSS('/favicon-ed.ico', null);
          }
        } else {
          this.resetFaviconAndCSS();
        }
      });
    }
  }

  login = (uid, cookie) => {
    this.setState({
      loggedInUID: uid,
      loggedInCookie: cookie,
      loggedInImpersonate: '',
    }, this.reloadUser.bind(null, true));
  }

  setImpersonate = (cid, path) => {
    if (!path) {
      path = '/';
    }
    window.open(path + '?impersonate=' + cid, '_blank');
  }

  doLogout = async () => {
    axios.post('/api/logout').then(() => {
      this.goToLogin();
    }).catch(() => {
      this.goToLogin();
    });
  }

  logout = () => {
    if (window.localStorage != null) {
      delete localStorage['uid'];
      delete localStorage['cookieid'];
    }
    if (window.sessionStorage != null) {
      delete sessionStorage['impersonateid'];
    }
    this.setState({
      loggedInUID: '',
      loggedInCookie: '',
      loggedInImpersonate: '',
      user: null,
    }, () => {
      this.resetFaviconAndCSS();
    });
  }

  goToLogin = url => {
    this.logout();
    
    if (url) {
      this.props.history.push({pathname: "/login", search: qs.stringify({redirect: url})});
    } else {
      this.props.history.push("/login");
    }
  }

  render() {
    const childProps = {
      login: this.login,
      logout: this.logout,
      user: this.state.user,
      doLogout: this.doLogout,
      setImpersonate: this.setImpersonate,
      loggedInUID: this.state.loggedInUID,
      loggedInCookie: this.state.loggedInCookie,
      loggedInImpersonate: this.state.loggedInImpersonate,
      reloadUser: this.reloadUser,
      setFaviconAndCSS: this.setFaviconAndCSS,
    };
    return (
      <LoaderPanel isLoading={this.state.loggedInUID && !this.state.user}>
        <div className="App">
          <Notifications />
          <Routes childProps={childProps} />
        </div>
      </LoaderPanel>
    );
  }
}

export default withRouter(App);
