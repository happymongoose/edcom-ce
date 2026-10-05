import React, { Component } from "react";
import { sendGA4Event } from "../utils/tracking";
import axios from "axios";
import { Glyphicon, Modal, DropdownButton, MenuItem, Row, Col, Button, Radio, ControlLabel } from "react-bootstrap";
import LoaderPanel from "../components/LoaderPanel";
import LoaderIcon from "../components/LoaderIcon";
import withLoadSave from "../components/LoadSave";
import { FormControlLabel, CheckboxLabel } from "../components/FormControls";
import getvalue from "../utils/getvalue";
import notify from "../utils/notify";
import _ from "underscore";
import * as Papa from "papaparse";
import update from 'immutability-helper';
import properties from "../utils/sys-props";
import SaveNavbar from "../components/SaveNavbar";
import { EDFormSection, EDFormBox, EDFormGroup } from "../components/EDDOM";
import EDDataSheet from "../components/EDDataSheet";
import { Lightbox } from "../components/react-modal-image/src";
import Dropzone from 'react-dropzone';

import "react-select2-wrapper/css/select2.css";

import "./ContactsAdd.css";

function cph(t) {
  return <span style={{color:'#ccc'}}>{t}</span>;
}

class HeadersChoice extends Component {
  render() {
    return (
      <EDFormGroup space={this.props.space}>
        <ControlLabel>Does your contact list have column headers?</ControlLabel>
        <div/>
        <Radio id="headeryes" name="headerGroup" inline checked={this.props.headers}  onChange={this.props.handleChange}>Yes</Radio>
        <Radio id="headerno"  name="headerGroup" inline checked={!this.props.headers} onChange={this.props.handleChange}>No</Radio>
        {' '}
        <a href="#idk" onClick={this.props.showLightbox} style={{marginLeft: '14px', fontSize:'14px', fontWeight: 500, verticalAlign: 'top'}}><i className="fa fa-question-circle" style={{verticalAlign:'top',paddingTop:'3px'}}/> I Don't Know</a>
      </EDFormGroup>
    );
  }
}

class ContactsAdd extends Component {
  constructor(props) {
    super(props);

    this.state = {
      mode: 'input',
      type: 'file',
      data: [],
      file: null,
      headers: true,
      isUploading: false,
      propmap: {},
      valmap: {},
      indmap: [],
      override: false,
      lightbox: false,
      showConfirm: false,
      newPropName: '',
      newprops: [],
    }
  }

  showLightbox = () => {
    this.setState({lightbox: true});
  }

  hideLightbox = () => {
    this.setState({lightbox: false});
  }

  reset = () => {
    this.setState({
      mode: 'input',
      propmap: {},
      valmap: {},
      indmap: [],
    });
  }

  onFileChange = e => { 
    this.onDrop(e.target.files);
  }

  onDrop = files => {
    if (files.length > 0) {
      this.setState({file: files[0]});
    }
  }

  handleChange = event => {
    this.setState({[event.target.id]: getvalue(event)})
  }

  handleRadioChange = event => {
    this.setState({headers: event.target.id === 'headeryes'})
  }

  handleRadioChange2 = event => {
    this.setState({headers: event.target.id === 'headeryes'}, () => {
        this.doParse();
    })
  }

  handleDataChange = event => {
    this.props.update({[event.target.id]: {$set: event.target.value}})
  }
  
  setProp = (k, p) => {
    this.setState({propmap: update(this.state.propmap, {[k]: {$set: p}})});
  }

  validateUpload = () => {
    var k;
    var counts = {};
    for (k in this.state.propmap) {
      if (this.state.propmap[k] === 'Domain') {
        notify.show("A field cannot be mapped to the 'Domain' property", "error");
        return false;
      }
      if (this.state.propmap[k]) {
        counts[this.state.propmap[k]] = (counts[this.state.propmap[k]] || 0) + 1;
      }
    }
    for (k in counts) {
      if (counts[k] > 1) {
        notify.show("The field '" + k + "' cannot be mapped more than once", "error");
        return false;
      }
    }
    for (k in this.state.propmap) {
      if (this.state.propmap[k] === 'Email') {
        return true;
      }
    }

    notify.show("One field must be mapped to the 'Email' property", "error");
    return false;
  }

  parseData = res => {
    if (res.length === 0) {
      if (this.state.type === 'file') {
        notify.show("That file contains no CSV records", "error");
      } else {
        notify.show("Please enter some contact data", "error");
      }
      return;
    }

    var propmap = {};
    var valmap = {};
    var indmap = [];
    var foundemail = false;
    var i, r;
    if (!this.state.headers) {
      for (i = 0; i < res[0].length; i++) {
        if (/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}\b/.test(res[0][i]) && !foundemail) {
          propmap['Column ' + (i + 1)] = 'Email';
          foundemail = true
        } else {
          propmap['Column ' + (i + 1)] = '';
        }
        valmap['Column ' + (i + 1)] = [res[0][i]];
        indmap.push('Column ' + (i + 1));
      }
      for (r = 1; r < res.length && r < 3; r++) {
        for (i = 0; i < res[r].length; i++) {
          valmap['Column ' + (i + 1)].push(res[r][i]);
        }
      }
    } else {
      var unk = 1;
      _.each(res[0], _.bind(function(c, i) {
        if (!c) {
          c = "Unknown " + unk;
          unk++;
        }

        var check = c;
        var ind = 2;
        while (!_.isUndefined(propmap[check])) {
          check = c + '_' + ind;
          ind++;
        }
        c = check;

        if (res.length > 1 && /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}\b/.test(res[1][i]) && !foundemail) {
          propmap[c] = 'Email';
          foundemail = true;
        } else {
          var prop = _.find(properties, p => p.toLowerCase() === c.toLowerCase());
          if (prop) {
            propmap[c] = prop;
            if (prop === 'Email')
              foundemail = true
          } else {
            propmap[c] = '';
          }
        }

        if (res.length > 1) {
          valmap[c] = [res[1][i]];
        } else {
          valmap[c] = [''];
        }
        indmap.push(c);
      }, this));
      for (r = 2; r < res.length && r < 4; r++) {
        for (i = 0; i < res[r].length; i++) {
          valmap[indmap[i]].push(res[r][i]);
        }
      }
    }

    this.setState({mode: 'map', propmap: propmap, valmap: valmap, indmap: indmap});
  }

  dataToCSV() {
    var rows = this.dataToRows();

    var s = _.map(rows, r => {
      return _.map(r, c => {
        if (c.includes(',') || c.includes('\n') || c.includes('"')) {
          return '"' + c.replace('"', '""') + '"';
        } else {
          return c;
        }
      }).join(',');
    }).join('\n');
    if (s) {
      s += '\n';
    }
    return s;
  }

  dataToRows() {
    var res = [];
    var maxlen = 0;
    this.state.data.forEach(r => {
      var len = 9;
      for (len = 9; len >= 1; len--) {
        if (r['col' + len]) {
          break;
        }
      }

      if (len > maxlen) {
        maxlen = len;
      }
    });

    this.state.data.forEach(r => {
      var arr = [];

      for (var i = 1; i <= maxlen; i++) {
        arr.push(r['col' + i] || '');
      }

      res.push(arr);
    });

    return res;
  }

  doParse = () => {
    if (this.state.type === 'manual') {
      this.parseData(this.dataToRows());
    } else {
      var f = this.state.file;
      if (f === null) {
        notify.show("Please choose a file before continuing.", "error");
        return;
      }
      if (!f.name.endsWith(".txt") && !f.name.endsWith(".csv")) {
        notify.show("Invalid file type. Please select a CSV file (extension .csv or .txt).", "error");
        return;
      }
      if (f.size > 1024 * 1024 * 500) {
        notify.show("This file is too large to process, please contact support for more information", "error");
        return;
      }
      var reader = new FileReader();
      reader.onload = _.bind(e => {
        if (e.target.result.indexOf('\0') >= 0) {
          notify.show("This file appears to contain binary data, please use one that contains text in CSV format", "error");
          return;
        }
        var res = [];
        try {
          res = Papa.parse(e.target.result, {delimiter: ','}).data;
        } catch (e) {
          notify.show("Error parsing CSV file: " + e + ". Please use a properly formatted CSV file.", "error");
          return;
        }
        this.parseData(res);
      }, this);
      reader.onerror = e => {
        notify.show(e.target.error.toString(), "error");
      }
      reader.readAsText(f.slice(0, 1024 * 1024));
    }
  }

  handleSubmit = event => {
    event.preventDefault();

    if (this.props.data.processing) {
      notify.show("List data is currently processing. Try again later.", "error");
      this.props.history.push("/contacts");
      return;
    }

    this.doParse();
  }

  handleCreateEmpty = async () => {
    await this.props.save();
    notify.show("Contact list created", "success");
    this.goBack();
  }

  handleSubmit2 = async event => {
    sendGA4Event('Contacts', 'Uploaded Contact List', 'Added Contact List Data');
    event.preventDefault();

    if (!this.validateUpload()) {
      return;
    }

    this.setState({isUploading: true});

    var upload;
    try {
      upload = (await axios({
        method: 'post',
        url: '/api/uploadfile',
        headers: { "Content-Type": `text/plain` },
        data: this.state.type === 'manual' ? new Blob([this.dataToCSV()], { type: "text/plain" }) : this.state.file
      })).data;
    } catch (e) {
      this.setState({isUploading: false});
      throw e;
    }

    var colmap = [];
    for (var i = 0; i < this.state.indmap.length; i++) {
      colmap.push(this.state.propmap[this.state.indmap[i]]);
    }

    var id;
    if (this.props.id === 'new') {
      id = (await this.props.save()).data.id;
    } else {
      id = this.props.id;
    }

    await axios.post('/api/lists/' + id + '/import', {
      key: upload.key,
      colmap: colmap,
      headers: this.state.headers,
      override: this.state.override,
    });

    notify.show("Your contacts are importing and will be available shortly", "success", 15000);

    this.goBack();
  }

  goBack = () => {
    this.props.history.push("/contacts");
  }

  newProp = k => {
    this.setState({showConfirm: k, newPropName: ''});
  }

  createConfirmClicked = yes => {
    if (!yes) {
      this.setState({showConfirm: false});
      return;
    }

    var k = this.state.showConfirm;

    var newprops = _.clone(this.state.newprops);
    if (!_.find(newprops, p => p === this.state.newPropName) &&
        !_.find(properties, p => p === this.state.newPropName) &&
        !_.find(this.props.allfields, p => p === this.state.newPropName)) {
      newprops.splice(0, 0, this.state.newPropName);
    }

    this.setState({showConfirm: false, newprops: newprops}, () => {
      this.setProp(k, this.state.newPropName);
    });
  }

  componentDidUpdate() {
    window.$("div.dropzone").attr("tabindex", "");
  }

  render() {
    var dataName = this.props.data && (this.props.data.name || '')

    var fields = _.sortBy(_.filter(this.state.newprops, p => p !== 'Email'), p => p.toLowerCase());
    if (this.props.allfields) {
      fields = fields.concat(_.sortBy(_.filter(this.props.allfields, p => p !== 'Email' && !_.find(fields, f => p === f)), p => p.toLowerCase()));
    }
    fields = fields.concat(_.filter(properties, p => p !== 'Email' && !_.find(fields, f => p === f)));
    fields.splice(0, 0, 'Email');

    return (
      <LoaderPanel isLoading={this.props.isLoading}>
        <SaveNavbar title={this.props.id === 'new' ? 'Create Contact List' : `Add Contacts ${dataName ? 'to ' + dataName : ''}`} hideSave={true} onBack={this.goBack} user={this.props.user}>
          {
            this.state.lightbox &&
            <Lightbox
              large="/img/headers.png"
              alt="If your contact list has a title at the top of each column, you have column headers"
              onClose={this.hideLightbox}
              hideDownload={true}
              hideZoom={true}
            />
          }
          <Modal show={this.state.showConfirm}>
            <Modal.Header>
              <Modal.Title>Create Property</Modal.Title>
            </Modal.Header>
            <Modal.Body>
              <FormControlLabel
                id="newPropName"
                label="Name"
                obj={this.state}
                onChange={this.handleChange}
              />
            </Modal.Body>
            <Modal.Footer>
              <Button onClick={this.createConfirmClicked.bind(this, true)} bsStyle="primary"
                disabled={!this.state.newPropName || this.state.newPropName === 'Ignore this Field' || this.state.newPropName.includes(',') || this.state.newPropName.includes('!') || this.state.newPropName.length > 50}>
                Create
              </Button>
              <Button onClick={this.createConfirmClicked.bind(this, false)}>Cancel</Button>
            </Modal.Footer>
          </Modal>
          {this.state.isUploading ?
            <EDFormSection>
              <EDFormBox>
                <div className="text-center">
                  <h4>Uploading contacts, please wait...</h4>
                  <LoaderIcon />
                </div>
              </EDFormBox>
            </EDFormSection>
           :
            this.state.mode === 'input' ?
              <EDFormSection onSubmit={this.handleSubmit}>
                {
                  this.props.id === 'new' && 
                    <EDFormBox>
                      <FormControlLabel
                        id="name"
                        label="Name"
                        obj={this.props.data}
                        onChange={this.handleDataChange}
                        required={true}
                      />
                    </EDFormBox>
                }
                <EDFormBox space={this.props.id === 'new'}>
                  <EDFormGroup controlId="type">
                    <ControlLabel>How would you like to import contact data?</ControlLabel>
                    <div />
                    <Radio inline name="typeGroup" id="type" value="file" checked={this.state.type==='file'} onChange={this.handleChange}>Upload a file</Radio>
                    <Radio inline name="typeGroup" id="type" value="manual" checked={this.state.type==='manual'} onChange={this.handleChange}>Copy and paste</Radio>
                    <div className="space20"/>
                  </EDFormGroup>
                  {
                    this.state.type === 'manual' ?
                      <div style={{paddingBottom:'20px'}}>
                        <HeadersChoice showLightbox={this.showLightbox} headers={this.state.headers} handleChange={this.handleRadioChange} />
                        <div className="space20"/>
                        <EDDataSheet
                          id="data"
                          obj={this.state}
                          groupStyle={{overflowX: 'scroll'}}
                          onChange={this.handleChange}
                          placeholders={
                            this.state.headers ?
                              [[cph('Email'), cph('First Name')],[cph('barbara@petpsychic.com'),cph('Barbara')],[cph('acethedog@petpsychic.com'), cph('Ace')]]
                            :
                              [[cph('barbara@petpsychic.com'),cph('Barbara')],[cph('acethedog@petpsychic.com'), cph('Ace')]]
                          }
                          help="You can copy and paste contact data directly from a spreadsheet into the cells above, or click in a cell and manually type your data."
                          columns={[{display: 'Column 1', name: 'col1'},
                                    {display: 'Column 2', name: 'col2'},
                                    {display: 'Column 3', name: 'col3'},
                                    {display: 'Column 4', name: 'col4'},
                                    {display: 'Column 5', name: 'col5'},
                                    {display: 'Column 6', name: 'col6'},
                                    {display: 'Column 7', name: 'col7'},
                                    {display: 'Column 8', name: 'col8'},
                                    {display: 'Column 9', name: 'col9'}]}
                          widths={[220, 220, 220, 220, 220, 220, 220, 220, 220]}
                        />
                      </div>
                    :
                      <EDFormGroup controlId="file">
                        <div className="text-center">
                          <Dropzone onDrop={this.onDrop} accept="text/*" multiple={false} disableClick>
                            {({getRootProps, getInputProps, isDragActive}) => {
                              return (
                                <div
                                  {...getRootProps()}
                                  className={'dropzone ' + (isDragActive ? 'dropzone--isActive' : '')}
                                >
                                  <input {...getInputProps()} />
                                  {
                                    this.state.file !== null ?
                                      <p>
                                        <i className="fa fa-thumbs-up"/>
                                        Ready: {this.state.file.name}
                                        <br/>
                                        <button type="button" onClick={() => this.setState({file: null})}>Choose a different file</button>
                                      </p>
                                    :
                                      <div className="upload-text">
                                        <i className="fa fa-upload"/>
                                        <h4>Drag a CSV file here</h4>
                                        <p>Or, if you prefer...</p>
                                        <input type="file" accept="text/*" onChange={this.onFileChange} />
                                      </div>
                                  }
                                </div>
                              );
                            }}
                          </Dropzone>
                        </div>
                      </EDFormGroup>
                  }
                  <EDFormGroup className="text-center">
                    {
                      this.props.id === 'new' &&
                      <Button
                        bsSize="large"
                        disabled={this.props.isSaving || !this.props.data.name}
                        onClick={this.handleCreateEmpty}
                        style={{marginRight: '40px'}}
                      >
                        Create Empty List
                      </Button>
                    }
                    <Button bsStyle="primary" bsSize="large" type="submit">Next</Button>
                  </EDFormGroup>
                </EDFormBox>
              </EDFormSection>
            :
              <EDFormSection onSubmit={this.handleSubmit2}>
                <EDFormBox>
                  <h4>Choose a contact list property for each field{this.state.type===' file'?' in the file':''}.</h4>
                  <h4><small>One field must be mapped to the "Email" property in order to proceed.</small></h4>
                  <HeadersChoice space={true} showLightbox={this.showLightbox} headers={this.state.headers} handleChange={this.handleRadioChange2} />
                  {
                    _.map(this.state.propmap, (v, k) => {
                      return (
                        <Row key={k} className="space15">
                          <Col xs={7}>
                            <table className="table table-condensed table-fieldmap">
                              <thead>
                                <tr>
                                  <th>
                                    {k}
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {
                                  _.map(this.state.valmap[k], (v, i) => (
                                    <tr key={i}>
                                      <td>
                                        {v?v:<span>&nbsp;</span>}
                                      </td>
                                    </tr>
                                  ))
                                }
                              </tbody>
                            </table>
                          </Col>
                          <Col xs={5}>
                            <div className="fieldmap">
                              <div className="fieldmap-arrow"/>
                              <p>
                                Map to...
                              </p>
                              <DropdownButton
                                id={k}
                                title={this.state.propmap[k]?this.state.propmap[k]:'Ignore this Field'}
                                style={{width: '100%'}}
                                className={this.state.propmap[k]?'':'ignore'}
                              >
                                <MenuItem onClick={this.newProp.bind(null, k)}>Create New Property...</MenuItem>
                                <MenuItem className="ignore" onClick={this.setProp.bind(null, k, '')}>
                                  {
                                    !this.state.propmap[k] && <Glyphicon glyph="ok" />
                                  }
                                  Ignore this Field
                                </MenuItem>
                                <MenuItem divider />
                                {
                                  _.map(fields,
                                    p => <MenuItem key={p} onClick={this.setProp.bind(null, k, p)}>
                                           {
                                            this.state.propmap[k] === p &&
                                              <Glyphicon glyph="ok" />
                                           }
                                           {p}
                                         </MenuItem>)
                                }
                              </DropdownButton>
                            </div>
                          </Col>
                        </Row>
                      );
                    })
                  }
                  <div className="space20" />
                  <CheckboxLabel
                    id="override"
                    label="Resubscribe any existing contacts who unsubscribed"
                    obj={this.props.data}
                    onChange={this.handleChange}
                  />
                  <EDFormGroup className="text-center">
                    <Button bsSize="large" onClick={this.reset} style={{marginRight: '40px'}}>Go Back</Button>
                    <Button bsStyle="primary" bsSize="large" type="submit">Upload</Button>
                  </EDFormGroup>
                </EDFormBox>
              </EDFormSection>
          }
        </SaveNavbar>
      </LoaderPanel>
    );
  }
}

export default withLoadSave({
  initial: { name: '', count: 0 },
  extend: ContactsAdd,
  get: async ({id}) => (await axios.get('/api/lists/' + id)).data,
  post: ({data}) => axios.post('/api/lists', data),
  extra: {
    allfields: async () => (await axios.get('/api/allfields')).data,
  },
});
