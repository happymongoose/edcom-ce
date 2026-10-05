import React, { Component } from "react";
import { Nav, Navbar, NavItem, Button } from "react-bootstrap";
import LoaderButton from "./LoaderButton";

import "./SaveNavbar.css";

export default class SaveNavbar extends Component {
  saveAndClose = async event => {
    await this.props.onSave(event);
    await this.props.onCancel(event);
  }
    
  render() {
    var props = this.props;
    
    return (
      <div className="save-navbar">
        <Navbar fluid className={props.isAdmin ? 'backend' : undefined}>
          <div className="flex-items space-between">
            <Navbar.Text>
              {props.onBack && <i className="back-arrow fa fa-arrow-left" onClick={props.onBack}/>}
              <span className="title-text">{props.title}</span>
            </Navbar.Text>
            {props.buttons &&
              <div className="text-right">
                {props.buttons}
              </div>
            }
            {!props.buttons &&
              <Nav pullRight className="nav-buttons">
                {props.onCancel &&
                  <NavItem className="nav-button">
                    <Button onClick={props.onCancel}>
                      { props.cancelText ? props.cancelText : 'Cancel' }
                    </Button>
                  </NavItem>
                }
                {!props.hideSave && props.id !== 'new' &&
                  <NavItem className="nav-button">
                    <LoaderButton
                      bsStyle={props.saveText?"primary":"default"}
                      text={props.saveText?props.saveText:"Save"}
                      loadingText="Saving..."
                      disabled={props.disabled || props.isSaving}
                      onClick={props.onSave}
                    />
                  </NavItem>
                }
                {(!props.hideSave && !props.saveText) &&
                  <NavItem className="nav-button">
                    <LoaderButton
                      bsStyle="primary"
                      text="Save and Close"
                      loadingText="Saving..."
                      disabled={props.disabled || props.isSaving}
                      onClick={this.saveAndClose}
                    />
                  </NavItem>
                }
              </Nav>
            }
          </div>
        </Navbar>
        {
          props.loggedInImpersonate &&
          <div className="alert alert-info alert-server" role="alert">
            This is the customer data view. <strong>Close this browser tab to exit.</strong>
          </div>
        }
        {props.children}
      </div>
    );
  }
}
