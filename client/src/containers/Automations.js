import React, { Component } from "react";
import MenuNavbar from "../components/MenuNavbar";
import TitlePage from "../components/TitlePage";
import { EDTableSection } from "../components/EDDOM";

export default class Automations extends Component {
  render() {
    return (
      <MenuNavbar {...this.props}>
        <TitlePage title="Automations" />
        <EDTableSection className="contact drop-blue">
          <div className="text-center space-top-sm">
            <h4>You don&apos;t have any automations yet!</h4>
          </div>
        </EDTableSection>
      </MenuNavbar>
    );
  }
}
