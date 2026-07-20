import React, { Component } from "react";
import ReactDOM from "react-dom";
import { Controlled as CodeMirror } from "react-codemirror2";
import { Tabs, Tab, Row, Col, ControlLabel, PanelGroup, Panel, Modal, MenuItem, DropdownButton, FormControl, Glyphicon, Button, ButtonGroup, ButtonToolbar, Overlay, Popover, Dropdown, InputGroup } from "react-bootstrap";
import update from 'immutability-helper';
import _ from "underscore";
import { Editor, EditorState, SelectionState, CompositeDecorator, ContentState, RichUtils, Modifier, convertToRaw, convertFromRaw } from "draft-js";
import { ColorControl, ColorPopup, FormControlPopup, LinkPopup } from "./PopupControls";
import { FormControlLabel, SelectLabel, CheckboxLabel } from "./FormControls";
import LoaderIcon from "./LoaderIcon";
import LoaderButton from "./LoaderButton";
import getvalue from "../utils/getvalue";
import { getImageSize } from "../utils/get-image";
import shortid from "shortid";
import axios from "axios";
import notify from "../utils/notify";
import { insertPopups, popupCSS, getHTML } from "../utils/template-utils";
import sanitizeHTML from "../utils/sanitize-html";
import createStyles from "draft-js-custom-styles";
import { stateToHTML } from "draft-js-export-html";
import Toggle from "react-toggle";
import moment from "moment";
import Select2 from "react-select2-wrapper";

import "codemirror/mode/xml/xml";
import "codemirror/mode/css/css";
import "codemirror/mode/htmlmixed/htmlmixed";
import "codemirror/lib/codemirror.css";
import "../../node_modules/draft-js/dist/Draft.css";
import "font-awesome/css/font-awesome.css";
import "./TemplateEditor.css";
import "./foundation.css";
import "react-toggle/style.css";
import "react-select2-wrapper/css/select2.css";

function truncate(n) {
  if (n < 0) {
    return Math.ceil(n);
  } else {
    return Math.floor(n);
  }
}

const SIDEBAR_WIDTH = 217;

const DEFAULT_MOBILE_WIDTH = 414;

const canInherit = {
  color: true,
  fontFamily: true,
  fontSize: true,
  lineHeight: true,
  align: true,
};

const needsPixels = {
  marginTop: true,
  marginBottom: true,
  marginLeft: true,
  marginRight: true,
  paddingTop: true,
  paddingBottom: true,
  paddingLeft: true,
  paddingRight: true,
  borderWidth: true,
  borderRadius: true,
  fontSize: true,
};

function draftStyles(s) {
  s =    s.replace(/<p><\/p>/g, '<p>&nbsp;</p>');
  //s =    s.replace(/<br>/g, '<br><br>');
  return s.replace(/<p>/g,  '<p style="margin:0; Margin: 0">');
}

function fromSidebar(event) {
  var p = event.target;
  while (p !== null) {
    if (p.id === 'PartDrawer') {
      return true;
    }
    p = p.parentNode;
  }
  return false;
}

function fromProperties(event, forclick) {
  var p = event.target;
  while (p !== null) {
    if (p.id === 'parttabs' || p.tagName === "BUTTON" || p.tagName === 'INPUT' ||
       (p.className && p.className.includes && (
        (forclick && p.className.includes("DraftEditor-root")) ||
        p.className.includes("dropdown-menu") ||
        (p.className === 'popup-toolbar') ||
        (p.className === 'popover-content')
      ))
    ) {
      return true;
    }
    p = p.parentNode;
  }
  return false;
}

function isDefault(prop, val) {
  switch (prop) {
  case 'borderStyle':
    return val === 'none';
  case 'align':
    return val === 'center';
  default:
    return false;
  }
}

function backgroundStyle(f) {
  if (!f.backgroundType) {
    return {};
  } else if (f.backgroundType === 'color') {
    return {backgroundColor: f.backgroundColor || '#ffffff'};
  } else {
    return {
      background: 'url(' + f.backgroundImage + ')',
      backgroundSize: f.backgroundSize === 'cover' ? 'cover' : undefined,
    };
  }
}

function borderStyle(f) {
  if (_.isUndefined(f.borderStyle) || f.borderStyle === 'none') {
    return {
     borderStyle: 'none',
    };
  }
  return {
     borderStyle: f.borderStyle,
     borderColor: f.borderColor,
     borderWidth: f.borderWidth,
     borderRadius: f.borderRadius,
     overflow: (f.selected && !f.displayOnly)?undefined:'hidden',
  }
}

function widthStyle(f) {
  if (f.bodyType === 'fixed') {
    return {
      margin: '0 auto',
      width: f.bodyWidth + 'px',
    };
  } else {
    return {
      width: '100%',
    };
  }
}

function marginStyle(f) {
  return {
    marginTop: f.marginTop,
    marginBottom: f.marginBottom,
    marginLeft: f.marginLeft,
    marginRight: f.marginRight,
  };
}

function paddingStyle(f, forcols) {
  var left = f.paddingLeft;
  var right = f.paddingRight;

  if (forcols) {
    left = left.substring(0, left.length - 2);
    left *= 0.5;
    left += 'px';
    right = right.substring(0, right.length - 2);
    right *= 0.5;
    right += 'px';
  }

  return {
    paddingTop: f.paddingTop,
    paddingBottom: f.paddingBottom,
    paddingLeft: left,
    paddingRight: right,
  };
}

const fonts = ['Arial', 'Arial Black', 'Bitter', 'Cabin', 'Courier', 'Courier New', 'Garamond',
               'Georgia', 'Helvetica', 'Impact', 'Karla', 'Lato', 'Lobster', 'Lora',
               'Montserrat', 'Open Sans', 'Oswald', 'Palatino', 'Playfair Display',
               'Roboto', 'Times', 'Trebuchet MS', 'Verdana'];

const defaultBodyStyle = {
  marginTop: 0,
  marginBottom: 0,
  marginLeft: 0,
  marginRight: 0,
  paddingTop: 0,
  paddingBottom: 0,
  paddingLeft: 0,
  paddingRight: 0,
  borderStyle: 'none',
  borderColor: '#333333',
  borderWidth: 1,
  borderRadius: 0,
  align: 'center',
  color: '#333333',
  linkColor: '#3b5998',
  linkUnderline: true,
  backgroundType: 'color',
  backgroundColor: '#ffffff',
  backgroundSize: '',
  backgroundImage: '',
  fontFamily: 'Helvetica',
  fontSize: 16,
  lineHeight: 1.3,
  bodyType: 'fixed',
  bodyWidth: 580,
  formCloseEnable: true,
  formCloseBorder: true,
  formCloseStyle: '',
  formCloseTop: 0,
  formCloseRight: 0,
  formCloseSize: 26,
  mobileWidth: '',
};

const defaultPartStyle = {
  paddingTop: 10,
  paddingBottom: 10,
  paddingLeft: 10,
  paddingRight: 10,
};

const themes = [
  {
    name: 'Gray',
    top: '#aaaaaa',
    bottom: '#8c8c8c',
    inset: '#ff5d55',
  },
  {
    name: 'Sand',
    top: '#b5aa9d',
    bottom: '#b9b7a7',
    inset: '#747274',
  },
  {
    name: 'Aqua',
    top: '#98cbb4',
    bottom: '#7ba098',
    inset: '#474935',
  },
  {
    name: 'Sunshine',
    top: '#ebd494',
    bottom: '#9ad2cb',
    inset: '#472836',
  },
  {
    name: 'Bold',
    top: '#7daa92',
    bottom: '#c2fbef',
    inset: '#8e4a49',
  },
];

function findLinkEntities(contentBlock, callback, contentState) {
  contentBlock.findEntityRanges(
    (character) => {
      const entityKey = character.getEntity();
      return (
        entityKey !== null &&
        contentState.getEntity(entityKey).getType() === 'LINK'
      );
    },
    callback
  );
}

function createPart(form, incols, part, txt, props) {
  var newPart = {
    type: part,
    id: shortid.generate(),
  };
  if (form && !incols) {
    newPart.backgroundType = 'color';
    newPart.backgroundColor = '#ffffff';
  }
  const t = themes[0];
  if (part === 'Headline') {
    txt = txt || 'Headline That Grabs Your Attention';
    newPart.content = convertToRaw(ContentState.createFromText(txt));
    newPart.fontSize = 30;
  } else if (part === 'Image') {
    newPart.src = '';
    newPart.scale = 100;
    newPart.width = null;
    newPart.height = null;
    newPart.link = '';
  } else if (part === 'Text') {
    txt = txt || 'A text block which can contain different styles and links.';
    newPart.align = 'left';
    newPart.content = convertToRaw(ContentState.createFromText(txt));
  } else if (part === 'HTML') {
    newPart.customHtml = txt || '<p>Enter your HTML here.</p>';
  } else if (part === 'Divider') {
    newPart.size = 3;
    newPart.top = 20;
    newPart.bottom = 20;
    newPart.left = 0;
    newPart.right = 0;
  } else if (part === 'Button') {
    newPart.text = form?'Subscribe':'Click Me';
    newPart.link = '';
    newPart.fontSize = 24;
    newPart.color = '#FFFFFF';
    newPart.buttonColor = t.inset;
  } else if (part === 'Input') {
    newPart.placeholder = '';
    newPart.field = '';
    newPart.fontSize = 16;
    newPart.color = '#333333';
    newPart.inputColor = '#ffffff';
    newPart.inputBorderColor = '#c0c0c0';
    newPart.inputHeight = 6;
    newPart.inputWidth = 6;
    newPart.inputRadius = 2;
    newPart.inputType = 'text';
    newPart.align = 'left';
    newPart.required = true;
  } else if (part === 'Columns') {
    newPart.stack = true;
    newPart.parts = [null, null];
    newPart.widths = [6, 6];
    newPart.valign = 'top';
  } else if (part === 'Social') {
    newPart.facebook = true;
    newPart.facebookLink = '';
    newPart.facebookLabel = 'Share';
    newPart.twitter = true;
    newPart.twitterLink = '';
    newPart.twitterLabel = 'Tweet';
    newPart.instagram = true;
    newPart.instagramLink = '';
    newPart.instagramLabel = 'Share';
    newPart.pinterest = false;
    newPart.pinterestLink = '';
    newPart.pinterestLabel = 'Pin it';
    newPart.linkedin = false;
    newPart.linkedinLink = '';
    newPart.linkedinLabel = 'Share'
    newPart.labels = true;
    newPart.iconColor = 'default';
    newPart.iconCustom = '#AAAAAA';
    newPart.layout = 'horizontal';
    newPart.fontSize = 12;
  } else if (part === 'Spacer') {
    newPart.height = 50;
  }
  if (props)
    newPart = _.extend(newPart, props);
  return newPart;
}

class EditToolbar extends Component {
  render() {
    var width = 'calc(100% - 110px)';
    if (this.props.isInCol) {
      width= '330px';
    }
    return (
      <ButtonToolbar
        className="edit-toolbar"
        style={{position: 'absolute', left: this.props.isInCol?'1px':'54px', top: 'calc(100% + 14px)', zIndex: 1001, width: width}}
      >
        {this.props.children}
      </ButtonToolbar>
    );
  }
}

class PartToolbar extends Component {
  render() {
    var {first, last, right, top, removeOnly} = this.props;
    return (
      <ButtonGroup vertical style={{
        position: 'absolute',
        top: top + 'px',
        right: right + 'px',
        zIndex: 1001,
      }}>
        { !removeOnly &&
        <ButtonGroup vertical>
          <Button className="square-btn" onClick={this.props.moveUp} disabled={first}><i className="fa fa-chevron-up"/></Button>
          <Button className="square-btn" onClick={this.props.moveDown} disabled={last}><i className="fa fa-chevron-down"/></Button>
        </ButtonGroup>
        }
        { !removeOnly &&
        <div className="space10"/>
        }
        { !removeOnly &&
        <ButtonGroup vertical>
          <Button className="square-btn" onClick={this.props.duplicate}><i className="fa fa-copy"/></Button>
        </ButtonGroup>
        }
        { !removeOnly &&
        <div className="space10"/>
        }
        <ButtonGroup vertical>
          <Button className="square-btn" onClick={this.props.remove}><Glyphicon glyph="trash" /></Button>
        </ButtonGroup>
      </ButtonGroup>
    );
  }
}

class Link extends Component {
  doNothing = event => {
    event.preventDefault();
  }

  render() {
    var props = this.props;
    const {style} = props;
    let {url, color, underline} = props.contentState.getEntity(props.entityKey).getData();
    if (_.isUndefined(color)) {
      color = style.linkColor;
    }
    if (_.isUndefined(underline)) {
      underline = style.linkUnderline;
    }
    return (
      <a href={url} target="_blank" style={{color: color, textDecoration: underline?'underline':'none'}} onClick={this.doNothing}>
        {props.children}
      </a>
    );
  }
}

class PopupToolbar extends Component {
  constructor(props) {
    super(props);

    this.state = {
      activeKey: 0,
      show: false,
    };
  }

  onClick = event => {
    this.setState({show: !this.state.show}, () => {
      this.props.onBorderSelect(this.state.show);
    });
  }

  onSelect = activeKey => {
    if (activeKey !== null) {
      this.setState({activeKey: activeKey});
    }
  }

  render() {
    return (
      <div style={{left: this.props.left + 'px', top: this.props.top + 'px'}} className="popup-toolbar">
        <Button onClick={this.onClick} ref={
          button => {
            this._target = button;
          }
        }>
          <i className="fa fa-pencil"/>
        </Button>
        <Overlay placement="left" container={this} target={() => ReactDOM.findDOMNode(this._target)} show={this.state.show}>
          <Popover id="edit-popover">
            <PanelGroup accordion id="edit-accordion" activeKey={this.state.activeKey} onSelect={this.onSelect}>
              {
                _.map(this.props.panels, (p, i) => {
                  if (this.props.form && p.name === 'Width') {
                    return false;
                  } else {
                    return (
                      <Panel key={i} eventKey={i}>
                        <Panel.Heading>
                          <Panel.Title toggle>{p.name}</Panel.Title>
                        </Panel.Heading>
                        <Panel.Body collapsible>
                          {p.body}
                        </Panel.Body>
                      </Panel>
                    );
                  }
                })
              }
            </PanelGroup>
          </Popover>
        </Overlay>
      </div>
    );
  }
}

class SpacerPanel extends Component {
  render() {
    var p = this.props;
    return (
      <div>
        <FormControlLabel
          id={this.props.type + 'Top'}
          obj={p.obj}
          label="Top"
          onChange={p.onChange}
          type="number"
          min="0"
          style={{width:"64px"}}
          groupStyle={{paddingLeft:'37px'}}
        />
        <Row>
          <Col xs={6}>
            <FormControlLabel
              id={this.props.type + 'Left'}
              obj={p.obj}
              label="Left"
              onChange={p.onChange}
              type="number"
              min="0"
              style={{width:"64px"}}
            />
          </Col>
          <Col xs={6}>
            <FormControlLabel
              id={this.props.type + 'Right'}
              obj={p.obj}
              label="Right"
              onChange={p.onChange}
              type="number"
              min="0"
              style={{width:"64px"}}
            />
          </Col>
        </Row>
        <FormControlLabel
          id={this.props.type + 'Bottom'}
          obj={p.obj}
          label="Bottom"
          onChange={p.onChange}
          type="number"
          min="0"
          style={{width:"64px"}}
          groupStyle={{paddingLeft:'37px'}}
        />
      </div>
    );
  }
}

class ColumnsPanel extends Component {
  render() {
    var p = this.props;
    return (
      <div>
        <label>Number</label>
        <ButtonGroup>
          <Button active={p.obj.parts.length === 1} disabled={p.compCount > 1} onClick={p.setCols.bind(null, 1)}>1</Button>
          <Button active={p.obj.parts.length === 2} disabled={p.compCount > 2} onClick={p.setCols.bind(null, 2)}>2</Button>
          <Button active={p.obj.parts.length === 3} disabled={p.compCount > 3} onClick={p.setCols.bind(null, 3)}>3</Button>
          <Button active={p.obj.parts.length === 4} onClick={p.setCols.bind(null, 4)}>4</Button>
        </ButtonGroup>
        <div className="space10"/>
        <SelectLabel id="valign" obj={p.obj} onChange={p.onChange} label="Vertical Align">
          <option value="top">Top</option>
          <option value="middle">Middle</option>
          <option value="bottom">Bottom</option>
        </SelectLabel>
        {
        !this.props.form &&
        <div className="checkbox">
          <label>
            <input id="stack" type="checkbox" checked={p.obj.stack} onChange={p.onChange} /> Stack on Mobile
          </label>
        </div>
        }
        <div className="space20"/>
        <div className="checkbox">
          <label>
            <input id="adjust" type="checkbox" checked={p.adjustWidths} onChange={p.setAdjust} disabled={p.obj.parts.length === 1} /> Adjust Widths
          </label>
        </div>
      </div>
    );
  }

}

class BackgroundPanel extends Component {
  constructor(props) {
    super(props);

    this.state = {
      isUploading: false,
    };
  }

  uploadClick = () => {
    this.props.onChange({target: {id: 'backgroundType', value: 'img'}});
    document.getElementById('bgfile').click();
  }

  handleImage = event => {
    if (event.target.files.length === 0)
      return
    var file = event.target.files[0];

    var props = this.props;

    notify.show("Uploading, please wait...", "success", 5000);

    getImageSize(file, async (width, height) => {
      this.setState({isUploading: true});

      try {
        var ext = file.name.split('.').pop();

        var upload = (await axios({
          method: 'post',
          url: '/api/uploadfile?type=img&ext=' + ext,
          headers: { "Content-Type": `application/octet-stream` },
          data: file
        })).data;

        var url = (await axios.post('/api/imageimport', {
          key: upload.key,
        })).data.url;

        props.onChange({
          target: {
            id: 'backgroundImage',
            value: url,
          }
        });
      } finally {
        this.setState({isUploading: false});
      }
    });
  }

  onSizeChange = event => {
    this.props.onChange({
      target: {
        id: 'backgroundSize',
        value: getvalue(event) ? 'cover': '',
      }
    });
  }

  render() {
    var p = this.props;
    return (
      <div>
        <div className="radio">
          <label>
            <input id="backgroundType" type="radio" value="" checked={!p.obj.backgroundType} onChange={this.props.onChange} /> Transparent
          </label>
        </div>
        <div className="radio">
          <label>
            <input id="backgroundType" type="radio" value="color" checked={p.obj.backgroundType === 'color'} onChange={this.props.onChange} /> Color:
          </label>
        </div>
        <ColorControl color={p.obj.backgroundColor || '#ffffff'} disableAlpha={true} onChangeComplete={p.onColorChange} onClick={() => { this.props.onChange({target: {id: 'backgroundType', value: 'color'}}) }} />
        <div className="radio">
          <label>
            <input id="backgroundType" type="radio" value="img" checked={p.obj.backgroundType === 'img'} onChange={this.props.onChange} /> Image
          </label>
        </div>
        <FormControl id="bgfile" type="file" onChange={this.handleImage} accept="image/*" style={{display: 'none'}}/>
        <Button className="upload-btn" onClick={this.uploadClick} disabled={this.state.isUploading}>Upload...</Button>
        <div className="checkbox">
          <label>
            <input id="backgroundSize" type="checkbox" disabled={p.obj.backgroundType !== 'img'} checked={p.obj.backgroundSize === 'cover'} onChange={this.onSizeChange} /> Stretch Image
          </label>
        </div>
      </div>
    );
  }
}

class SocialPanel extends Component {
  constructor(props) {
    super(props);

    this.state = {
      show: false,
      activeKey: 0,
    };
  }

  onSelect = activeKey => {
    if (activeKey !== null) {
      this.setState({activeKey: activeKey});
    }
  }

  onClose = () => {
    this.setState({show: false});
  }

  onShow = () => {
    this.setState({show: true});
  }

  render() {
    var p = this.props;

    var social = ['Facebook', 'Twitter', 'Instagram', 'Pinterest', 'LinkedIn'];
    var enabledcount = 0;
    social.forEach(s => {
      if (p.obj[s.toLowerCase()]) {
        enabledcount++;
      }
    });

    return (
      <div>
        <Button onClick={this.onShow} style={{padding: '3px 7px', fontSize: '14px'}}>Edit Links</Button>
        <Modal show={this.state.show}>
          <Modal.Header>
            <Modal.Title>
              Edit Social Links
            </Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <PanelGroup accordion id="edit-accordion" activeKey={this.state.activeKey} onSelect={this.onSelect}>
              {
                _.map(social, (s, i) => {
                  var sl = s.toLowerCase();
                  return (
                    <Panel key={s} eventKey={i}>
                      <Panel.Heading className="form-inline">
                        <Panel.Title toggle>
                          {s}
                          <Toggle
                            checked={p.obj[sl]}
                            id={sl}
                            onChange={p.onChange}
                            disabled={p.obj[sl] && enabledcount === 1}
                            className="pull-right"
                          />
                        </Panel.Title>
                      </Panel.Heading>
                      <Panel.Body collapsible>
                        <FormControlLabel id={sl + 'Link'} obj={p.obj} label="Link" onChange={p.onChange} />
                        <div className="space10" />
                        <FormControlLabel id={sl + 'Label'} obj={p.obj} label="Label" onChange={p.onChange} />
                      </Panel.Body>
                    </Panel>
                  );
                })
              }
            </PanelGroup>
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={this.onClose} bsStyle="primary">Close</Button>
          </Modal.Footer>
        </Modal>
        <CheckboxLabel id="labels" obj={p.obj} label="Show Labels" onChange={p.onChange}/>
        <SelectLabel id="layout" obj={p.obj} label="Layout" onChange={p.onChange}>
          <option value="horizontal">Horizontal</option>
          <option value="vertical">Vertical</option>
        </SelectLabel>
        <div className="space10"/>
        <div className="radio">
          <label>
            <input id="iconColor" type="radio" value="default" checked={p.obj.iconColor === 'default'} onChange={this.props.onChange} /> Default
          </label>
        </div>
        <div className="radio">
          <label>
            <input id="iconColor" type="radio" value="custom" checked={p.obj.iconColor === 'custom'} onChange={this.props.onChange} /> Custom:
          </label>
        </div>
        <ColorControl color={p.obj['iconCustom']} disabled={p.obj.iconColor !== 'custom'} disableAlpha={true} onChangeComplete={p.onColorChange}/>
      </div>
    );
  }
}

class WidthPanel extends Component {
  render() {
    var p = this.props;
    return (
      <div>
        <div className="radio" style={{marginTop: 0}}>
          <label>
            <input id="bodyType" type="radio" value="fixed" checked={p.obj.bodyType === 'fixed'} onChange={p.onChange} /> Fixed Width
          </label>
        </div>
        <FormControlLabel id="bodyWidth" obj={p.obj} disabled={p.obj.bodyType !== 'fixed'} type="number" min="100" onChange={p.onChange} width="75" />
        <div className="radio">
          <label>
            <input id="bodyType" type="radio" value="full" checked={p.obj.bodyType === 'full'} onChange={p.onChange} /> Full Width
          </label>
        </div>
      </div>
    );
  }
}

class BorderPanel extends Component {
  render() {
    var p = this.props;
    return (
      <div>
        <SelectLabel id="borderStyle" obj={p.obj} label="Border Style" onChange={p.onChange}>
          <option value="none">None</option>
          <option value="solid">Solid</option>
          <option value="dashed">Dashed</option>
          <option value="dotted">Dotted</option>
          <option value="double">Double</option>
          <option value="groove">Groove</option>
          <option value="ridge">Ridge</option>
          <option value="inset">Inset</option>
          <option value="outset">Outset</option>
        </SelectLabel>
        <div className="space10"/>
        <FormControlLabel groupStyle={{display: 'inline-block'}} id="borderWidth" obj={p.obj} label="Width" type="number" min="0" onChange={p.onChange} width="55" />
        <FormControlLabel groupStyle={{display: 'inline-block', marginLeft: '4px'}} id="borderRadius" obj={p.obj} label="Radius" type="number" min="0" onChange={p.onChange} width="55" />
        <div className="space10"/>
        <ColorControl color={p.obj['borderColor']} disableAlpha={true} onChangeComplete={p.onColorChange}/>
      </div>
    );
  }
}

class InputPanel extends Component {
  render() {
    var p = this.props;
    return (
      <div>
        <ControlLabel>Field</ControlLabel>
        <Select2
          id="field"
          value={p.obj.field}
          onChange={p.onChange}
          data={_.uniq([p.obj.field].concat(p.fields).concat(['Email', 'First Name']))}
          style={{width: '135px'}}
          options={{
            tags: true,
            placeholder: '',
          }}
        />
        <div className="space10"/>
        <FormControlLabel id="placeholder" obj={p.obj} label="Label" onChange={p.onChange} style={{width:'100%'}} />
        <div className="space10"/>
        <SelectLabel id="inputType" obj={p.obj} label="Type" onChange={p.onChange}>
          <option value="email">Email</option>
          <option value="number">Number</option>
          <option value="password">Password</option>
          <option value="tel">Phone</option>
          <option value="text">Text</option>
          <option value="url">URL</option>
        </SelectLabel>
        <div className="space10"/>
        <CheckboxLabel id="required" obj={p.obj} label="Required" onChange={p.onChange}/>
      </div>
    );
  }
}

class InnerPartDisplay extends Component {
  render() {
    const {selected, selectedCol, disabled, toolbar, panels, displayOnly, onBorderSelect, popupToolbarLeft, isInCol, noDrag, children} = this.props;

    if (displayOnly)
      return children;

    var usepanels = panels;
    if (isInCol) {
      usepanels = _.clone(panels);
      usepanels.pop();
    }

    return (
      selected && selectedCol === null ?
        <div>
          <div className="properties">
            <PopupToolbar panels={usepanels} onBorderSelect={onBorderSelect} top={isInCol?0:15} left={popupToolbarLeft} form={this.props.form} />
            {toolbar}
            {children}
          </div>
        </div>
      :
        <div draggable={!disabled && !noDrag}>
          {children}
        </div>
    );
  }
}

class Wrapper extends Component {
  render() {
    var style = this.props.style || {};
    style.borderCollapse = 'collapse';
    style.verticalAlign = 'top';

    var inner = this.props.children;
    if (this.props.center) {
      inner = <DivTable center={true}>{inner}</DivTable>;
    }

    var outerStyle;
    if (this.props.isInCol) {
      outerStyle = {padding: 0, verticalAlign: 'top', textAlign: 'left', borderSpacing: 0, borderCollapse: 'collapse', width: '100%'};
    } else {
      outerStyle = _.extend(this.props.outerStyle, {padding: 0, verticalAlign: 'top', textAlign: 'left', borderSpacing: 0, borderCollapse: 'collapse'});
    }

    return (
      <table className="wrapper" style={outerStyle}>
        <tbody>
          <tr style={{padding: 0, verticalAlign: 'top'}}>
            <td className="wrapper-inner" style={{position: 'relative', padding: 0, verticalAlign: 'top', textAlign: 'left'}}>
              <DivTable style={style}>
                {inner}
              </DivTable>
            </td>
          </tr>
        </tbody>
      </table>
    );
  }
}

class InvisiblePartDisplay extends Component {
  render() {
    if (this.props.displayOnly) {
      return null;
    } else {
      return <div />
    }
  }
}

class ImagePartDisplay extends Component {
  constructor(props) {
    super(props);

    this.state = {
      isUploading: false,
      stockModal: false,
      stockSearch: '',
      stockType: 'all',
      stockPage: 1,
      stockImages: null,
      pages: [1],
      showZoom: null,
    }

    this._reloadStock = _.debounce(this.reloadStock, 500);
  }

  handleModalChange = event => {
    var id = event.target.id;
    this.setState({[id]: getvalue(event)}, () => { this._reloadStock(id) });
  }

  reloadStock = prop => {
    var p = {stockImages: null, showZoom: null};
    if (prop !== 'stockPage') {
      p.stockPage = 1;
    }

    this.setState(p, async () => {
      var data = (await axios.post('/api/stock/search', {
        image_type: this.state.stockType,
        q: this.state.stockSearch,
        page: this.state.stockPage.toString(),
      })).data;

      var total = data.totalHits;

      var pages = [];
      for (var i = 0; i < Math.floor(total/15)+1; i++) {
        pages.push(i+1);
      }

      this.setState({stockImages: data.hits, pages: pages});
    });
  }

  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  onAlignLeft = () => {
    this.props.updatePart(this.props.id, {align: 'left'});
  }
  onAlignCenter = () => {
    this.props.updatePart(this.props.id, {align: 'center'});
  }
  onAlignRight = () => {
    this.props.updatePart(this.props.id, {align: 'right'});
  }

  uploadClick = () => {
    document.getElementById('file').click();
  }

  stockClick = () => {
    this.setState({stockModal: true, showZoom: null}, this._reloadStock);
  }

  doUpload = async (file, width, height) => {
    this.setState({isUploading: true});

    try {
      var ext = file.name.split('.').pop();


      var upload = (await axios({
        method: 'post',
        url: '/api/uploadfile?type=img&ext=' + ext,
        headers: { "Content-Type": `application/octet-stream` },
        data: file
      })).data;

      var url = (await axios.post('/api/imageimport', {
        key: upload.key,
      })).data.url;

      this.props.updatePart(this.props.id, {width: width,
                                       height: height,
                                       src: url});
    } finally {
      this.setState({isUploading: false});
    }
  }

  handleImage = event => {
    if (event.target.files.length === 0)
      return
    var file = event.target.files[0];

    notify.show("Uploading, please wait...", "success", 5000);

    getImageSize(file, async (width, height) => {
      await this.doUpload(file, width, height);
    });
  }

  onLink = () => {
    return {url: this.props.link};
  }

  onLinkConfirm = urlValue => {
    this.props.updatePart(this.props.id, {link: urlValue});
  }

  onUnlink = () => {
    this.props.updatePart(this.props.id, {link: ''});
  }

  showZoom = i => {
    this.setState({showZoom: i});
  }

  hideZoom = () => {
    this.setState({showZoom: null});
  }

  stockSelect = async () => {
    var i = this.state.showZoom;

    var data = (await axios.get(i.webformatURL, {responseType: 'blob'})).data;

    var s = i.webformatURL.split('/');

    data.name = s[s.length-1];

    await this.doUpload(data, i.webformatWidth, i.webformatHeight);

    this.setState({showZoom: null, stockModal: false});
  }

  render() {
    var p = this.props;
    const style = this.props.getPartStyles(p);
    var {selected, selectedCol, align, scale, width, height, src, link, displayOnly, imgWidth, bodyType, bodyWidth} = style;
    const f = this.props.getPartStylesDisplay(p);

    var imgstyle = {
      outline: 'none',
      textDecoration: 'none',
      msInterpolationMode: 'bicubic',
      maxWidth: '100%',
      clear: 'both',
      display: 'block',
      border: 'none',
    };

    if (!this.props.isInCol && bodyType === 'fixed') {
      imgWidth = bodyWidth;
    }

    if (width !== null) { 
      if (imgWidth) {
        var origwidth = width;
        var borderwidth = 0;
        if (!_.isUndefined(f.borderStyle) && f.borderStyle !== 'none') {
          borderwidth = style.borderWidth; 
        }
        imgWidth -= (style.marginLeft + style.marginRight + style.paddingLeft + style.paddingRight + borderwidth*2);
        if (imgWidth < width) {
          width = imgWidth;
        }
        width = Math.trunc(width * (scale / 100.0));
        height = Math.trunc((width / origwidth) * height);
        imgstyle.width = width + 'px';
        imgstyle.height = 'auto';
      } else {
        imgstyle.width = scale + '%'; 
        imgstyle.height = 'auto';
        width = scale + '%';
        height = scale + '%';
      }
    } else {
      width = 64;
      height = 91;
      imgstyle.width = '64px';
      imgstyle.height = 'auto';
    }

    var center = false;
    if (f.align === 'left') {
      imgstyle.textAlign = 'left';
      imgstyle.float = 'left';
    } else if (f.align === 'right') {
      imgstyle.textAlign = 'right';
      imgstyle.float = 'right';
    } else {
      imgstyle.textAlign = 'center';
      imgstyle.float = 'none';
      imgstyle.margin = '0 auto';
      center = true;
    }

    var imgsrc = src;
    if (displayOnly && !imgsrc) {
      imgsrc = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
    }

    const types = {
      all: 'All Images',
      photo: 'Photos',
      vector: 'Vector Graphics',
      illustration: 'Illustrations',
    };

    var inner = (
      <Wrapper style={{
           textAlign: f.align,
           ...borderStyle(f),
           ...paddingStyle(f),
           ...marginStyle(f),
           ...backgroundStyle(f),
      }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol} center={center}>
        {
          imgsrc ?
            (link && (displayOnly || this.props.disabled)) ?
              <a href={link} target="_blank" onDragStart={e=>e.preventDefault()}><img src={imgsrc} alt="" style={imgstyle} width={width} height={height} /></a>
            :
              <img src={imgsrc} alt="" style={imgstyle} width={width} height={height} onDragStart={e=>e.preventDefault()}/>
          :
            <img src="/img/dnd/placeholder_image.png" alt="placeholder" style={{height: '128px'}} onDragStart={e => e.preventDefault()}/>
        }
        <p style={{clear:'both', margin: 0, lineHeight: 0, padding: 0}}/>
        {
          this.state.stockModal && selected && !displayOnly &&
            <Modal show={true} size="lg" id="stock-modal">
              <Modal.Header>
                <Modal.Title>Import Stock Image</Modal.Title>
              </Modal.Header>
              <Modal.Body>
              <InputGroup>
                <FormControl type="text" id="stockSearch" placeholder="Enter search string, e.g. plants, animals" onChange={this.handleModalChange} value={this.state.handleModalChange} />
                <DropdownButton componentClass={InputGroup.Button} id="stock-button" title={types[this.state.stockType]}>
                  <MenuItem onClick={this.handleModalChange.bind(null, {target:{id: 'stockType', value: 'all'}})}>All Images</MenuItem>
                  <MenuItem onClick={this.handleModalChange.bind(null, {target:{id: 'stockType', value: 'photo'}})}>Photos</MenuItem>
                  <MenuItem onClick={this.handleModalChange.bind(null, {target:{id: 'stockType', value: 'vector'}})}>Vector Graphics</MenuItem>
                  <MenuItem onClick={this.handleModalChange.bind(null, {target:{id: 'stockType', value: 'illustration'}})}>Illustrations</MenuItem>
                </DropdownButton>
              </InputGroup>
              <div id="stock-image-gallery">
              {
                this.state.stockImages === null ?
                  <LoaderIcon />
                :
                  <div className="text-left">
                  {
                    _.map(this.state.stockImages, i => (
                      <div className="stock-image-box" key={i.id}>
                        <img key={i.id} src={i.previewURL} alt={i.tags} onClick={this.showZoom.bind(null, i)} />
                      </div>
                    ))
                  }
                  </div>
              }
              {
                this.state.showZoom !== null &&
                  <div className="stock-zoom-box">
                    <div className="stock-unzoom-btn" onClick={() => this.setState({showZoom: null})}>
                      <i className="fa fa-remove" />
                    </div>
                    <img className="zoom-img" src={this.state.showZoom.webformatURL} alt={this.state.showZoom.tags} />
                  </div>
              }
              </div>
              <div className="select-div">
                <b>Page:</b>{' '}
                <FormControl id="stockPage" componentClass="select" onChange={this.handleModalChange} value={this.state.stockPage} disabled={this.state.stockImages === null}>
                {
                  _.map(this.state.pages, p => <option key={p} value={p}>{p}</option>)
                }
                </FormControl>
              </div>
              <p>Powered by <a target="_blank" rel="noreferrer noopener" href="https://pixabay.com/">Pixabay</a></p>
              </Modal.Body>
              <Modal.Footer>
                <LoaderButton
                  bsStyle="primary"
                  text="Import Selected"
                  style={{display:this.state.showZoom === null?'none':undefined}}
                  loadingText="Importing..."
                  onClick={this.stockSelect}
                />
                <Button onClick={() => this.setState({stockModal: false})}>Cancel</Button>
              </Modal.Footer>
            </Modal>
        }
      </Wrapper>
    );

    return (
      <InnerPartDisplay form={this.props.form} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} onBorderSelect={this.props.onBorderSelect} popupToolbarLeft={this.props.popupToolbarLeft} isInCol={this.props.isInCol} toolbar={
        <EditToolbar {...style} isInCol={this.props.isInCol}>
          <FormControl id="file" type="file" onChange={this.handleImage} accept="image/*" style={{display: 'none'}}/>
          <ButtonGroup>
            <Button onClick={this.uploadClick} disabled={this.state.isUploading}>Upload...</Button>
          </ButtonGroup>
          <ButtonGroup>
            <Button onClick={this.stockClick} disabled={this.state.isUploading}>Free Stock Art...</Button>
          </ButtonGroup>
          <ButtonGroup>
            <LinkPopup onPopup={this.onLink} onConfirm={this.onLinkConfirm} nocolor />
            <Button disabled={!link} onClick={this.onUnlink}><i className="fa fa-unlink"></i></Button>
          </ButtonGroup>
          <ButtonGroup>
            <Button onClick={this.onAlignLeft} active={align==='left'}><Glyphicon glyph="align-left"/></Button>
            <Button onClick={this.onAlignCenter} active={align==='center'}><Glyphicon glyph="align-center"/></Button>
            <Button onClick={this.onAlignRight} active={align==='right'}><Glyphicon glyph="align-right"/></Button>
          </ButtonGroup>
          <ButtonGroup>
            <FormControlPopup
              id="scale"
              obj={p}
              text="Scale %"
              onChange={this.handleChange}
              type="number"
              min="1"
              max="100"
              style={{width:'75px'}}
            />
          </ButtonGroup>
        </EditToolbar>
      } panels={[
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
        {name: 'Border', body: <BorderPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
        {name: 'Width', body: <WidthPanel obj={style} onChange={this.handleChange} /> }
      ]}>
        {
          (!selected && !displayOnly && !this.props.disabled) ?
            <div>
              {inner}
            </div>
          :
            inner
        }
      </InnerPartDisplay>
    );
  }
}

const { styles, customStyleFn, exporter } = createStyles(['font-family', 'font-size', 'color']);

function withPartStyle(C, style) {
  return ({...props}) => (
    <C style={style} {...props} /> 
  );
}

class TextPartDisplay extends Component {
  constructor(props) {
    super(props);

    this.state = {
      editorState: this.getEditorState(props),
    };

    this.editorRef = null;
  }

  getEditorState(props) {
    const style = props.getPartStyles(props);

    const decorator = new CompositeDecorator([
      {
        strategy: findLinkEntities,
        component: withPartStyle(Link, style),
      }
    ]);

    return EditorState.createWithContent(convertFromRaw(props.content), decorator);
  }

  componentWillReceiveProps(props) {
    if (this.props.designType && props.designType && this.props.designType !== props.designType) {
      this.setState({editorState: this.getEditorState(props)});
    }
  }

  handleChange = (editorState, cb) => {
    this.setState({editorState: editorState});
    const content = convertToRaw(editorState.getCurrentContent());
    this.props.updatePart(this.props.id, {content: content}, cb);
  }

  handlePropChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  onLink = () => {
    const {editorState} = this.state;
    const contentState = editorState.getCurrentContent();
    const startKey = editorState.getSelection().getStartKey();
    const startOffset = editorState.getSelection().getStartOffset();
    const blockWithLinkAtBeginning = contentState.getBlockForKey(startKey);
    const linkKey = blockWithLinkAtBeginning.getEntityAt(startOffset);

    const style = this.props.getPartStyles(this.props);

    let url = '', color = style.linkColor, underline = style.linkUnderline;
    if (linkKey) {
      const linkInstance = contentState.getEntity(linkKey);
      const data = linkInstance.getData();
      url = data.url;
      if (!_.isUndefined(data.color)) {
        color = data.color;
      }
      if (!_.isUndefined(data.underline)) {
        underline = data.underline;
      }
    }

    return {url: url, color: color, underline: underline};
  }

  onLinkConfirm = (urlValue, color, underline) => {
    const style = this.props.getPartStyles(this.props);

    if (color === style.linkColor) {
      color = undefined;
    }
    if (underline === style.linkUnderline) {
      underline = undefined;
    }

    const {editorState} = this.state;
    const contentState = editorState.getCurrentContent();
    const contentStateWithEntity = contentState.createEntity(
      'LINK',
      'MUTABLE',
      {url: urlValue, color: color, underline: underline}
    );

    const entityKey = contentStateWithEntity.getLastCreatedEntityKey();
    const newEditorState = EditorState.set(editorState, {currentContent: contentStateWithEntity});
    this.handleChange(RichUtils.toggleLink(newEditorState, newEditorState.getSelection(), entityKey), () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }

  onUnlink = () => {
    const {editorState} = this.state;
    const selection = editorState.getSelection();
    this.handleChange(RichUtils.toggleLink(editorState, selection, null), () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }

  onBold = () => {
    this.handleChange(RichUtils.toggleInlineStyle(this.state.editorState, 'BOLD'), () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }
  onItalic = () => {
    this.handleChange(RichUtils.toggleInlineStyle(this.state.editorState, 'ITALIC'), () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }
  onUnderline = () => {
    this.handleChange(RichUtils.toggleInlineStyle(this.state.editorState, 'UNDERLINE'), () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }
  onStrikethrough = () => {
    this.handleChange(RichUtils.toggleInlineStyle(this.state.editorState, 'STRIKETHROUGH'), () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }

  onAlignLeft = () => {
    this.props.updatePart(this.props.id, {align: 'left'}, () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }
  onAlignCenter = () => {
    this.props.updatePart(this.props.id, {align: 'center'}, () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }
  onAlignRight = () => {
    this.props.updatePart(this.props.id, {align: 'right'}, () => {
      if (this.editorRef) {
        this.editorRef.focus();
      }
    });
  }

  insertText = txt => {
    const {editorState} = this.state;
    this.handleChange(EditorState.push(editorState, Modifier.replaceText(editorState.getCurrentContent(), editorState.getSelection(), txt), 'insert-variable'));
  }

  setFont = font => {
    this.handleChange(styles.fontFamily.toggle(this.state.editorState, font));
  }
  setFontSize = event => {
    this.handleChange(styles.fontSize.add(styles.fontSize.remove(this.state.editorState), getvalue(event) + 'px'));
  }
  setColor = color => {
    this.handleChange(styles.color.add(styles.color.remove(this.state.editorState), color.hex));
  }

  handlePastedText = (text, html, state) => {
    this.handleChange(EditorState.push(state, Modifier.replaceText(state.getCurrentContent(), state.getSelection(), text), 'paste'));
    return 'handled';
  }

  linkExporter = (style, entity) => {
    if (entity.get('type').toLowerCase() === 'link') {
      let {url, color, underline} = entity.getData();

      if (_.isUndefined(color)) {
        color = style.linkColor;
      }
      if (_.isUndefined(underline)) {
        underline = style.linkUnderline;
      }
      return {
        element: 'a',
        attributes: {
          href: url,
          target: '_blank',
        },
        style: {
          color: color,
          textDecoration: underline?'underline':'none',
        }
      };
    }
  }

  render() {
    const style = this.props.getPartStyles(this.props);
    var {selected, selectedCol, align, displayOnly} = style;
    const f = this.props.getPartStylesDisplay(this.props);

    var transactional = this.props.transactional;

    var currentStyle = this.state.editorState.getCurrentInlineStyle();

    var fontFamily = styles.fontFamily.current(this.state.editorState) || style.fontFamily;
    var color      = styles.color.current(this.state.editorState) || style.color;
    var fontSize   = { fontSize: styles.fontSize.current(this.state.editorState) || style.fontSize };

    if (_.isString(fontSize.fontSize) && /px$/.test(fontSize.fontSize)) {
      fontSize.fontSize = parseInt(fontSize.fontSize.substring(0, fontSize.fontSize.length - 2), 10);
    }

    var selection = this.state.editorState.getSelection()

    var nosel = selection.getStartOffset() === selection.getEndOffset();

    var inlineStyles = exporter(this.state.editorState);

    const decorator = new CompositeDecorator([
      {
        strategy: findLinkEntities,
        component: withPartStyle(Link, style),
      }
    ]);
    var stateWithLinks = EditorState.set(this.state.editorState, {decorator: decorator});

    return (
      <InnerPartDisplay form={this.props.form} noDrag={this.props.footer} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} selected={selected} selectedCol={selectedCol} disabled={this.props.disabled} displayOnly={displayOnly} toolbar={
        <EditToolbar {...style} isInCol={this.props.isInCol}>
          <ButtonGroup>
            <LinkPopup onPopup={this.onLink} onConfirm={this.onLinkConfirm}
              disabled={stateWithLinks.getSelection().isCollapsed()} />
            <Button disabled={stateWithLinks.getSelection().isCollapsed()} onClick={this.onUnlink}><i className="fa fa-unlink"></i></Button>
          </ButtonGroup>
          <ButtonGroup>
            <Button disabled={nosel} onClick={this.onBold} active={currentStyle.has('BOLD')}><Glyphicon glyph="bold"/></Button>
            <Button disabled={nosel} onClick={this.onItalic} active={currentStyle.has('ITALIC')}><Glyphicon glyph="italic"/></Button>
            <Button disabled={nosel} onClick={this.onUnderline} active={currentStyle.has('UNDERLINE')}><span className="fa fa-underline"></span></Button>
            <Button disabled={nosel} onClick={this.onStrikethrough} active={currentStyle.has('STRIKETHROUGH')}><span className="fa fa-strikethrough"></span></Button>
            <Dropdown id="fonts" disabled={nosel} onToggle={open => !open && this.editorRef && setTimeout(() => this.editorRef.focus())}>
              <Dropdown.Toggle>
                <span className="fa fa-font"></span>
              </Dropdown.Toggle>
              <Dropdown.Menu>
              {
                _.map(fonts, f => <MenuItem key={f} style={{fontFamily: f}} active={fontFamily === f} onClick={this.setFont.bind(null, f)}>{f}</MenuItem>)
              }
              </Dropdown.Menu>
            </Dropdown>
            <FormControlPopup disabled={nosel} id="fontSize" label="Size" obj={fontSize} text={<span className="fa fa-text-height"></span>} onChange={this.setFontSize} type="number" min="6" max="200" onBlur={ () => {
                if (this.editorRef) {
                  this.editorRef.focus();
                }
              }
            } />
            <ColorPopup disabled={nosel} id="textcolor" type="text" color={color} onChange={this.setColor} onBlur={ () => {
                if (this.editorRef) {
                  this.editorRef.focus();
                }
              }
            } />
          </ButtonGroup>
          <ButtonGroup>
            <FormControlPopup id="lineHeight" label="Line Height" obj={style} text={<span className="fa fa-arrows-v"></span>} onChange={this.handlePropChange} type="number" min="0" step="0.1" style={{width: '75px'}} onBlur={ () => {
                if (this.editorRef) {
                  this.editorRef.focus();
                }
              }
            } />
          </ButtonGroup>
          <ButtonGroup>
            <Button onClick={this.onAlignLeft} active={align==='left'}><Glyphicon glyph="align-left"/></Button>
            <Button onClick={this.onAlignCenter} active={align==='center'}><Glyphicon glyph="align-center"/></Button>
            <Button onClick={this.onAlignRight} active={align==='right'}><Glyphicon glyph="align-right"/></Button>
          </ButtonGroup>
          {!this.props.form &&
          <ButtonGroup>
            <Dropdown id="variables" onToggle={open => !open && this.editorRef && setTimeout(() => this.editorRef.focus())}>
              <Dropdown.Toggle>
                Personalize
              </Dropdown.Toggle>
              <Dropdown.Menu>
              {
                transactional ?
                  <MenuItem onClick={this.insertText.bind(null, '{{variable}}')}>{'{{'}variable}}</MenuItem>
                :
                _.map(this.props.fields, f => <MenuItem key={f} onClick={this.insertText.bind(null, ' {{' + f + ',default=}}')}>{f}</MenuItem>)
              }
              </Dropdown.Menu>
            </Dropdown>
          </ButtonGroup>
          }
        </EditToolbar>
      } panels={[
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handlePropChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handlePropChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handlePropChange} /> },
        {name: 'Border', body: <BorderPanel obj={style} onChange={this.handlePropChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
        {name: 'Width', body: <WidthPanel obj={style} onChange={this.handlePropChange} /> }
      ]}>
        <Wrapper style={{color: f.color,
                     fontSize: f.fontSize,
                     fontFamily: f.fontFamily,
                     lineHeight: f.lineHeight,
                     ...marginStyle(f),
                     ...paddingStyle(f),
                     ...borderStyle(f),
                     ...backgroundStyle(f),
                     }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}>
          {
            displayOnly || this.props.disabled ?
              <DivTable style={{textAlign:f.align}} innerHTML={{__html: draftStyles(stateToHTML(stateWithLinks.getCurrentContent(), { entityStyleFn: this.linkExporter.bind(null, style), inlineStyles }))}}/>
            :
              <Editor customStyleFn={customStyleFn} editorState={stateWithLinks} onChange={this.handleChange} textAlignment={align} handleDrop={() => 'handled'} ref={r => this.editorRef = r} handlePastedText={this.handlePastedText} />
          }
        </Wrapper>
      </InnerPartDisplay>
    );
  }
}

class ColumnPlaceholder extends Component {
  render() {
    return (
      <div className="column-placeholder" ref={r => this._ref = r} onClick={this.props.togglePopup}>
        { this.props.highlight &&
          <div className="ph-highlight"/>
        }
        {
          this.props.hover && !this.props.showPopup &&
          <div className="hover-overlay hover-pink" />
        }
        <img onDragStart={e => e.preventDefault()} src={'/img/dnd/placeholder_columns_' + this.props.num + '.png'} alt="placeholder" ref={t => this._target = t}/>
        <Overlay placement="bottom" container={this} target={() => ReactDOM.findDOMNode(this._target)} show={this.props.showPopup}>
          <Popover id="newpart-popover" className={this.props.form?"newpart-popover-form":undefined}>
            <Button onClick={this.props.addPart.bind(null, 'Text')}>
              <img src="/img/dnd/Text.png" alt="Text" />
            </Button>
            <Button onClick={this.props.addPart.bind(null, 'Image')}>
              <img src="/img/dnd/Image.png" alt="Img" />
            </Button>
            { !this.props.form &&
            <Button onClick={this.props.addPart.bind(null, 'HTML')}>
              <img src="/img/dnd/HTML.svg" alt="HTML" />
            </Button>
            }
            <Button onClick={this.props.addPart.bind(null, 'Button')}>
              <img src="/img/dnd/Button.png" alt="Button" />
            </Button>
            { this.props.form &&
            <Button onClick={this.props.addPart.bind(null, 'Input')}>
              <img src="/img/dnd/Input.png" alt="Input" />
            </Button>
            }
          </Popover>
        </Overlay>
      </div>
    );
  }
}

class ColumnsPartDisplay extends Component {
  constructor(props) {
    super(props);

    this.state = {
      highlightCol: null,
      highlightColIndex: null,
      hoverPart: null,
      hoverPartIndex: null,
      selectedToolbarTop: null,
      selectedToolbarRight: null,
      showModal: null,
      showModalIndex: null,
      adjustWidths: false,
      placeholderPopup: null,
    };

    if (props.setDragCB) {
      props.setDragCB(this.props.id, this.dragCB);
    }

    this._refs = {};
  }

  onMouseLeave = event => {
    this.setState({hoverPart: null, hoverPartIndex: null});
  }

  onMouseMove = event => {
    if (this.props.disabled) {
      return;
    }

    if (event.target.className === 'arrow' || event.target.className === 'popover-content') {
      return;
    }

    if (this.props.selectedPart !== null && this.props.selectedCol !== null) {
      return;
    }

    var y = event.clientY;
    var x = event.clientX;

    var colnum = null, index = null;

    for (var c = 0; c < this.props.parts.length; c++) {
      var p = this.props.parts[c];
      if (_.isArray(p) && p.length > 0) {
        for (var i = 0; i < p.length; i++) {
          let rect = this._refs[c+","+i]._ref.getBoundingClientRect();
          if (x >= rect.left && x <= rect.right &&
              y >= rect.top  && y <= rect.bottom) {
            colnum = c;
            index = i;
            break;
          }
        }
        if (colnum !== null) {
          break;
        }
      } else {
        let rect = this._refs[c+",0"]._ref.getBoundingClientRect();
        if (x >= rect.left && x <= rect.right &&
            y >= rect.top  && y <= rect.bottom) {
          colnum = c;
          index = 0;
          break;
        }
      }
    }

    this.setState({hoverPart: colnum, hoverPartIndex: index});
  }

  dragCB = (event, drop) => {
    if (event === null) {
      this.setState({highlightCol: null, highlightColIndex: null});
      return;
    }

    var y = event.clientY;
    var x = event.clientX;

    var colnum = null, index = null;

    for (var c = 0; c < this.props.parts.length; c++) {
      var p = this.props.parts[c];
      if (_.isArray(p) && p.length > 0) {
        for (var i = 0; i < p.length; i++) {
          let rect = this._refs[c+","+i]._ref.getBoundingClientRect();
          if (x >= rect.left && x <= rect.right &&
              y >= rect.top  && y <= rect.bottom) {
            colnum = c;
            index = i;
            if (y - rect.top > rect.height/2) {
              index++;
            }
            break;
          }
          if (colnum !== null) {
            break;
          }
        }
      } else {
        let rect = this._refs[c+",0"]._ref.getBoundingClientRect();
        if (x >= rect.left && x <= rect.right &&
            y >= rect.top  && y <= rect.bottom) {
          colnum = c;
          index = 0;
          if (y - rect.top > rect.height/2) {
            index++;
          }
          break;
        }
      }
    }

    var hl = null, hlindex = null;
    if (!drop && colnum !== null) {
      hl = colnum;
      hlindex = index;
    }
    this.setState({highlightCol: hl, highlightColIndex: hlindex});

    return {colnum:colnum, colindex:index};
  }

  partMenuPlacement(colnum, index) {
    var mainrect = this._mainRef.getBoundingClientRect();
    var rect = this._refs[colnum + "," + index]._ref.getBoundingClientRect();
    return {top: (rect.top - mainrect.top) + 2, right: (mainrect.right - rect.right) - 53};
  }

  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  updatePart = (colnum, colindex, id, pr, cb) => {
    const style = this.props.getPartStyles(this.props);

    var newparts = _.map(this.props.parts, (part, i) => {
      if (i !== colnum) {
        return part;
      }

      if (_.isArray(part)) {
        return _.map(part, (subpart, index) => {
          if (index !== colindex) {
            return subpart;
          }
          var d = {$unset: []};
          for (var p in pr) {
            if (canInherit[p] && pr[p] === style[p]) {
              d.$unset.push(p);
            } else {
              d[p] = {$set: pr[p]};
            }
          }
          if (d.$unset.length === 0) {
            delete(d.$unset);
          }
          var newPart = update(subpart, d);
          newPart.html = this.props.getDisplayHTML(newPart);
          return newPart;
        });
      } else {
        var d = {$unset: []};
        for (var p in pr) {
          if (canInherit[p] && pr[p] === style[p]) {
            d.$unset.push(p);
          } else {
            d[p] = {$set: pr[p]};
          }
        }
        if (d.$unset.length === 0) {
          delete(d.$unset);
        }
        var newPart = update(part, d);
        newPart.html = this.props.getDisplayHTML(newPart);
        return newPart;
      }
    });

    this.props.updatePart(this.props.id, {parts: newparts}, cb);
  }

  removePart = () => {
    this.setState({hoverPart: null, hoverPartIndex: null, showModal: this.props.selectedCol, showModalIndex: this.props.selectedColIndex});
  }

  confirmClicked = yes => {
    var selcol = this.state.showModal;
    var selind = this.state.showModalIndex;
    this.setState({showModal: null, showModalIndex: null}, () => {
      if (yes) {
        this.props.clearSelection(() => {
          var newparts;
          if (_.isArray(this.props.parts[selcol])) {
            newparts = update(this.props.parts, {[selcol]: {$splice: [[selind, 1]]}});
            this.props.updatePart(this.props.id, {parts: newparts});
          } else {
            newparts = update(this.props.parts, {[selcol]: {$set: null}});
            this.props.updatePart(this.props.id, {parts: newparts});
          }
        }); 
      }
    });
  }

  setSelection = (colnum, index) => {
    if (this.props.selectedPart === this.props.index && this.props.selectedCol === colnum && this.props.selectedColIndex === index) {
      this.setState({selectedToolbarTop: null, selectedToolbarRight: null, hoverPart: colnum, hoverPartIndex: index}, () => {
        this.props.setSelection(this.props.index, colnum, index);
      });
    } else {
      var {top, right} = this.partMenuPlacement(colnum, index);
      this.setState({selectedToolbarTop: top, selectedToolbarRight: right, hoverPart: colnum, hoverPartIndex: index}, () => {
        this.props.setSelection(this.props.index, colnum, index);
      });
    }
  }

  setCols = num => {
    if (num === this.props.parts.length) {
      return;
    }
    var newparts;
    if (num > this.props.parts.length) {
      newparts = _.clone(this.props.parts);
    } else {
      newparts = _.filter(this.props.parts, p => p && (!_.isArray(p) || p.length));
    }
    while (num > newparts.length) {
      newparts.push([]);
    }
    var coldiv = 12/newparts.length;
    var newwidths = [];
    while (newwidths.length < newparts.length) {
      newwidths.push(coldiv);
    }

    this.props.updatePart(this.props.id, {parts: newparts, widths: newwidths});
  }

  setAdjust = event => {
    this.setState({adjustWidths: getvalue(event)});
  }

  columnLeft = colnum => {
    if (this.props.widths[colnum] <= 2) {
      return;
    }
    this.props.updatePart(this.props.id, {widths: update(this.props.widths, {[colnum]:   {$set: this.props.widths[colnum] - 1},
                                                                             [colnum+1]: {$set: this.props.widths[colnum+1] + 1}})});
  }

  columnRight = colnum => {
    if (this.props.widths[colnum+1] <= 2) {
      return;
    }
    this.props.updatePart(this.props.id, {widths: update(this.props.widths, {[colnum]:   {$set: this.props.widths[colnum] + 1},
                                                                             [colnum+1]: {$set: this.props.widths[colnum+1] - 1}})});
  }

  togglePopup = (colnum, event) => {
    event.stopPropagation();

    var cb = () => {
      if (!this.props.selected) {
        this.props.setSelection(this.props.index, null, null);
      }
    };

    if (this.state.placeholderPopup === colnum) {
      this.setState({placeholderPopup: null}, cb);
    } else {
      this.setState({placeholderPopup: colnum}, cb);
    }
  }

  addPart = (colnum, part) => {
    var newPart = createPart(this.props.form, true, part);
    newPart.html = this.props.getDisplayHTML(newPart);
    this.props.updatePart(this.props.id, {
      parts: update(this.props.parts, {[colnum]: {$set: [newPart]}}),
    });
  }

  render() {
    var p = this.props;
    const style = p.getPartStyles(p);
    const {selected, selectedCol, displayOnly} = style;
    const f = p.getPartStylesDisplay(p);

    var compcount = _.filter(this.props.parts, p => p && p.length).length;

    return (
      <InnerPartDisplay form={this.props.form} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} disabled={this.props.disabled} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} noDrag={true}
        panels={[
        {name: 'Columns', body: <ColumnsPanel obj={style} compCount={compcount} adjustWidths={this.state.adjustWidths} setAdjust={this.setAdjust} setCols={this.setCols} onChange={this.handleChange} form={this.props.form} /> },
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
        {name: 'Border', body: <BorderPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
        {name: 'Width', body: <WidthPanel obj={style} onChange={this.handleChange} /> }
      ]}>
        <Wrapper style={{
            ...marginStyle(f),
            ...borderStyle(f),
            ...backgroundStyle(f),
          }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}
        >
          {
            this.props.selected && this.props.selectedCol !== null && !displayOnly &&
              <PartToolbar
                top={this.state.selectedToolbarTop}
                right={this.state.selectedToolbarRight}
                remove={this.removePart}
                removeOnly={true}
              />
          }
          <table className="row" style={{
            padding: 0, borderSpacing: 0, borderCollapse: 'separate',
            width: '100%', position: 'relative', marginLeft: 0, marginRight: 0,
          }} ref={r => {this._mainRef = r}}>
            {
              this.state.adjustWidths && selected &&
              _.filter(_.map(this.props.parts, (p, colnum) => {
                if (colnum === this.props.parts.length - 1)
                  return null;
                var offset = 0;
                for (var i = 0; i <= colnum; i++) {
                  var coldiv = this.props.widths[i];
                  if (style.bodyType === 'fixed') {
                    offset += ((style.bodyWidth - style.marginLeft - style.marginRight) * (coldiv/12.0));
                  } else {
                    offset += (100 * (coldiv/12.0));
                  }
                }
                return (
                  <thead key={colnum} className="column-line" style={{
                    left: offset + (style.bodyType === 'fixed'?'px':'%'),
                  }}>
                    <tr>
                      <th>
                        <Button disabled={this.props.widths[colnum] <= 2} onClick={this.columnLeft.bind(null, colnum)} className="column-left-button" bsSize="xs"><i className="fa fa-chevron-left"/></Button>
                        <Button disabled={this.props.widths[colnum+1] <= 2} onClick={this.columnRight.bind(null, colnum)} className="column-right-button" bsSize="xs"><i className="fa fa-chevron-right"/></Button>
                      </th>
                    </tr>
                  </thead>
                );
              }), x => x)
            }
            <tbody>
              <tr onMouseMove={this.onMouseMove} onMouseLeave={this.onMouseLeave} style={{padding: 0}}>
                {
                  _.map(this.props.parts, (p, colnum) => {
                    var firstlast = '';
                    if (colnum === 0) {
                      firstlast = 'first';
                    } else if (colnum === this.props.parts.length - 1) {
                      firstlast = 'last';
                    }
                    var colwidth;
                    var coldiv = this.props.widths[colnum];
                    var imgwidth = undefined;
                    if (style.bodyType === 'fixed') {
                      colwidth = ((style.bodyWidth - style.marginLeft - style.marginRight) * (coldiv/12.0));
                      imgwidth = Math.trunc(colwidth - style.paddingLeft/2 - style.paddingRight/2);
                      colwidth += 'px';
                    } else {
                      colwidth = (100 * (coldiv/12.0)) + '%';
                    }
                    return (
                      <th className={`${this.props.stack?'small-12':''} large-${coldiv} ${firstlast} columns`} key={colnum} style={{
                        ...paddingStyle(f, true),
                        margin: '0 auto',
                        textAlign: f.align,
                        width: colwidth,
                        fontWeight: 400,
                        verticalAlign: style.valign,
                        position: displayOnly?undefined:'relative',
                      }}>
                        { !displayOnly && (p === null || (_.isArray(p) && p.length === 0)) &&
                          <ColumnPlaceholder num={this.props.parts.length} ref={r => {this._refs[colnum + ",0"] = r}} highlight={this.state.highlightCol === colnum}
                                             addPart={this.addPart.bind(null, colnum)} hover={this.state.hoverPart === colnum && this.props.hover}
                                             form={this.props.form}
                                             togglePopup={this.togglePopup.bind(null, colnum)} showPopup={this.props.selected && this.state.placeholderPopup === colnum} />
                        }
                        {
                          p !== null && 
                            (
                            _.isArray(p) ?
                              _.map(p, (subpart, subindex) => (
                                <PartDisplay key={subpart.id} index={this.props.index} colnum={colnum} colindex={subindex} {...subpart}
                                             fields={this.props.fields}
                                             transactional={this.props.transactional}
                                             form={this.props.form}
                                             designType={this.props.designType}
                                             displayOnly={displayOnly}
                                             updatePart={this.updatePart.bind(null, colnum, subindex)}
                                             getPartStyles={this.props.getPartStyles}
                                             getPartStylesDisplay={this.props.getPartStylesDisplay}
                                             setNextPart={this.props.setNextPart}
                                             disabled={this.props.disabled}
                                             setSelection={this.setSelection}
                                             clearSelection={this.props.clearSelection}
                                             selected={this.props.selected && colnum === this.props.selectedCol && subindex === this.props.selectedColIndex}
                                             selectedCol={null}
                                             selectedColIndex={null}
                                             hover={this.state.hoverPart === colnum && this.state.hoverPartIndex === subindex && this.props.hover && (colnum !== this.props.selectedCol || subindex !== this.props.selectedColIndex)}
                                             hoverPink={true}
                                             popupToolbarLeft={-50}
                                             isInCol={true}
                                             imgWidth={imgwidth}
                                             ref={r => {this._refs[colnum+","+subindex] = r}}
                                             highlight={this.state.highlightCol === colnum && this.state.highlightColIndex === subindex}
                                             highlightBottom={this.state.highlightCol === colnum && this.state.highlightColIndex === (subindex + 1) && p.length === this.state.highlightColIndex}
                                />
                              ))
                            :
                            <PartDisplay index={this.props.index} colnum={colnum} colindex={0} {...p}
                                         fields={this.props.fields}
                                         transactional={this.props.transactional}
                                         form={this.props.form}
                                         designType={this.props.designType}
                                         displayOnly={displayOnly}
                                         updatePart={this.updatePart.bind(null, colnum, 0)}
                                         getPartStyles={this.props.getPartStyles}
                                         getPartStylesDisplay={this.props.getPartStylesDisplay}
                                         setNextPart={this.props.setNextPart}
                                         disabled={this.props.disabled}
                                         setSelection={this.setSelection}
                                         clearSelection={this.props.clearSelection}
                                         selected={this.props.selected && colnum === this.props.selectedCol}
                                         selectedCol={null}
                                         selectedColIndex={null}
                                         hover={this.state.hoverPart === colnum && this.props.hover && colnum !== this.props.selectedCol}
                                         hoverPink={true}
                                         popupToolbarLeft={-50}
                                         isInCol={true}
                                         imgWidth={imgwidth}
                                         ref={r => {this._refs[colnum+",0"] = r}}
                                         highlight={this.state.highlightCol === colnum && this.state.highlightColIndex === 0}
                                         highlightBottom={this.state.highlightCol === colnum && this.state.highlightColIndex > 0}
                            />
                            )
                        }
                      </th>
                    );
                  })
                }
                {
                /*
                <th className="expander" style={{visibility: 'hidden', width: '0', padding: '0'}} />
                */
                }
              </tr>
            </tbody>
          </table>
          {
            this.state.showModal !== null &&
              <Modal show={true}>
                <Modal.Header>
                  <Modal.Title>Delete Component Confirmation</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                  <p>Are you sure you want to delete this component?</p>
                </Modal.Body>
                <Modal.Footer>
                  <Button onClick={this.confirmClicked.bind(this, true)} bsStyle="primary">Yes</Button>
                  <Button onClick={this.confirmClicked.bind(this, false)}>No</Button>
                </Modal.Footer>
              </Modal>
          }
        </Wrapper>
      </InnerPartDisplay>
    );
  }
}

class DividerPartDisplay extends Component {
  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  render() {
    var p = this.props;
    const style = p.getPartStyles(p);
    const {selected, selectedCol, color, displayOnly} = style;
    const f = p.getPartStylesDisplay(p);

    return (
      <InnerPartDisplay form={this.props.form} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} disabled={this.props.disabled} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} toolbar={
        <EditToolbar {...style} isInCol={this.props.isInCol}>
          <ButtonGroup>
            <FormControlPopup
              id="size"
              obj={style}
              text="Size"
              onChange={this.handleChange}
              type="number"
              min="1"
              max="100"
            />
            <ColorPopup id="color" type="line" color={color} onChange={this.handleColorChange.bind(null, 'color')} />
          </ButtonGroup>
        </EditToolbar>
      } panels={[
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
      ]}>
        <Wrapper style={{
          ...paddingStyle(f),
          ...marginStyle(f),
          ...backgroundStyle(f),
        }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}>
          <hr style={{
            borderColor: f.color,
            borderStyle: 'solid',
            borderTopWidth:f.size+'px',
            borderBottomWidth: '0',
            borderLeftWidth: '0',
            borderRightWidth: '0',
            marginTop: '0',
            marginBottom: '0',
            marginRight: '0',
            marginLeft: '0',
          }}/>
        </Wrapper>
      </InnerPartDisplay>
    );
  }
}

class SpacerPartDisplay extends Component {
  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  render() {
    var p = this.props;
    const style = p.getPartStyles(p);
    const {selected, selectedCol, displayOnly, height} = style;
    const f = p.getPartStylesDisplay(p);

    return (
      <InnerPartDisplay form={this.props.form} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} disabled={this.props.disabled} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} toolbar={
        <EditToolbar {...style} isInCol={this.props.isInCol}>
          <ButtonGroup>
            <FormControlPopup id="height" obj={style} text={<span className="fa fa-arrows-v"></span>} onChange={this.handleChange} type="number" min="1" max="1000" />
          </ButtonGroup>
        </EditToolbar>
      } panels={[
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
        {name: 'Border', body: <BorderPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
        {name: 'Width', body: <WidthPanel obj={style} onChange={this.handleChange} /> }
      ]}>
        <Wrapper style={{
                     ...marginStyle(f),
                     ...paddingStyle(f),
                     ...borderStyle(f),
                     ...backgroundStyle(f),
                     }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}>
          <div style={{height: height + 'px'}}></div>
        </Wrapper>
      </InnerPartDisplay>
    );
  }

}

class HTMLPartDisplay extends Component {
  constructor(props) {
    super(props);

    this.state = {
      showModal: false,
      value: props.customHtml || '',
    };

    this.editorRef = null;
  }

  componentWillReceiveProps(props) {
    if (props.customHtml !== this.props.customHtml) {
      this.setState({value: props.customHtml || ''});
    }
  }

  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  openModal = () => {
    this.setState({showModal: true, value: this.props.customHtml || ''});
  }

  closeModal = () => {
    this.setState({showModal: false});
  }

  saveModal = () => {
    this.props.updatePart(this.props.id, {customHtml: this.state.value}, () => {
      this.setState({showModal: false});
    });
  }

  setEditorRef = ref => {
    this.editorRef = ref;
  }

  insertText = txt => {
    if (this.editorRef) {
      this.editorRef.replaceSelection(txt);
    } else {
      this.setState({value: this.state.value + txt});
    }
  }

  render() {
    var p = this.props;
    const style = p.getPartStyles(p);
    const {selected, selectedCol, displayOnly} = style;
    const f = p.getPartStylesDisplay(p);
    const cleanHtml = sanitizeHTML(this.props.customHtml || '', {proxyImages: true});
    const displayHtml = cleanHtml || (displayOnly ? '' : '<p style="margin:0; color:#999999">Empty HTML block</p>');
    const body = (
      <Wrapper style={{
                   ...marginStyle(f),
                   ...paddingStyle(f),
                   ...borderStyle(f),
                   ...backgroundStyle(f),
                   }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}>
        <DivTable innerHTML={{__html: displayHtml}}/>
      </Wrapper>
    );

    if (displayOnly) {
      return body;
    }

    return (
      <div>
        <InnerPartDisplay form={this.props.form} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} disabled={this.props.disabled} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} toolbar={
          <EditToolbar {...style} isInCol={this.props.isInCol}>
            <ButtonGroup>
              <Button onClick={this.openModal}>Edit HTML</Button>
            </ButtonGroup>
          </EditToolbar>
        } panels={[
          {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
          {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
          {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
          {name: 'Border', body: <BorderPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
          {name: 'Width', body: <WidthPanel obj={style} onChange={this.handleChange} /> }
        ]}>
          {body}
        </InnerPartDisplay>
        {
          this.state.showModal &&
          <Modal show={true} onHide={this.closeModal} bsSize="large">
            <Modal.Header closeButton>
              <Modal.Title>Edit HTML</Modal.Title>
            </Modal.Header>
            <Modal.Body>
              <div style={{border: '1px solid #ddd', borderRadius: '4px'}}>
                <CodeMirror
                  value={this.state.value}
                  onBeforeChange={(editor, data, value) => {
                    this.setState({value: value});
                  }}
                  options={{
                    mode: 'htmlmixed',
                    lineNumbers: true,
                    viewportMargin: Infinity,
                  }}
                  editorDidMount={this.setEditorRef}
                />
              </div>
              <div className="space20"/>
              <ControlLabel>Sanitized Preview</ControlLabel>
              <div style={{border: '1px solid #ddd', borderRadius: '4px', padding: '10px', minHeight: '60px'}} dangerouslySetInnerHTML={{__html: sanitizeHTML(this.state.value, {proxyImages: true}) || '<p style="margin:0; color:#999999">Empty HTML block</p>'}} />
            </Modal.Body>
            <Modal.Footer>
              <Button onClick={this.saveModal} bsStyle="primary">Save HTML</Button>
              <Button onClick={this.closeModal}>Cancel</Button>
            </Modal.Footer>
          </Modal>
        }
      </div>
    );
  }
}

class SocialPartDisplay extends Component {
  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  onAlignLeft = () => {
    this.props.updatePart(this.props.id, {align: 'left'});
  }
  onAlignCenter = () => {
    this.props.updatePart(this.props.id, {align: 'center'});
  }
  onAlignRight = () => {
    this.props.updatePart(this.props.id, {align: 'right'});
  }

  setFont = font => {
    this.props.updatePart(this.props.id, {fontFamily: font});
  }

  setFontSize = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleClick = (event) => {
    event.preventDefault();
  }

  socialIcon({s, color, style, f}) {
    return (
      <td style={{padding: '4px', verticalAlign: 'middle'}}>
        <table role="presentation" cellPadding="0" cellSpacing="0" style={{background:color,borderRadius:'3px',width:'20px',border:'none'}}>
          <tbody>
            <tr>
              <td style={{fontSize: '0px',padding: 0,verticalAlign:'middle',width:'20px',height:'20px'}}>
                <a href={style[s + 'Link']} onClick={this.handleClick} onDragStart={e => e.preventDefault()}>
                  <img alt={s} height="20" src={'/img/' + s + '-icon.png'} width="20" style={{display:'block',borderRadius: '3px'}}/>
                </a>
              </td>
            </tr>
          </tbody>
        </table>
      </td>
    );
  }

  socialLabel({s, style, f}) {
    return (
      <td style={{padding:'4px 4px 4px 0',verticalAlign: 'middle'}}>
        <a href={style[s + 'Link']} onDragStart={e => e.preventDefault()} style={{textDecoration:'none',textAlign:'left',display:'block',color:f.color}} onClick={this.handleClick}>
          {style[s + 'Label']}
        </a>
      </td>
    );
  }

  socialItems({layout, colors, style, f, labels, iconColor, iconCustom}) {
    if (layout === 'horizontal') {
      return (
        <table cellPadding="0" cellSpacing="0" style={{border:'none', display: 'inline-table'}}>
          <tbody>
            <tr>
            {
              _.map(['facebook', 'twitter', 'instagram', 'pinterest', 'linkedin'], s => {
                if (!style[s]) {
                  return null;
                }
                var color = colors[s];
                if (iconColor !== 'default') {
                  color = iconCustom;
                }
                var r = [
                  this.socialIcon({s: s, color: color, style: style, f: f})
                ];
                if (labels) {
                  r.push(this.socialLabel({s: s, style: style, f: f}));
                }
                return r;
              })
            }
            </tr>
          </tbody>
        </table>
      );
    } else {
      return (
        <table cellPadding="0" cellSpacing="0" style={{border:'none', display: 'inline-table'}}>
          <tbody>
          {
            _.map(['facebook', 'twitter', 'instagram', 'pinterest', 'linkedin'], s => {
              if (!style[s]) {
                return null;
              }
              var color = colors[s];
              if (iconColor !== 'default') {
                color = iconCustom;
              }
              return (
                <tr key={s}>
                  {
                    this.socialIcon({s: s, color: color, style: style, f: f})
                  }
                  { labels &&
                    this.socialLabel({s: s, style: style, f: f})
                  }
                </tr>
              );
            })
          }
          </tbody>
        </table>
      );
    }
  }

  render() {
    var p = this.props;
    const style = p.getPartStyles(p);
    const {selected, selectedCol, align, fontFamily, color, displayOnly, labels, iconColor, iconCustom, layout} = style;
    const f = p.getPartStylesDisplay(p);

    var colors = {
      facebook:  'rgb(59,89,152)',
      twitter:   'rgb(85,172,238)',
      instagram: 'rgb(63,114,155)',
      pinterest: 'rgb(189,8,28)',
      linkedin:  'rgb(0,119,181)',
    };

    return (
      <InnerPartDisplay form={this.props.form} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} disabled={this.props.disabled} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} toolbar={
        <EditToolbar {...style} isInCol={this.props.isInCol}>
          <ButtonGroup>
            <Button onClick={this.onAlignLeft} active={align==='left'}><Glyphicon glyph="align-left"/></Button>
            <Button onClick={this.onAlignCenter} active={align==='center'}><Glyphicon glyph="align-center"/></Button>
            <Button onClick={this.onAlignRight} active={align==='right'}><Glyphicon glyph="align-right"/></Button>
          </ButtonGroup>
          <ButtonGroup>
            <DropdownButton title={<span className="fa fa-font"></span>} id="fonts">
              {
                _.map(fonts, f => <MenuItem key={f} style={{fontFamily: f}} active={fontFamily === f} onClick={this.setFont.bind(null, f)}>{f}</MenuItem>)
              }
            </DropdownButton>
            <FormControlPopup id="fontSize" obj={style} text={<span className="fa fa-text-height"></span>} onChange={this.setFontSize} type="number" min="6" max="200" />
            <ColorPopup id="textcolor" type="text" color={color} onChange={this.handleColorChange.bind(null, 'color')} />
          </ButtonGroup>
        </EditToolbar>
      } panels={[
        {name: 'Social', body: <SocialPanel type="padding" obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'iconCustom')} /> },
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
        {name: 'Border', body: <BorderPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
        {name: 'Width', body: <WidthPanel obj={style} onChange={this.handleChange} /> }
      ]}>
        <Wrapper style={{
                     textAlign: f.align,
                     fontSize: f.fontSize,
                     fontFamily: f.fontFamily,
                     color: f.color,
                     ...marginStyle(f),
                     ...paddingStyle(f),
                     ...borderStyle(f),
                     ...backgroundStyle(f),
                     }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}>
          <div>

          {
            this.socialItems({layout: layout, colors: colors, style: style, f: f, labels: labels, iconColor: iconColor, iconCustom: iconCustom})
          }
          </div>
        </Wrapper>
      </InnerPartDisplay>
    );
  }
}

class InputPartDisplay extends Component {
  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  onAlignLeft = () => {
    this.props.updatePart(this.props.id, {align: 'left'});
  }
  onAlignCenter = () => {
    this.props.updatePart(this.props.id, {align: 'center'});
  }
  onAlignRight = () => {
    this.props.updatePart(this.props.id, {align: 'right'});
  }

  setFont = font => {
    this.props.updatePart(this.props.id, {fontFamily: font});
  }

  setFontSize = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  onFlagChange = prop => {
    this.props.updatePart(this.props.id, {[prop]: !this.props[prop]});
  }

  render() {
    var p = this.props;
    const style = p.getPartStyles(p);
    const {selected, selectedCol, placeholder, align, fontFamily, color, inputColor, inputBorderColor, displayOnly,
           bold, italic, inputWidth, inputHeight, inputRadius, inputType, required, field} = style;
    const f = p.getPartStylesDisplay(p);

    var inputstyle = {
      backgroundColor: f.inputColor,
      color: color,
      borderStyle: 'solid',
      borderWidth: '1px',
      borderColor: inputBorderColor,
      borderRadius: inputRadius + 'px',
      paddingTop: inputHeight + 'px',
      paddingBottom: inputHeight + 'px',
      paddingLeft: inputWidth + 'px',
      paddingRight: inputWidth + 'px',
      width: '100%',
      margin: 0,
      fontSize: f.fontSize,
      fontFamily: f.fontFamily,
      textAlign: f.align,
      boxSizing: 'border-box',
    };

    if (bold) {
      inputstyle.fontWeight = 'bold';
    }
    if (italic) {
      inputstyle.fontStyle = 'italic';
    }

    return (
      <InnerPartDisplay form={this.props.form} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} disabled={this.props.disabled} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} toolbar={
        <EditToolbar {...style} isInCol={this.props.isInCol}>
          <ButtonGroup>
            <Button onClick={this.onAlignLeft} active={align==='left'}><Glyphicon glyph="align-left"/></Button>
            <Button onClick={this.onAlignCenter} active={align==='center'}><Glyphicon glyph="align-center"/></Button>
            <Button onClick={this.onAlignRight} active={align==='right'}><Glyphicon glyph="align-right"/></Button>
          </ButtonGroup>
          <ButtonGroup>
            <Button onClick={this.onFlagChange.bind(null, 'bold')} active={bold}><Glyphicon glyph="bold"/></Button>
            <Button onClick={this.onFlagChange.bind(null, 'italic')} active={italic}><Glyphicon glyph="italic"/></Button>
            <DropdownButton title={<span className="fa fa-font"></span>} id="fonts">
              {
                _.map(fonts, f => <MenuItem key={f} style={{fontFamily: f}} active={fontFamily === f} onClick={this.setFont.bind(null, f)}>{f}</MenuItem>)
              }
            </DropdownButton>
            <FormControlPopup id="fontSize" obj={style} text={<span className="fa fa-text-height"></span>} onChange={this.setFontSize} type="number" min="6" max="200" />
          </ButtonGroup>
          <ButtonGroup>
            <ColorPopup id="textcolor" type="text" color={color} onChange={this.handleColorChange.bind(null, 'color')} />
            <ColorPopup id="btncolor" type="btn" color={inputColor} onChange={this.handleColorChange.bind(null, 'inputColor')} />
            <ColorPopup id="bordercolor" type="line" color={inputBorderColor} onChange={this.handleColorChange.bind(null, 'inputBorderColor')} />
          </ButtonGroup>
          <ButtonGroup>
            <FormControlPopup id="inputWidth" label="Pad Width" obj={style} defValue={10} text={<span className="fa fa-arrows-h"></span>} onChange={this.handleChange} type="number" min="0" style={{width: '75px'}} />
            <FormControlPopup id="inputHeight" label="Pad Height" obj={style} defValue={10} text={<span className="fa fa-arrows-v"></span>} onChange={this.handleChange} type="number" min="0" style={{width: '75px'}} />
            <FormControlPopup id="inputRadius" label="Radius" obj={style} defValue={4} text={<span className="fa fa-square-o"></span>} onChange={this.handleChange} type="number" min="0" style={{width: '75px'}} />
          </ButtonGroup>
        </EditToolbar>
      } panels={[
        {name: 'Input', body: <InputPanel obj={style} onChange={this.handleChange} fields={this.props.fields} /> },
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
        {name: 'Border', body: <BorderPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
        {name: 'Width', body: <WidthPanel obj={style} onChange={this.handleChange} /> }
      ]}>
        <Wrapper style={{
                     ...marginStyle(f),
                     ...paddingStyle(f),
                     ...borderStyle(f),
                     ...backgroundStyle(f),
                     }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}>
          <input placeholder={placeholder} name={field} type={inputType} style={inputstyle} onDragStart={e=>e.preventDefault()} required={(displayOnly && required) ? true : undefined} />
        </Wrapper>
      </InnerPartDisplay>
    );
  }
}

class ButtonPartDisplay extends Component {
  handleChange = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  handleColorChange = (prop, color) => {
    this.props.updatePart(this.props.id, {[prop]: color.hex});
  }

  handleTransparentChange = event => {
    this.props.updatePart(this.props.id, {buttonTransparent: getvalue(event)});
  }

  handleClick = (event) => {
    event.preventDefault();
  }

  onAlignLeft = () => {
    this.props.updatePart(this.props.id, {align: 'left'});
  }
  onAlignCenter = () => {
    this.props.updatePart(this.props.id, {align: 'center'});
  }
  onAlignRight = () => {
    this.props.updatePart(this.props.id, {align: 'right'});
  }

  onLink = () => {
    return {url: this.props.link};
  }

  onLinkConfirm = urlValue => {
    this.props.updatePart(this.props.id, {link: urlValue});
  }

  onUnlink = () => {
    this.props.updatePart(this.props.id, {link: ''});
  }

  setFont = font => {
    this.props.updatePart(this.props.id, {fontFamily: font});
  }

  setFontSize = event => {
    this.props.updatePart(this.props.id, {[event.target.id]: getvalue(event)});
  }

  onFlagChange = prop => {
    this.props.updatePart(this.props.id, {[prop]: !this.props[prop]});
  }

  setButtonType = t => {
    this.props.updatePart(this.props.id, {buttonType: t});
  }

  render() {
    var p = this.props;
    const style = p.getPartStyles(p);
    const {selected, selectedCol, text, link, align, fontFamily, color, buttonColor, displayOnly,
           bold, italic, underline, strikethrough, buttonWidth, buttonHeight, buttonRadius,
           buttonTransparent, buttonType} = style;
    const f = p.getPartStylesDisplay(p);

    var tdstyle = {
      backgroundColor: buttonTransparent?'transparent':f.buttonColor,
      position: 'relative', 
      verticalAlign: 'top',
      textAlign: 'center',
      borderStyle: 'solid',
      borderWidth: '1px',
      borderColor: f.buttonColor,
      overflow: 'none',
    };

    var width = buttonWidth;
    var height = buttonHeight;
    var radius = buttonRadius;
    if (_.isUndefined(width)) {
      width = 10;
    }
    if (_.isUndefined(height)) {
      height = 10;
    }
    if (_.isUndefined(radius)) {
      radius = 4;
    }
    tdstyle.paddingLeft   = width + 'px';
    tdstyle.paddingRight  = width + 'px';
    tdstyle.paddingTop    = height + 'px';
    tdstyle.paddingBottom = height + 'px';
    tdstyle.borderRadius  = radius + 'px';

    var linkstyle = {
      textDecoration: 'none',
    };
    var textstyle = {
      color: f.color,
    };
    if (bold) {
      textstyle.fontWeight = 'bold';
    }
    if (italic) {
      textstyle.fontStyle = 'italic';
    }
    if (underline && strikethrough) {
      textstyle.textDecoration = 'underline line-through';
    } else if (underline) {
      textstyle.textDecoration = 'underline';
    } else if (strikethrough) {
      textstyle.textDecoration = 'line-through';
    }

    return (
      <InnerPartDisplay form={this.props.form} isInCol={this.props.isInCol} popupToolbarLeft={this.props.popupToolbarLeft} onBorderSelect={this.props.onBorderSelect} disabled={this.props.disabled} selected={selected} selectedCol={selectedCol} displayOnly={displayOnly} toolbar={
        <EditToolbar {...style} isInCol={this.props.isInCol}>
          <ButtonGroup>
            <FormControlPopup
              id="text"
              obj={style}
              text="Text"
              onChange={this.handleChange}
            />
          </ButtonGroup>
          { !this.props.form &&
          <ButtonGroup>
            <LinkPopup onPopup={this.onLink} onConfirm={this.onLinkConfirm} nocolor />
            <Button disabled={!link} onClick={this.onUnlink}><i className="fa fa-unlink"></i></Button>
          </ButtonGroup>
          }
          <ButtonGroup>
            <Button onClick={this.onAlignLeft} active={align==='left'}><Glyphicon glyph="align-left"/></Button>
            <Button onClick={this.onAlignCenter} active={align==='center'}><Glyphicon glyph="align-center"/></Button>
            <Button onClick={this.onAlignRight} active={align==='right'}><Glyphicon glyph="align-right"/></Button>
          </ButtonGroup>
          <ButtonGroup>
            <Button onClick={this.onFlagChange.bind(null, 'bold')} active={bold}><Glyphicon glyph="bold"/></Button>
            <Button onClick={this.onFlagChange.bind(null, 'italic')} active={italic}><Glyphicon glyph="italic"/></Button>
            <Button onClick={this.onFlagChange.bind(null, 'underline')} active={underline}><span className="fa fa-underline"></span></Button>
            <Button onClick={this.onFlagChange.bind(null, 'strikethrough')} active={strikethrough}><span className="fa fa-strikethrough"></span></Button>
            <DropdownButton title={<span className="fa fa-font"></span>} id="fonts">
              {
                _.map(fonts, f => <MenuItem key={f} style={{fontFamily: f}} active={fontFamily === f} onClick={this.setFont.bind(null, f)}>{f}</MenuItem>)
              }
            </DropdownButton>
            <FormControlPopup id="fontSize" obj={style} text={<span className="fa fa-text-height"></span>} onChange={this.setFontSize} type="number" min="6" max="200" />
          </ButtonGroup>
          <ButtonGroup>
            <ColorPopup id="textcolor" type="text" color={color} onChange={this.handleColorChange.bind(null, 'color')} />
            <ColorPopup id="btncolor" type="btn" color={buttonColor} enableTransparent={true} transparent={_.isUndefined(buttonTransparent)?false:buttonTransparent} onTransparentChange={this.handleTransparentChange} onChange={this.handleColorChange.bind(null, 'buttonColor')} />
          </ButtonGroup>
          <ButtonGroup>
            <FormControlPopup id="buttonWidth" label="Width" obj={style} defValue={10} text={<span className="fa fa-arrows-h"></span>} onChange={this.handleChange} type="number" min="0" style={{width: '75px'}} />
            <FormControlPopup id="buttonHeight" label="Height" obj={style} defValue={10} text={<span className="fa fa-arrows-v"></span>} onChange={this.handleChange} type="number" min="0" style={{width: '75px'}} />
            <FormControlPopup id="buttonRadius" label="Radius" obj={style} defValue={4} text={<span className="fa fa-square-o"></span>} onChange={this.handleChange} type="number" min="0" style={{width: '75px'}} />
          </ButtonGroup>
          { this.props.form &&
          <ButtonGroup>
            <Button onClick={this.setButtonType.bind(null, '')} active={!buttonType}>Submit</Button>
            <Button onClick={this.setButtonType.bind(null, 'dismiss')} active={buttonType==='dismiss'}>Dismiss</Button>
          </ButtonGroup>
          }
        </EditToolbar>
      } panels={[
        {name: 'Background', body: <BackgroundPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(null, 'backgroundColor')} /> },
        {name: 'Padding', body: <SpacerPanel type="padding" obj={style} onChange={this.handleChange} /> },
        {name: 'Margin', body: <SpacerPanel type="margin" obj={style} onChange={this.handleChange} /> },
        {name: 'Border', body: <BorderPanel obj={style} onChange={this.handleChange} onColorChange={this.handleColorChange.bind(this, 'borderColor')} /> },
        {name: 'Width', body: <WidthPanel obj={style} onChange={this.handleChange} /> }
      ]}>
        <Wrapper style={{
                     textAlign: f.align,
                     fontSize: f.fontSize,
                     fontFamily: f.fontFamily,
                     ...marginStyle(f),
                     ...paddingStyle(f),
                     ...borderStyle(f),
                     ...backgroundStyle(f),
                     }} outerStyle={widthStyle(f)} isInCol={this.props.isInCol}>
          <a onDragStart={e=>e.preventDefault()} href={link} onClick={this.handleClick} target="_blank" className={!buttonType?'edcom-button':'edcom-button-dismiss'} style={linkstyle}>
            <table style={{display: 'inline-table', padding: 0, verticalAlign: 'top', textAlign: 'left', borderSpacing: 0, borderCollapse: 'separate', width: 'auto'}}>
              <tbody>
                <tr style={{padding: 0, verticalAlign: 'top'}}>
                  <td style={tdstyle}>
                    <DivTable center={true}>
                      <span style={textstyle}>
                        {text}
                      </span>
                    </DivTable>
                  </td>
                </tr>
              </tbody>
            </table>
          </a>
        </Wrapper>
      </InnerPartDisplay>
    );
  }
}

class PartDisplay extends Component {
  constructor(props) {
    super(props);

    this.state = {
      hideBorder: false,
    };
  }

  componentWillReceiveProps(newProps) {
    if (newProps.selected !== this.props.selected) {
      this.setState({hideBorder: false});
    }
  }

  onBorderSelect = val => {
    this.setState({hideBorder: val}, () => {
      if (this.props.onBorderSelect) {
        this.props.onBorderSelect(val);
      }
    });
  }

  onDragStart = event => {
    if (_.isUndefined(this.props.colnum)) {
      this.props.setNextPart(this.props.index.toString());
    } else {
      this.props.setNextPart(this.props.index + ',' + this.props.colnum + ',' + this.props.colindex);
      event.stopPropagation();
    }

    event.dataTransfer.setData('text', 'none');
  }

  onClick = event => {
    event.stopPropagation();

    if (this.props.type === 'Invisible') {
      this.props.clearSelection();
      return;
    }

    if (!this.props.setSelection || this.props.disabled || (this.props.selected && fromProperties(event, true))) {
      return;
    }

    var rect = this._ref.getBoundingClientRect();
    var y = truncate(event.clientY - rect.top);
    var x = truncate(event.clientX - rect.left);

    var cs = window.getComputedStyle(this._ref);
    var marginTop    = cs.marginTop;
    var marginBottom = cs.marginBottom;
    marginTop    = parseInt(marginTop.substring(   0, marginTop.length   -2), 10);
    marginBottom = parseInt(marginBottom.substring(0, marginBottom.length-2), 10);

    if (x >= 0 && x <= rect.width &&
        y >= marginTop  && y <= rect.height - marginBottom) {
      if (!_.isUndefined(this.props.colnum)) {
        this.props.setSelection(this.props.colnum, this.props.colindex);
      } else {
        this.props.setSelection(this.props.index, null, null);
      }
    } else {
      this.props.clearSelection();
    }
  }

  render() {
    var p = this.props;
    const {type, displayOnly, selected} = p;

    var partdisplay = {
      Headline: <TextPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Image: <ImagePartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Text: <TextPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      HTML: <HTMLPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Divider: <DividerPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Button: <ButtonPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Columns: <ColumnsPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Social: <SocialPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Spacer: <SpacerPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Input: <InputPartDisplay {...p} onBorderSelect={this.onBorderSelect} />,
      Invisible: <InvisiblePartDisplay {...p} />
    }[type];

    if (displayOnly)
      return partdisplay;

    var r = (
      <div style={{
             cursor: type==='Invisible'?undefined:'pointer',
             position: 'relative',
             flex: type==='Invisible'?1:undefined,
           }}
           className="part-display"
           onDragStart={this.onDragStart}
           onClick={this.onClick}
           onMouseOver={this.onMouseOver}
           onMouseLeave={this.onMouseLeave}
           ref={el => this._ref = el}
           id={type === 'Invisible'?'invisible-part':undefined}
      >
        {
          this.props.hover && !selected && type !== 'Invisible' && this.props.hoverPink &&
          <div className="hover-overlay hover-pink" />
        }
        {
          selected && !this.state.hideBorder && this.props.hoverPink &&
          <div className="selected-overlay selected-pink" />
        }
        {partdisplay}
        {
          this.props.highlight &&
            (this.props.isInCol ?
              <div className="placeholder pink"/>
             :
              <div className="placeholder"/>
            )
        }
        {
          this.props.highlightBottom &&
            <div className="placeholder bottom"/>
        }
      </div>
    );

    return r;
  }
}

class FormCloseButton extends Component {
  render() {
    const {paddingTop, paddingRight, bodyType, bodyWidth, mobileWidth, designType, formCloseStyle, formCloseBorder, formCloseTop, formCloseRight, formCloseSize} = this.props;

    var size = formCloseSize;
    if (formCloseSize === null || _.isUndefined(formCloseSize)) {
      size = 26;
    } else if (formCloseSize < 10) {
      size = 10;
    } else if (formCloseSize > 100) {
      size = 100;
    }

    var top = parseInt(paddingTop.substring(0, paddingTop.length-2), 10);
    var right = parseInt(paddingRight.substring(0, paddingTop.length-2), 10);
    if (bodyType === 'fixed') {
      right = 'calc(50% - ' + Math.trunc(bodyWidth/2 + (-formCloseRight||0) + size/2) + 'px)';
      top = (top + (formCloseTop||0) - size/2) + 'px';
    } else {
      if (designType === 'mobile') {
        var width = DEFAULT_MOBILE_WIDTH;
        if (mobileWidth) {
          width = parseInt(mobileWidth, 10);
        }
        right = 'calc(50% - ' + Math.trunc(width/2 + (-formCloseRight||0) - 1) + 'px)';
      } else {
        right = (right + (formCloseRight||0) + 1) + 'px';
      }
      top = (top + (formCloseTop||0) + 1) + 'px';
    }

    return (
      <div style={{
        right: right,
        top: top,
        width: size + 'px',
        height: size + 'px',
        lineHeight: Math.trunc(size * .85) + 'px',
        fontSize: Math.trunc(size  * .7) + 'px',
        borderRadius: size + 'px',
      }} id="FormCloseButton" className={(formCloseStyle?formCloseStyle:'') + (formCloseBorder?'':' noborder')}>
        &#xd7;
      </div>
    );
  }
}

class Viewer extends Component {
  constructor(props) {
    super(props);

    this.state = {
      highlight: false,
      highlightPart: null,
      hoverPart: null,
      hoverTop: null,
      hoverHeight: null,
      selectedTop: null,
      selectedHeight: null,
      selectedToolbarTop: null,
      selectedToolbarRight: null,
      popupToolbarLeft: null,
      hideBorder: false,
      clientwidth: document.body.clientWidth,
    };
    this._columnDragCallbacks = {};
    this._updateDimensions = _.throttle(this.updateDimensions, 200);
    this._updateHighlight = _.throttle(_.bind((event) => {
      var {index, tophalf} = this.hoverIndex(event);

      var parts = this.props.parts;
      var bumped = false;
      if ((index >= parts.length-2) && parts.length > 0 && parts[parts.length-1].footer) {
        index = parts.length-2;
        bumped = true;
      }

      if (index < this.props.parts.length) {
        var part = this.props.parts[index];
        if (part.type === 'Columns' && this.props.nextPartType !== 'Columns') {
          var colid = part.id;
          if (this._columnDragCallbacks[part.id](event).colindex === null) {
            if (!tophalf && !bumped) {
              if (index + 1 < this.props.parts.length) {
                part = this.props.parts[index+1];
                this.setState({highlight: false, highlightPart: part.id});
              } else {
                this.setState({highlight: false, highlightPart: null});
              }
            } else {
              this.setState({highlight: false, highlightPart: part.id});
            }
          } else {
            this.setState({highlight: false, highlightPart: null});
          }
          _.each(this._columnDragCallbacks, (cb, id) => {
            if (id !== colid) {
              cb(null);
            }
          });
        } else {
          if (!tophalf && !bumped) {
            if (index + 1 < this.props.parts.length) {
              part = this.props.parts[index+1];
              this.setState({highlight: false, highlightPart: part.id});
              _.each(this._columnDragCallbacks, cb => {
                cb(null);
              });
            } else {
              this.setState({highlight: true, highlightPart: null});
              _.each(this._columnDragCallbacks, cb => {
                cb(null);
              });
            }
          } else {
            this.setState({highlight: false, highlightPart: part.id});
            _.each(this._columnDragCallbacks, cb => {
              cb(null);
            });
          }
        }
      } else {
        this.setState({highlight: true, highlightPart: null});
        _.each(this._columnDragCallbacks, cb => {
          cb(null);
        });
      }
    }, this), 200, {trailing: false});
  }

  partMenuPlacement(index, log) {
    var top = this.props.getBodyStyle('paddingTop');
    var bottom = top;

    var partcount = 0;
    for (var i = 0; i < this._ref.childNodes[0].childNodes.length; i++) {
      var node = this._ref.childNodes[0].childNodes[i];

      if (node.className === 'btn-group-vertical' || node.className === 'hover-overlay' || node.className === 'selected-overlay' ||
          node.id === 'FormCloseButton') {
        continue;
      }

      var cs = window.getComputedStyle(node);
      var height = cs.height;
      var hint = parseInt(height.substring(0, height.length-2), 10);

      bottom += hint;

      if (partcount === index) {
        break;
      }

      if (node.className.includes('part-display')) {
        partcount++;
      }

      top += hint;
    }

    var left;
    var clientwidth = this._parentRef.clientWidth;

    if (this.props.fixed) {
      clientwidth -= SIDEBAR_WIDTH;
    }
    
    if (this.props.getBodyStyle('bodyType') === 'fixed') {
      left = 14;
    } else {
      if (this.props.form && this.props.designType === 'mobile') {
        var w = DEFAULT_MOBILE_WIDTH;
        var mobileWidth = this.props.getBodyStyle('mobileWidth');
        if (mobileWidth) {
          w = parseInt(mobileWidth, 10);
        }
        left = 14 - Math.trunc(clientwidth/2 - w/2);
      } else {
        left = -this.props.getBodyStyle('paddingLeft') + 14;
      }
    }

    return {top: top, right: 15, bottom: bottom, left: left};
  }

  hoverIndex(event) {
    var rect = this._parentRef.getBoundingClientRect();
    var y = event.clientY - rect.top + this._ref.parentNode.scrollTop;
    var lasty = this.props.getBodyStyle('paddingTop');
    var partindex = 0;
    for (var i = 0; i < this._ref.childNodes[0].childNodes.length; i++) {
      var node = this._ref.childNodes[0].childNodes[i];

      var cs = window.getComputedStyle(node);
      var height = cs.height;
      var hint = parseInt(height.substring(0, height.length-2), 10);

      if (node.className.includes('part-display')) {
        if (y >= lasty && y < lasty + hint) {
          return {index: partindex, tophalf: y - lasty < hint/2};
        }
        partindex++;
        lasty += hint;
      }
    }
    return {index: this.props.parts.length, inside: false};
  }

  onDragOver = event => {
    event.preventDefault();  

    this._updateHighlight(event);
  }

  onDragEnter = event => {
    this._updateHighlight(event);
  }

  onDragLeave = event => {
    var x = event.clientX;
    var y = event.clientY;
    var rect = this._parentRef.getBoundingClientRect();
    var outside = (x <= rect.left || x >= rect.right || y <= rect.top || y >= rect.bottom);
    if (event.target.id === 'Viewer' || outside) {
      this.setState({highlight: false, highlightPart: null});
      _.each(this._columnDragCallbacks, cb => {
        cb(null);
      });
    }
  }

  onDrop = event => {
    event.preventDefault();
    event.stopPropagation();

    if (event.dataTransfer && event.dataTransfer.items && event.dataTransfer.items[0].kind === 'file') {
      this.props.clearSelection(() => {
        this.setState({highlight: false, highlightPart: null, hoverPart: null}, () => { this.props.setNextPart(null); });
      });
      return;
    }

    var {index,tophalf} = this.hoverIndex(event);

    var parts = this.props.parts;
    var bumped = false;
    if ((index >= parts.length-2) && parts.length > 0 && parts[parts.length-1].footer) {
      index = parts.length-2;
      bumped = true;
    }

    var colnum = null, colindex = null;
    if (index < this.props.parts.length) {
      var part = this.props.parts[index];
      if (part.type === 'Columns' && this.props.nextPartType !== 'Columns') {
        var d = this._columnDragCallbacks[part.id](event, true);
        colnum = d.colnum;
        colindex = d.colindex;

        if (colnum === null) {
          if (!tophalf && !bumped) {
            index++;
          }
        }
      } else {
        if (!tophalf && !bumped) {
          index++;
        }
      }
    }

    this.props.addPart(index, colnum, colindex);
    this.props.clearSelection(() => {
      this.setState({highlight: false, highlightPart: null, hoverPart: null}, () => { this.props.setNextPart(null); });
    });
  }

  onMouseMove = event => {
    if (fromSidebar(event)) {
      this.setState({hoverPart: null});
      return;
    }
    if (this.props.disabled || fromProperties(event) || this.props.selectedPart !== null) {
      return;
    }

    if (event.target.className === 'arrow' || event.target.className === 'popover-content') {
      return;
    }

    var {index} = this.hoverIndex(event);

    var {top, bottom} = this.partMenuPlacement(index);

    this.setState({hoverPart: index, hoverTop: top, hoverHeight: bottom - top});
  }

  onMouseLeave = () => {
    this.setState({hoverPart: null});
  }

  removePart = () => {
    this.setState({hoverPart: null}, () => {
      this.props.removePart();
    });
  }

  moveUp = () => {
    this.props.movePartUp(() => {
      var {top, bottom} = this.partMenuPlacement(this.props.selectedPart);
      this.setState({selectedTop: top, selectedHeight: bottom - top, hoverPart: null});
    });
  }

  moveDown = () => {
    this.props.movePartDown(() => {
      var {top, bottom} = this.partMenuPlacement(this.props.selectedPart);
      this.setState({selectedTop: top, selectedHeight: bottom - top, hoverPart: null});
    });
  }

  setSelection = (index, colnum, colindex) => {
    if (colnum !== null || (this.props.selectedPart === index && this.props.selectedCol === colnum && this.props.selectedColIndex === colindex)) {
      this.setState({selectedTop: null, selectedHeight: null, selectedToolbarTop: null, selectedToolbarRight: null, popupToolbarLeft: null, hoverPart: index, hideBorder: false}, () => {
        this.props.setSelection(index, colnum, colindex);
      });
    } else {
      var {top, right, bottom, left} = this.partMenuPlacement(index, true);
      this.setState({selectedTop: top, selectedHeight: bottom - top, selectedToolbarTop: top + 15, selectedToolbarRight: right, popupToolbarLeft: left, hoverPart: index, hideBorder: false}, () => {
        this.props.setSelection(index, colnum, colindex);
      });
    }
  }

  onClick = event => {
    if (event.target.id === 'ViewerInner' || event.target.id === 'Viewer' || event.target.id === 'ViewerPadding') {
      var {index} = this.hoverIndex(event);
      if (index < this.props.parts.length && this.props.parts[index].type !== 'Invisible') {
        this.setSelection(index, null, null);
      } else {
        this.setState({selectedTop: null, selectedHeight: null, selectedToolbarTop: null, selectedToolbarRight: null, popupToolbarLeft: null, hoverPart: null, hideBorder: false}, () => {
          this.props.clearSelection();
        });
      }
    }
  }

  setColumnDragCB = (id, cb) => {
    this._columnDragCallbacks[id] = cb;
  }

  onBorderSelect = val => {
    this.setState({hideBorder: val});
  }

  updatePart = (id, pr, cb) => {
    this.props.updatePart(id, pr, () => {
      if (this.props.selectedPart !== null) {
        var {top, bottom} = this.partMenuPlacement(this.props.selectedPart);
        this.setState({selectedTop: top, selectedHeight: bottom - top}, cb);
      }
    });
  }

  componentDidMount() {
    window.addEventListener("resize", this._updateDimensions);
  }

  componentWillUnmount() {
    window.removeEventListener("resize", this._updateDimensions);
  }

  updateDimensions = () => {
    var clientwidth = document.body.clientWidth;
    if (this.props.selectedPart !== null) {
      var {top, right, bottom, left} = this.partMenuPlacement(this.props.selectedPart);
      this.setState({selectedTop: top, selectedHeight: bottom - top, selectedToolbarTop: top + 15, selectedToolbarRight: right, popupToolbarLeft: left, clientwidth: clientwidth});
    } else if (this.props.form) {
      this.setState({clientwidth: clientwidth});
    }
  }

  render() {
    var {highlight} = this.state;

    var f = this.props.getBodyStylesDisplay();
    var {backgroundColor, paddingTop, paddingBottom, paddingLeft, paddingRight, color, fontFamily, fontSize, lineHeight, align, bodyType, mobileWidth} = f;

    var style = {
      flex: '1',
      color: color,
      backgroundColor: backgroundColor,
      fontFamily: fontFamily,
      fontSize: fontSize,
      lineHeight: lineHeight,
      textAlign: align,
    };

    var hasfooter = false;
    var lastisfooter = false;
    if (this.props.parts) {
      this.props.parts.forEach(p => {
        if (p.footer) {
          hasfooter = true;
        }
      });
      if (!hasfooter && !this.props.form) {
        style.paddingBottom = '100px';
      }
      if (this.state.hoverPart !== null &&
          this.state.hoverPart < this.props.parts.length &&
          this.props.parts[this.state.hoverPart].type !== 'Invisible' &&
          this.props.selectedPart !== this.state.hoverPart) {
        style.cursor = 'pointer';
      }

      lastisfooter = this.props.parts.length > 0 && this.props.parts[this.props.parts.length-1].footer;
    }

    var innerStyle = {
      height: '100%',
      width: '100%',
    };

    var bgstyle = {
      display: 'flex',
      flexDirection: 'column',
      paddingTop: paddingTop,
      paddingBottom: paddingBottom,
      minHeight: '100%',
    };
    if (!this.props.form) {
      _.extend(bgstyle, backgroundStyle(f));
    }


    if (this.props.form && this.props.designType === 'mobile' && bodyType !== 'fixed') {
      var width = DEFAULT_MOBILE_WIDTH;
      if (mobileWidth) {
        width = parseInt(mobileWidth, 10);
      }
      var clientwidth = this.state.clientwidth - SIDEBAR_WIDTH - this.props.sideWidth;
      bgstyle.paddingLeft = Math.trunc(clientwidth/2 - width/2) + 'px';
      bgstyle.paddingRight = Math.trunc(clientwidth/2 - width/2) + 'px';
    } else if (bodyType !== 'fixed') {
      bgstyle.paddingLeft = paddingLeft;
      bgstyle.paddingRight = paddingRight;
    }

    var deftext = 'Your template is empty! Drag and drop some components from the left.';
    if (this.props.initialize) {
      deftext = 'Please wait while we make a new template for you...';
    }

    return (
      <div id="Viewer" className={this.props.form ? 'body body-form' : 'body'} onDragOver={this.onDragOver} onDragEnter={this.onDragEnter} onDragLeave={this.onDragLeave} onDrop={this.onDrop}
           onMouseMove={this.onMouseMove} onMouseLeave={this.onMouseLeave} onClick={this.onClick}
           style={style} ref={el => this._parentRef = el}>
        {!this.props.disabled && this.props.partDrawer}
        <div id="ViewerInner" className={bodyType === 'fixed'?'container':''} style={innerStyle} ref={el => this._ref = el}>
          <div id="ViewerPadding" style={bgstyle}>
          {
            this.props.selectedPart !== null && this.props.selectedCol === null &&
              <PartToolbar
                top={this.state.selectedToolbarTop}
                right={this.state.selectedToolbarRight}
                first={this.props.selectedPart===0}
                last={this.props.selectedPart===(lastisfooter?this.props.parts.length-3:this.props.parts.length-1)}
                removeOnly={this.props.parts[this.props.selectedPart].footer}
                moveUp={this.moveUp}
                moveDown={this.moveDown}
                duplicate={this.props.duplicatePart}
                remove={this.removePart}
              />
          }
          {
            this.props.selectedPart !== null && this.props.selectedCol === null && !this.state.hideBorder &&
            <div className="selected-overlay" style={{
              top:this.state.selectedTop + 'px',
              height:this.state.selectedHeight + 'px',
            }}/>
          }
          {
            this.state.hoverPart !== null && this.state.hoverPart < this.props.parts.length &&
            this.props.parts[this.state.hoverPart].type !== 'Invisible' && this.props.selectedPart !== this.state.hoverPart &&
            <div className="hover-overlay" style={{
              top:this.state.hoverTop + 'px',
              height:this.state.hoverHeight + 'px',
            }}/>
          }
          {
            (highlight && !this.props.parts.length) && 
              <div className="placeholder"></div>
          }
          {
            !this.props.parts.length ?
              <div className="text-center" style={{pointerEvents:'none'}}>
                <h4 style={{marginTop: '100px', color: this.props.form?'#fff':undefined}}>{deftext}</h4>
              </div>
            :
              _.map(this.props.parts, (p, i) => <PartDisplay key={p.id} index={i} {...p}
                                                  fields={this.props.fields}
                                                  popupToolbarLeft={this.state.popupToolbarLeft}
                                                  transactional={this.props.transactional}
                                                  form={this.props.form}
                                                  designType={this.props.designType}
                                                  getDisplayHTML={this.props.getDisplayHTML}
                                                  updatePart={this.updatePart}
                                                  addPart={this.props.addPart}
                                                  getPartStyles={this.props.getPartStyles}
                                                  getPartStylesDisplay={this.props.getPartStylesDisplay}
                                                  setNextPart={this.props.setNextPart}
                                                  setSelection={this.setSelection}
                                                  clearSelection={this.props.clearSelection}
                                                  selected={i === this.props.selectedPart}
                                                  selectedCol={this.props.selectedCol}
                                                  selectedColIndex={this.props.selectedColIndex}
                                                  hover={i === this.state.hoverPart}
                                                  disabled={this.props.disabled}
                                                  isInCol={false}
                                                  highlight={p.id === this.state.highlightPart && this.props.nextPart !== i.toString() &&
                                                             this.props.nextPart !== (i - 1).toString()}
                                                  setDragCB={this.setColumnDragCB}
                                                  onBorderSelect={this.onBorderSelect}
                                                />)
          }
          {
            (highlight && this.props.parts && this.props.parts.length>0 && this.props.nextPart !== (this.props.parts.length - 1).toString()) &&
              <div className="placeholder"></div>
          }
          {
            this.props.form && f.formCloseEnable &&
            <FormCloseButton designType={this.props.designType} {...f} />
          }
          </div>
        </div>
      </div>
    );
  }
}

class Part extends Component {
  onDragStart = event => {
    this.props.clearSelection();

    this.props.setNextPart(this.props.text);

    event.dataTransfer.setData('text', 'none');
  }

  render() {
    const props = this.props;
    const src = props.text === 'HTML' ? '/img/dnd/HTML.svg' : '/img/dnd/' + props.text + '.png';
    return (
      <img className="part" draggable="true" onDragStart={this.onDragStart}
          src={src}
          alt={props.text}
      />
    );
  }
}

class PartDrawer extends Component {
  constructor(props) {
    super(props);

    this.state = {
      activeKey: props.form?0:1,
      isUploading: false,
    };
  }

  onSelect = activeKey => {
    if (activeKey !== null) {
      this.setState({activeKey: activeKey});
    }
  }

  setFont = font => {
    this.props.setStyle('fontFamily', font);
  }

  setFontSize = event => {
    this.props.setStyle('fontSize', getvalue(event));
  }
  
  handlePropChange = event => {
    this.props.setStyle(event.target.id, getvalue(event));
  }

  handleColorChange = (prop, color) => {
    this.props.setStyle(prop, color.hex);
  }

  handlePaddingChange = event => {
    var val = getvalue(event);
    this.props.setStyle('paddingTop', val, 'paddingBottom', val, 'paddingLeft', val, 'paddingRight', val);
  }

  uploadClick = () => {
    this.props.setStyle('backgroundType', 'img');
    document.getElementById('bodyfile').click();
  }

  handleImage = event => {
    if (event.target.files.length === 0)
      return
    var file = event.target.files[0];

    notify.show("Uploading, please wait...", "success", 5000);

    getImageSize(file, async (width, height) => {
      this.setState({isUploading: true});

      try {
        var ext = file.name.split('.').pop();

        var upload = (await axios({
          method: 'post',
          url: '/api/uploadfile?type=img&ext=' + ext,
          headers: { "Content-Type": `application/octet-stream` },
          data: file
        })).data;

        var url = (await axios.post('/api/imageimport', {
          key: upload.key,
        })).data.url;

        this.props.setStyle('backgroundImage', url);
      } finally {
        this.setState({isUploading: false});
      }
    });
  }

  onSizeChange = event => {
    this.props.setStyle('backgroundSize', getvalue(event) ? 'cover': '');
  }

  onBGChange = event => {
    this.props.setStyle('backgroundType', getvalue(event) ? 'img': 'color');
  }

  render() {
    var style = this.props.getStyle();

    return (
      <div id="PartDrawer" onClick={() => this.props.clearSelection()} className="text-left">
        <Tabs defaultActiveKey={1} id="parttabs" animation={false}>
          {this.props.form ?
          <Tab eventKey={1} title="Compose">
            <Part text="Input" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Headline" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="Image" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Text" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="Button" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Columns" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="Divider" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Spacer" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="Social" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
          </Tab>
          :
          <Tab eventKey={1} title="Compose">
            <Part text="Headline" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Image" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="Text" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Button" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="HTML" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Columns" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="Divider" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <br/>
            <Part text="Spacer" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
            <Part text="Social" clearSelection={this.props.clearSelection} setNextPart={this.props.setNextPart} />
          </Tab>
          }
          <Tab eventKey={2} title="Settings">
            <PanelGroup accordion id="body-accordion" activeKey={this.state.activeKey} onSelect={this.onSelect} className="properties">
              {
                this.props.form &&
                <Panel key={0} eventKey={0}>
                  <Panel.Heading>
                    <Panel.Title toggle>Close Button</Panel.Title>
                  </Panel.Heading>
                  <Panel.Body collapsible>
                    <div className="checkbox">
                      <label>
                        <input id="formCloseEnable" type="checkbox" checked={style.formCloseEnable} onChange={this.handlePropChange} /> Show Close Button
                      </label>
                    </div>
                    <div className="space10">
                      <SelectLabel id="formCloseStyle" label="Style" obj={style} onChange={this.handlePropChange} disabled={!style.formCloseEnable}>
                        <option value="">Light</option>
                        <option value="dark">Dark</option>
                      </SelectLabel>
                    </div>
                    <div className="checkbox space20">
                      <label>
                        <input id="formCloseBorder" type="checkbox" checked={style.formCloseBorder} onChange={this.handlePropChange} disabled={!style.formCloseEnable} /> Enable Border
                      </label>
                    </div>
                    <div className="space10">
                      <FormControlLabel id="formCloseSize" label="Size" obj={style} disabled={!style.formCloseEnable} type="number" min="10" max="100" onChange={this.handlePropChange} width="75" />
                    </div>
                    <div className="space10">
                      <Row>
                        <Col xs={6}>
                          <FormControlLabel id="formCloseTop" label="Top Offset" obj={style} disabled={!style.formCloseEnable} type="number" min="-200" max="2000" onChange={this.handlePropChange} width="68" />
                        </Col>
                        <Col xs={6}>
                          <FormControlLabel id="formCloseRight" label="Right Offset" obj={style} disabled={!style.formCloseEnable} type="number" min="-200" max="2000" onChange={this.handlePropChange} width="68" />
                        </Col>
                      </Row>
                    </div>
                  </Panel.Body>
                </Panel>
              }
              <Panel key={1} eventKey={1}>
                <Panel.Heading>
                  <Panel.Title toggle>Text</Panel.Title>
                </Panel.Heading>
                <Panel.Body collapsible>
                  <div>
                    <SelectLabel id="fontFamily" obj={style} onChange={this.handlePropChange} style={{fontFamily: style.fontFamily}} options={
                      _.map(fonts, f => ({id: f, name: f}))
                    } />
                  </div>
                  <div className="space10">
                    <div style={{display: 'inline-block'}}>
                      <ControlLabel>Size</ControlLabel>
                      <FormControl id="fontSize" value={style.fontSize} onChange={this.setFontSize} type="number" min="6" max="200" style={{width: '75px'}}/>
                    </div>
                    <div style={{display: 'inline-block', marginLeft: '8px'}}>
                      <ControlLabel>Line Height</ControlLabel>
                      <FormControl id="lineHeight" value={style.lineHeight} onChange={this.handlePropChange} type="number" min="0" step="0.1" style={{width: '75px'}}/>
                    </div>
                  </div>
                  <div className="space10">
                    <ControlLabel>Text Color</ControlLabel>
                    <ColorControl color={style.color} disableAlpha={true} onChangeComplete={this.handleColorChange.bind(null, 'color')}/>
                  </div>
                  <div className="space10">
                    <ControlLabel>Link Color</ControlLabel>
                    <ColorControl color={style.linkColor} disableAlpha={true} onChangeComplete={this.handleColorChange.bind(null, 'linkColor')} />
                  </div>
                  <div className="checkbox">
                    <label>
                      <input id="linkUnderline" type="checkbox" checked={style.linkUnderline} onChange={this.handlePropChange} /> Underline Links
                    </label>
                  </div>
                </Panel.Body>
              </Panel>
              { !this.props.form &&
              <Panel key={2} eventKey={2}>
                <Panel.Heading>
                  <Panel.Title toggle>Background</Panel.Title>
                </Panel.Heading>
                <Panel.Body collapsible>
                  <ColorControl color={style.backgroundColor} onChangeComplete={this.handleColorChange.bind(null, 'backgroundColor')}/>
                  <div className="checkbox">
                    <label>
                      <input id="backgroundType" type="checkbox" checked={style.backgroundType === 'img'} onChange={this.onBGChange} /> Use Image
                    </label>
                  </div>
                  <FormControl id="bodyfile" type="file" onChange={this.handleImage} accept="image/*" style={{display: 'none'}}/>
                  <Button className="upload-btn" onClick={this.uploadClick} disabled={this.state.isUploading}>Upload...</Button>
                  {
                  /*
                  <div className="checkbox">
                    <label>
                      <input id="backgroundSize" disabled={style.backgroundType !== 'img'} type="checkbox" checked={style.backgroundSize === 'cover'} onChange={this.onSizeChange} /> Stretch Image
                    </label>
                  </div>*/ // this doesn't work in email clients
                  }
                </Panel.Body>
              </Panel>
              }
              <Panel key={3} eventKey={3}>
                <Panel.Heading>
                  <Panel.Title toggle>Width</Panel.Title>
                </Panel.Heading>
                <Panel.Body collapsible>
                  <div className="radio" style={{marginTop: 0}}>
                    <label>
                      <input id="bodyType" type="radio" value="fixed" checked={style.bodyType === 'fixed'} onChange={this.handlePropChange} /> Fixed Width
                    </label>
                  </div>
                  <FormControlLabel id="bodyWidth" obj={style} disabled={style.bodyType !== 'fixed'} type="number" min="100" onChange={this.handlePropChange} width="75" />
                  <div className="radio">
                    <label>
                      <input id="bodyType" type="radio" value="full" checked={style.bodyType === 'full'} onChange={this.handlePropChange} /> Full Width
                    </label>
                  </div>
                  { !this.props.form &&
                    <FormControlLabel id="paddingTop" obj={style} label="Padding" type="number" min="0" onChange={this.handlePaddingChange} width="75" />
                  }
                  {
                    this.props.form && this.props.designType === 'mobile' &&
                    <SelectLabel id="mobileWidth" label="Design View Width:" obj={style} onChange={this.handlePropChange} disabled={style.bodyType !== 'full'}>
                      <option value="">Large (iPhone 6+)</option>
                      <option value="375">Medium (iPhone 6)</option>
                      <option value="320">Small (iPhone 4/5)</option>
                    </SelectLabel>
                  }
                </Panel.Body>
              </Panel>
            </PanelGroup>
          </Tab>
        </Tabs>
      </div>
    );
  }
}

class DivTable extends Component {
  render() {
    return (
      <table style={{border: 0, margin: 0, padding: 0, width: '100%', borderSpacing: 0, borderCollapse: 'collapse'}}>
        <tr style={{padding: 0, borderSpacing: 0, borderCollapse: 'collapse'}}>
          {
            this.props.innerHTML ?
              <td style={{padding: 0, borderSpacing: 0, borderCollapse: 'collapse', textAlign: this.props.center?'center':undefined, ...this.props.style}}
                dangerouslySetInnerHTML={this.props.innerHTML}/>
            :
              <td style={{paddingTop: 0, paddingRight: 0, paddingBottom: 0, paddingLeft: 0, borderSpacing: 0, borderCollapse: 'collapse', textAlign: this.props.center?'center':undefined, ...this.props.style}}>
                {this.props.children}
              </td>
          }
        </tr>
      </table>
    );
  }
}

export class ReadOnlyTemplateEditor extends Component {
  setIFrameRef = ref => {
    this.iframeRef = ref;
    setTimeout(() => {
      if (this.iframeRef) {
        this.iframeRef.contentWindow.document.open();
        this.iframeRef.contentWindow.document.write(this.getBody(true).__html);
      }
    });
  }

  getBodyStyle() {
    var s = this.getBodyProps();

    var width = s.bodyWidth;
    
    var parts = []
    if (this.props.data) {
      parts = this.props.data.parts;
    }
    for (var p = 0; p < parts.length; p++) {
      var part = parts[p];
      if (part.bodyType === 'fixed' && part.bodyWidth > width) {
        width = part.bodyWidth;
      }
    }

    return {
      width: '100%',
      minWidth: width + 'px',
      boxSizing: 'border-box',
      textAlign: s.align,
      backgroundColor: s.backgroundColor,
      color: s.color,
      fontSize: s.fontSize,
      paddingTop: s.paddingTop,
      paddingBottom: s.paddingBottom,
      paddingRight: s.paddingRight,
      paddingLeft: s.paddingLeft,
      fontFamily: s.fontFamily,
      lineHeight: s.lineHeight,
    };
  }

  getBodyProps() {
    var s = defaultBodyStyle;
    _.extend(s, this.props.data.bodyStyle);
    return s;
  }

  getBody(addPopupCSS) {
    var html;
    if (!this.props.noPopups) {
      html = insertPopups(this.props.data);
      if (addPopupCSS) {
        if (html.search(/<\s*head[^>]*>/i)) {
          html = html.replace(/<\s*head([^>]*)>/i, '<head$1>' + popupCSS());
        } else if (html.search(/<\s*body[^>]*>/i)) {
          html = html.replace(/<\s*body([^>]*)>/i, '<body$1>' + popupCSS());
        } else {
          html = popupCSS() + html;
        }
      }
    } else {
      html = getHTML(this.props.data);
    }

    return {__html: html};
  }

  render() {
    var bp = this.getBodyProps();
    return (
      <div id="TemplateEditor" className="readonly" style={{display: 'flex', position: 'relative', alignItems: 'stretch', marginTop: '45px'}}>
        <table id="Viewer" style={{borderSpacing: 0, borderCollapse: 'collapse', padding: 0, verticalAlign: 'top', textAlign: 'left', height: '100%', width: '100%'}}>
          <tbody>
            <tr style={{padding: 0, verticalAlign: 'top', textAlign: 'left'}}>
              <td style={{borderCollapse: 'collapse', padding: 0, verticalAlign: 'top', textAlign: 'left'}}>
                {
                  (this.props.data && this.props.data.type === 'raw') ?
                    <center>
                      <iframe ref={this.setIFrameRef} title="rawPreview" width="100%" height="500px"/>
                    </center>
                  :
                  ((bp.bodyType === 'fixed' && !bp.version) ?
                    <DivTable center={true} style={this.getBodyStyle()}>
                      <table style={{borderSpacing: 0, borderCollapse: 'collapse', padding: 0, verticalAlign: 'top', width: this.getBodyProps().bodyWidth + 'px', margin: '0 auto'}}>
                        <tbody>
                          <tr style={{padding: 0, verticalAlign: 'top', textAlign: 'left'}}>
                            <td style={{borderCollapse: 'collapse', padding: 0, verticalAlign: 'top', textAlign: 'left'}} dangerouslySetInnerHTML={this.getBody()} />
                          </tr>
                        </tbody>
                      </table>
                    </DivTable>
                  :
                    <DivTable center={true} style={this.getBodyStyle()} innerHTML={this.getBody()}/>)
                }
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }
}

class ColumnConfig extends Component {
  render() {
    var props = this.props;

    return (
      <Row className="colconfig-row" onClick={props.onClick.bind(null, props.widths)}>
        {
          _.map(props.widths, (w, i) => (
            <Col key={i} xs={w} className={i === 0 ? 'colconfig-col-first' : ((i % 2) === 0?'colconfig-col-even':'colconfig-col-odd')} />
          ))
        }
      </Row>
    );
  }
}

export default class TemplateEditor extends Component {
  constructor(props) {
    super(props);

    this.state = {
      nextPart: null,
      showModal: null,
      deletingFooter: false,
      selectedPart: null,
      selectedCol: null,
      selectedColIndex: null,
      showColumnsModal: null,
      windowHeight: document.documentElement.clientHeight,
    }

    this.componentWillReceiveProps(props);
  }

  componentWillReceiveProps(props) {
    if (props.data.initialize && props.user) {
      if (props.form) {
        var input = createPart(true, false, 'Input', '', {placeholder: 'Email address', inputType: 'email', field: 'Email', align: 'center', paddingTop: 10, paddingLeft: 10, paddingRight: 10, paddingBottom: 10});
        input.html = this.getDisplayHTML(input);
        var button = createPart(true, false, 'Button', '', {paddingTop: 10, paddingLeft: 10, paddingRight: 10, paddingBottom: 10});
        button.html = this.getDisplayHTML(button);

        var np = [input, button];
        var c = JSON.parse(JSON.stringify(np));
        this.props.update({initialize: {$set: false}, parts: {$push: np}, mobile: { parts: {$set: c}, bodyStyle: {$set: {bodyType: 'full', bodyWidth: 300, paddingTop: 20, paddingLeft: 20, paddingRight: 20, paddingBottom: 20} } } });
      } else {
        var footer = props.user.lastFooter;
        if (!footer) {
          footer = createPart(props.form, false, 'Text', 'Copyright ' + moment().year() + ' ' + (props.user.companyname || '') + '\n123 Example St.\nExample, EX, USA 12345\n\nIf you no longer wish to receive these messages, you can unsubscribe.', {align: 'center', fontSize: 11});

          const contentState = convertFromRaw(footer.content);
          const contentStateWithEntity = contentState.createEntity(
            'LINK',
            'MUTABLE',
            {url: '{{!!unsublink}}'}
          );
          const entityKey = contentStateWithEntity.getLastCreatedEntityKey();
          const editorState = EditorState.createWithContent(contentStateWithEntity);
          const selection = SelectionState.createEmpty(contentStateWithEntity.getBlocksAsArray()[4].getKey());
          footer.content = convertToRaw(RichUtils.toggleLink(editorState, selection.merge({
            anchorOffset: 57,
            focusOffset: 68,
          }), entityKey).getCurrentContent());
          footer.html = this.getDisplayHTML(footer);
          footer.footer = true;
        } else {
          footer.html = this.getDisplayHTML(footer);
        }

        this.props.update({initialize: {$set: false}, parts: {$push: [createPart(props.form, false, 'Invisible'), footer]}});
      }
    } else if (props.data && props.data.bodyStyle && (!props.data.bodyStyle.version || props.data.bodyStyle.version === 2) && props.data.parts.length) {
      var u = {bodyStyle: {version: {$set: 3}}, parts: {}};
      var a;
      for (var p = 0; p < props.data.parts.length; p++) {
        if (props.data.parts[p].type !== 'Invisible') {
          u.parts[p] = {html: {$set: this.getDisplayHTML(props.data.parts[p])}};
          var pads = ['paddingTop', 'paddingLeft', 'paddingRight', 'paddingBottom'];
          for (a = 0; a < pads.length; a++) {
            if (_.isUndefined(props.data.parts[p][pads[a]])) {
              u.parts[p][pads[a]] = {$set: 10};
            }
          }

          if (props.data.parts[p].type === 'Columns' && props.data.parts[p].parts) {
            var newparts = {};
            for (var sp = 0; sp < props.data.parts[p].parts.length; sp++) {
              var subpart = props.data.parts[p].parts[sp];
              if (!subpart) { continue; }
              if (_.isArray(subpart)) {
                var newsubparts = {};
                for (var ssp = 0; ssp < subpart.length; ssp++) {
                  var subsubpart = subpart[ssp];

                  if (!subsubpart) { continue; }

                  let newpads = {};
                  for (a = 0; a < pads.length; a++) {
                    if (_.isUndefined(subsubpart[pads[a]])) {
                      newpads[pads[a]] = {$set: 10};
                    }
                  }
                  if (_.size(newpads)) {
                    newsubparts[ssp] = newpads;
                  }
                }
                if (_.size(newsubparts)) {
                  newparts[sp] = newsubparts;
                }
              } else {
                let newpads = {};
                for (a = 0; a < pads.length; a++) {
                  if (_.isUndefined(subpart[pads[a]])) {
                    newpads[pads[a]] = {$set: 10};
                  }
                }
                if (_.size(newpads)) {
                  newparts[sp] = newpads;
                }
              }
            }
            if (_.size(newparts)) {
              u.parts[p].parts = newparts;
            }
          }
        }
      }
      this.props.update(u);
    } else if (props.designType && this.props.designType && props.designType !== this.props.designType) {
      this.setState({selectedPart: null, selectedCol: null, selectedColIndex: null});
    }
  }

  setNextPart = part => {
    this.setState({nextPart: part});
  }

  getParts = () => {
    var parts = this.props.data.parts;
    if (this.props.designType === 'mobile') {
      parts = this.props.data.mobile.parts;
    }
    return parts;
  }

  getNextPartType = () => {
    var parts = this.getParts();

    var part = this.state.nextPart;
    if (!part) {
      return null;
    } else if (/^\d+,\d+,\d+$/.test(part)) {
      var [oi, oc, oci] = part.split(',');
      let oldIndex = parseInt(oi, 10);
      let oldColnum = parseInt(oc, 10);
      let oldColIndex = parseInt(oci, 10);

      if ((oldIndex >= parts.length) ||
          (!parts[oldIndex].parts) ||
          (oldColnum >= parts[oldIndex].parts.length) ||
          (_.isArray(parts[oldIndex].parts[oldColnum]) && (oldColIndex >= parts[oldIndex].parts[oldColnum].length))
          ) {
        return null;
      }
      var oldpart = parts[oldIndex].parts[oldColnum];
      if (oldpart === null) {
        return null;
      }
      if (_.isArray(oldpart)) {
        if (oldpart[oldColIndex] === null) {
          return null;
        }
        return oldpart[oldColIndex].type;
      } else {
        return oldpart.type;
      }
    } else if (/^\d+$/.test(part)) {
      let oldIndex = parseInt(part, 10);
      if (oldIndex >= parts.length) {
        return null;
      }
      return parts[oldIndex].type;
    } else {
      return part;
    }
  }

  updateParts = (p, cb) => {
    if (this.props.designType === 'mobile') {
      this.props.update({mobile: {parts: p}}, cb);
    } else {
      this.props.update({parts: p}, cb);
    }
  }

  addPart = (index, colnum, colindex) => {
    var part = this.state.nextPart;

    if (!part)
      return;

    var parts = this.getParts();

    if (/^\d+,\d+,\d+$/.test(part)) {
      var [oi, oc, oci] = part.split(',');
      let oldIndex = parseInt(oi, 10);
      let oldColnum = parseInt(oc, 10);
      let oldColIndex = parseInt(oci, 10);

      let existing = parts[oldIndex].parts[oldColnum];
      if (_.isArray(existing)) {
        existing = existing[oldColIndex];
      }

      if (colnum === null) {
        let newparts = _.map(parts, (part, i) => {
          if (i === oldIndex) {
            if (_.isArray(part.parts[oldColnum])) {
              return update(part, {parts: {[oldColnum]: {$splice: [[oldColIndex, 1]]}}});
            } else {
              return update(part, {parts: {[oldColnum]: {$set: []}}});
            }
          } else {
            return part;
          }
        });
        newparts.splice(index, 0, existing);
        this.updateParts({$set: newparts});
      } else {
        let newparts = _.map(parts, (part, i) => {
          if (oldIndex === index && oldColnum === colnum && i === index) {
            if (oldColIndex === colindex) {
              return part;
            } else if (oldColIndex > colindex) {
              return update(part, {parts: {[colnum]: {$set: update(part.parts[colnum], {$splice: [[oldColIndex, 1], [colindex, 0, existing]]})}}});          
            } else {
              return update(part, {parts: {[colnum]: {$set: update(part.parts[colnum], {$splice: [[oldColIndex, 1], [colindex - 1, 0, existing]]})}}});          
            }
          } else if (oldIndex === index && i === index) {
            if (_.isArray(part.parts[colnum]) && _.isArray(part.parts[oldColnum])) {
              return update(part, {parts: {[colnum]: {$splice: [[colindex, 0, existing]]}, [oldColnum]: {$splice: [[oldColIndex, 1]]}}});          
            } else if (_.isArray(part.parts[colnum])) {
              return update(part, {parts: {[colnum]: {$splice: [[colindex, 0, existing]]}, [oldColnum]: {$set: []}}});          
            } else if (_.isArray(part.parts[oldColnum])) {
              if (part.parts[colnum] === null) {
                return update(part, {parts: {[colnum]: {$set: [existing]}, [oldColnum]: {$splice: [[oldColIndex, 1]]}}});          
              } else if (colindex === 0) {
                return update(part, {parts: {[colnum]: {$set: [existing, part.parts[colnum]]}, [oldColnum]: {$splice: [[oldColIndex, 1]]}}});          
              } else {
                return update(part, {parts: {[colnum]: {$set: [part.parts[colnum], existing]}, [oldColnum]: {$splice: [[oldColIndex, 1]]}}});          
              }
            } else {
              if (part.parts[colnum] === null) {
                return update(part, {parts: {[colnum]: {$set: [existing]}, [oldColnum]: {$set: []}}});
              } else if (colindex === 0) {
                return update(part, {parts: {[colnum]: {$set: [existing, part.parts[colnum]]}, [oldColnum]: {$set: []}}});
              } else {
                return update(part, {parts: {[colnum]: {$set: [part.parts[colnum], existing]}, [oldColnum]: {$set: []}}});
              }
            }
          } else if (i === index) {
            if (_.isArray(part.parts[colnum])) {
              return update(part, {parts: {[colnum]: {$splice: [[colindex, 0, existing]]}}});          
            } else {
              if (part.parts[colnum] === null) {
                return update(part, {parts: {[colnum]: {$set: [existing]}}});
              } else if (colindex === 0) {
                return update(part, {parts: {[colnum]: {$set: [existing, part.parts[colnum]]}}});
              } else {
                return update(part, {parts: {[colnum]: {$set: [part.parts[colnum], existing]}}});
              }
            }
          } else if (i === oldIndex) {
            if (_.isArray(part.parts[oldColnum])) {
              return update(part, {parts: {[oldColnum]: {$splice: [[oldColIndex, 1]]}}});
            } else {
              return update(part, {parts: {[oldColnum]: {$set: []}}});
            }
          } else {
            return part;
          }
        });
        this.updateParts({$set: newparts});
      }
    } else if (/^\d+$/.test(part)) {
      let oldIndex = parseInt(part, 10);
      let existing = parts[oldIndex];
      if (colnum === null) {
        if (oldIndex === index) {
          return;
        } else if (oldIndex > index) {
          this.updateParts({$splice: [[oldIndex, 1], [index, 0, existing]]});
        } else {
          this.updateParts({$splice: [[oldIndex, 1], [index - 1, 0, existing]]});
        }
      } else {
        let newparts = _.map(parts, (part, i) => {
          if (i === index) {
            if (_.isArray(part.parts[colnum])) {
              return update(part, {parts: {[colnum]: {$splice: [[colindex, 0, existing]]}}});
            } else {
              if (part.parts[colnum] === null) {
                return update(part, {parts: {[colnum]: {$set: [existing]}}});
              } else if (colindex === 0) {
                return update(part, {parts: {[colnum]: {$set: [existing, part.parts[colnum]]}}});
              } else {
                return update(part, {parts: {[colnum]: {$set: [part.parts[colnum], existing]}}});
              }
            }
          } else {
            return part;
          }
        });
        newparts.splice(oldIndex, 1);
        this.updateParts({$set: newparts});
      }
    } else {
      if (part === "Columns") {
        this.setState({showColumnsModal: {part: part, index: index}});
      } else {
        var newPart = createPart(this.props.form, colnum !== null, part);
        newPart.html = this.getDisplayHTML(newPart);
        if (colnum === null) {
          this.updateParts({$splice: [[index, 0, newPart]]});
        } else {
          if (_.isArray(parts[index].parts[colnum])) {
            this.updatePart(parts[index].id, {
              parts: update(parts[index].parts, {[colnum]: {$splice: [[colindex, 0, newPart]]}}),
            });
          } else {
            if (parts[index].parts[colnum] === null) {
              this.updatePart(parts[index].id, {
                parts: update(parts[index].parts, {[colnum]: {$set: [newPart]}}),
              });
            } else if (colindex === 0) {
              this.updatePart(parts[index].id, {
                parts: update(parts[index].parts, {[colnum]: {$set: [newPart, parts[index].parts[colnum]]}}),
              });
            } else {
              this.updatePart(parts[index].id, {
                parts: update(parts[index].parts, {[colnum]: {$set: [parts[index].parts[colnum], newPart]}}),
              });
            }
          }
        }
      }
    }
  }

  cancelColumnsClicked = () => {
    this.setState({showColumnsModal: null});
  }

  confirmColumnsClicked = widths => {
    var {part, index} = this.state.showColumnsModal;

    this.setState({showColumnsModal: null});

    var parts = [];
    for (var i = 0; i < widths.length; i++) {
      parts.push([]);
    }

    var newPart = createPart(this.props.form, false, part, null, {
      parts: parts,
      widths: widths,
    });
    newPart.html = this.getDisplayHTML(newPart);
    this.updateParts({$splice: [[index, 0, newPart]]});
  }

  updatePart = (id, pr, cb) => {
    var newparts = _.map(this.getParts(), (part, i) => {
      if (part.id !== id)
        return part;
      var d = {$unset: []};
      for (var p in pr) {
        if (canInherit[p] && pr[p] === this.getBodyStyle(p))
          d.$unset.push(p);
        else
          d[p] = {$set: pr[p]};
      }
      if (d.$unset.length === 0)
        delete(d.$unset);
      var newPart = update(part, d);
      newPart.html = this.getDisplayHTML(newPart);
      return newPart;
    });
    this.updateParts({$set: newparts}, cb);
  }

  getDisplayHTML = (part) => {
    var div = document.createElement('div');
    ReactDOM.render(<PartDisplay
                        index={0}
                        displayOnly={true}
                        {...part}
                        getPartStyles={this.getPartStyles}
                        getPartStylesDisplay={this.getPartStylesDisplay}
                        highlight={false}
                        isInCol={false}
                        />, div);
    div.children[0].removeAttribute("data-reactroot");
    return div.innerHTML;
  }

  getPartStyles = (props) => {
    var r = _.clone(props);
    _.each(this.getBodyStyles(true), (val, prop) => {
      if (!prop.startsWith("background") && _.isUndefined(r[prop]))
        r[prop] = val;
    });
    return r;
  }

  getPartStylesDisplay = (props) => {
    var r = this.getPartStyles(props);
    _.each(r, (val, prop) => {
      if (needsPixels[prop] && val !== '')
        r[prop] = val + 'px';
    });
    return r;
  }

  removePart = () => {
    this.setState({showModal: this.state.selectedPart, deletingFooter: this.getParts()[this.state.selectedPart].footer});
  }

  confirmClicked = yes => {
    var selind = this.state.showModal;
    this.setState({showModal: null, selectedPart: null});

    if (yes) {
      if (this.getParts()[selind].footer) {
        this.updateParts({$splice: [[selind-1, 2]]});
      } else {
        this.updateParts({$splice: [[selind, 1]]});
      }
    }
  }

  movePartUp = cb => {
    var selind = this.state.selectedPart;
    this.setState({selectedPart: selind - 1}, () => {
      var part = this.getParts()[selind];
      this.updateParts({$splice: [[selind, 1], [selind-1, 0, part]]}, cb);
    });
  }

  movePartDown = cb => {
    var selind = this.state.selectedPart;
    this.setState({selectedPart: selind + 1}, () => {
      var part = this.getParts()[selind];
      this.updateParts({$splice: [[selind, 1], [selind+1, 0, part]]}, cb);
    });
  }

  duplicatePart = () => {
    var selind = this.state.selectedPart;
    var newpart = JSON.parse(JSON.stringify(this.getParts()[selind]));
    newpart.id = shortid.generate();
    this.updateParts({$splice: [[selind+1, 0, newpart]]});
  }

  getBodyStyle = prop => {
    var bodyStyle = this.props.data.bodyStyle;
    if (this.props.designType === 'mobile') {
      bodyStyle = this.props.data.mobile.bodyStyle;
    }

    var val;
    if (this.props.data && bodyStyle) {
      val = bodyStyle[prop];
    }
    if (_.isUndefined(val)) {
      val = defaultBodyStyle[prop];
    }
    return val;
  }

  getBodyStyles = (forpart) => {
    var bodyStyle = this.props.data.bodyStyle;
    if (this.props.designType === 'mobile') {
      bodyStyle = this.props.data.mobile.bodyStyle;
    }

    var r = {};
    var ver3 = this.props.data && bodyStyle.version === 3;

    if (ver3) {
      _.each(_.keys(defaultBodyStyle), prop => {
        if (!forpart || !/^padding/.test(prop)) {
          r[prop] = this.getBodyStyle(prop);
        } else {
          r[prop] = 0;
        }
      });
    } else {
      _.each(_.keys(defaultBodyStyle), prop => {
        r[prop] = this.getBodyStyle(prop);
      });
      if (forpart) {
        _.each(_.keys(defaultPartStyle), prop => {
          r[prop] = defaultPartStyle[prop];
        });
      }
    }
    return r;
  }

  getBodyStylesDisplay = () => {
    var r = this.getBodyStyles();
    _.each(_.keys(r), prop => {
      var val = r[prop];
      if (isDefault(prop, val))
        delete(r[prop]);
      else if (needsPixels[prop] && val !== '')
        r[prop] = val + 'px';
    });
    return r;
  }

  setBodyStyle = (...args) => {
    var p = {};
    for (var i = 0; i < args.length; i += 2) {
      var prop = args[i];
      var val = args[i + 1]

      p[prop] = {$set: val};
    }

    var spec = {bodyStyle: p};
    if (this.props.designType === 'mobile') {
      spec = {mobile: spec};
    }

    this.props.update(spec, () => {
      var newparts = _.map(this.getParts(), (part, i) => {
        if (part.type === 'Invisible') {
          return part;
        } else {
          return update(part, {html: {$set: this.getDisplayHTML(part)}});
        }
      });
      this.updateParts({$set: newparts});
    });
  }

  setSelection = (index, colnum, colindex) => {
    if (index === this.state.selectedPart && colnum === this.state.selectedCol && colindex === this.state.selectedColIndex) {
      this.setState({selectedPart: null, selectedCol: null, selectedColIndex: null});
    } else {
      this.setState({selectedPart: index, selectedCol: colnum, selectedColIndex: colindex});
    }
  }

  clearSelection = (cb) => {
    this.setState({selectedPart: null, selectedCol: null, selectedColIndex: null}, cb);
  }

  render() {
    const {readOnly} = this.props;

    var drawer = <PartDrawer setNextPart={this.setNextPart}
                             clearSelection={this.clearSelection}
                             getStyle={this.getBodyStyles}
                             setStyle={this.setBodyStyle}
                             designType={this.props.designType}
                             form={this.props.form} />

    return (
      <div id="TemplateEditor" className={this.props.fixed?"fixed-editor":undefined} style={{display: 'flex', alignItems: 'stretch'}}>
        {
          !this.props.fixed && drawer
        }
        <Viewer addPart={this.addPart}
                designType={this.props.designType}
                fixed={this.props.fixed}
                fields={this.props.fields}
                transactional={this.props.transactional}
                form={this.props.form}
                sideWidth={this.props.sideWidth}
                getDisplayHTML={this.getDisplayHTML}
                nextPartType={this.getNextPartType()}
                getBodyStylesDisplay={this.getBodyStylesDisplay}
                getBodyStyle={this.getBodyStyle}
                removePart={this.removePart}
                setNextPart={this.setNextPart}
                parts={this.getParts()}
                initialize={this.props.data.initialize}
                updatePart={this.updatePart}
                getPartStyles={this.getPartStyles}
                getPartStylesDisplay={this.getPartStylesDisplay}
                nextPart={this.state.nextPart}
                disabled={readOnly}
                movePartUp={this.movePartUp}
                movePartDown={this.movePartDown}
                duplicatePart={this.duplicatePart}
                selectedPart={this.state.selectedPart}
                selectedCol={this.state.selectedCol}
                selectedColIndex={this.state.selectedColIndex}
                setSelection={this.setSelection}
                clearSelection={this.clearSelection}
                partDrawer={this.props.fixed?drawer:undefined}
          />
          {
            this.state.showModal !== null &&
              <Modal show={true}>
                <Modal.Header>
                  {
                    this.state.deletingFooter ?
                      <Modal.Title>Delete Footer Confirmation</Modal.Title>
                    :
                      <Modal.Title>Delete Component Confirmation</Modal.Title>
                  }
                </Modal.Header>
                <Modal.Body>
                  {
                    this.state.deletingFooter ?
                      <p>Are you sure you want to delete the footer component? Any changes you make to this footer will be carried over to your next template.</p>
                    :
                      <p>Are you sure you want to delete this component?</p>
                  }
                </Modal.Body>
                <Modal.Footer>
                  <Button onClick={this.confirmClicked.bind(this, true)} bsStyle="primary">Yes</Button>
                  <Button onClick={this.confirmClicked.bind(this, false)}>No</Button>
                </Modal.Footer>
              </Modal>
          }
          {
            this.state.showColumnsModal !== null &&
              <Modal show={true}>
                <Modal.Header>
                  <Modal.Title>
                    Choose Column Configuration
                    <span className="pull-right fa fa-remove" style={{cursor: 'pointer'}} onClick={this.cancelColumnsClicked} />
                  </Modal.Title>
                </Modal.Header>
                <Modal.Body>
                  <Tabs defaultActiveKey={2} animation={false} id="column-tabs" bsStyle="pills">
                    <Tab eventKey={1} title="1 Column">
                      <div style={{paddingTop: '20px'}}>
                        <p>Select a layout:</p>
                        <ColumnConfig widths={[12]} onClick={this.confirmColumnsClicked} />
                      </div>
                    </Tab>
                    <Tab eventKey={2} title="2 Columns">
                      <div style={{paddingTop: '20px'}}>
                        <p>Select a layout:</p>
                        <ColumnConfig widths={[6, 6]} onClick={this.confirmColumnsClicked} />
                        <ColumnConfig widths={[9, 3]} onClick={this.confirmColumnsClicked} />
                        <ColumnConfig widths={[8, 4]} onClick={this.confirmColumnsClicked} />
                        <ColumnConfig widths={[4, 8]} onClick={this.confirmColumnsClicked} />
                        <ColumnConfig widths={[3, 9]} onClick={this.confirmColumnsClicked} />
                      </div>
                    </Tab>
                    <Tab eventKey={3} title="3 Columns">
                      <div style={{paddingTop: '20px'}}>
                        <p>Select a layout:</p>
                        <ColumnConfig widths={[4, 4, 4]} onClick={this.confirmColumnsClicked} />
                        <ColumnConfig widths={[3, 6, 3]} onClick={this.confirmColumnsClicked} />
                        <ColumnConfig widths={[6, 3, 3]} onClick={this.confirmColumnsClicked} />
                        <ColumnConfig widths={[3, 3, 6]} onClick={this.confirmColumnsClicked} />
                      </div>
                    </Tab>
                    <Tab eventKey={4} title="4 Columns">
                      <div style={{paddingTop: '20px'}}>
                        <p>Select a layout:</p>
                        <ColumnConfig widths={[3, 3, 3, 3]} onClick={this.confirmColumnsClicked} />
                      </div>
                    </Tab>
                  </Tabs>
                  <p>You can edit the columns later by clicking the <i style={{
                    fontSize: '22px', padding: '3px', border: '1px solid', borderRadius: '3px'
                  }} className="fa fa-pencil"/> icon for the component.</p>
                </Modal.Body>
              </Modal>
          }
      </div>
    );
  }
}
