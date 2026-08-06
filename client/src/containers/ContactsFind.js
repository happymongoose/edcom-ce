import React, { Component } from "react";
import axios from "axios";
import { Checkbox, FormControl, MenuItem, Modal, Button } from "react-bootstrap";
import LoaderPanel from "../components/LoaderPanel";
import LoaderButton from "../components/LoaderButton";
import LoaderIcon from "../components/LoaderIcon";
import withLoadSave from "../components/LoadSave";
import getvalue from "../utils/getvalue";
import _ from "underscore";
import SaveNavbar from "../components/SaveNavbar";
import { EDFormSection, EDFormBox, EDFormGroup } from "../components/EDDOM";
import delay from "timeout-as-promise";
import notify from "../utils/notify";
import update from "immutability-helper";
import ReactTable from "react-table";
import fixTag from "../utils/fixtag";
import Select2 from "react-select2-wrapper";
import shortid from "shortid";
import moment from "moment";
import SearchControl from "../components/SearchControl";
import ConfirmDropdown from "../components/ConfirmDropdown";

import "react-select2-wrapper/css/select2.css";
import {Link} from "react-router-dom";

const PAGE_SIZE = 50;

function ValueCell({prop, value, listid, ...props}) {
  if (prop === '!!tags') {
    if (value) {
      var tags = value.split(',');
      return (
        <span>
        {
          tags.map(t => {
            return <span key={t} className="tag-value">{t}</span>;
          })
        }
        </span>
      );
    } else {
      return <span/>
    }
  } else if (prop === 'Email') {
    return <Link to={'/contacts/editcontact?id=' + value + '&listid=' + listid} style={{fontSize: 'inherit'}}>{value}</Link>;
  } else if (value === 'true') {
    return <i className="fa fa-check-square-o" />;
  } else {
    return <span>{value}</span>;
  }
}

class ContactsFind extends Component {
  constructor(props) {
    super(props);

    this.state = {
      isSearching: false,
      isPaging: false,
      search: '',
      searchedData: null,
      result: null,
      tags: [],
      selected: {},
      selectAll: false,
      showConfirm: false,
      saving: false,
      filter: 'Active',
      tagModal: null,
    }

    this.props.setLoadedCB(this.handleSearch);
  }

  previous = () => {
    this.handleSearch(this.state.result.rows[0].Email)
  }

  next = () => {
    this.handleSearch(undefined, this.state.result.rows[this.state.result.rows.length - 1].Email)
  }

  onHeaderCheckChange = e => {
    var val = getvalue(e);
    var p = {selectAll: val};
    if (!val)
      p.selected = {};
    this.setState(p);
  }

  onCheckChange = e => {
    var val = getvalue(e);
    var p = {};
    p.selected = update(this.state.selected, {[e.target.id]: {$set: val}});
    this.setState(p);
  }

  isSelected = s => {
    return this.state.selectAll || this.state.selected[s.Email] || false;
  }

  selectedCount = () => {
    var cnt = 0;
    for (var i in this.state.selected) {
      if (this.state.selected[i])
        cnt++;
    }
    return cnt;
  }

  searchToSegment = (search, filter, sort, before, after) => {
    let p = {
      parts: [{
        id: shortid.generate(),
        type: 'Info',
        tag: '',
        prop: '!!*',
        operator: 'contains',
        value: search,
        addedtype: 'inpast',
        addednum: 30,
        addedstart: moment().subtract(30, 'days').format(),
        addedend: moment().format(),
      }],
      operator: 'and',
      subset: false,
      subsettype: 'percent',
      subsetpct: 10,
      subsetnum: 2000,
      sort,
      before,
      after,
    };

    if (filter === 'Active') {
      p.parts.push({
        id: shortid.generate(),
        tag: '',
        prop: 'Bounced',
        test: '',
        type: 'Info',
        value: 'true',
        addedend: moment().format(),
        addednum: 30,
        operator: 'notequals',
        addedtype: 'inpast',
        addedstart: moment().subtract(30, 'days').format(),
        addl: [
          {
            tag: '',
            prop: 'Unsubscribed',
            test: '',
            type: 'Info',
            value: 'true',
            addedend: moment().format(),
            addednum: 30,
            operator: 'notequals',
            addedtype: 'inpast',
            addedstart: moment().subtract(30, 'days').format(),
          },
          {
            tag: '',
            prop: 'Complained',
            test: '',
            type: 'Info',
            value: 'true',
            addedend: moment().format(),
            addednum: 30,
            operator: 'notequals',
            addedtype: 'inpast',
            addedstart: moment().subtract(30, 'days').format(),
          },
        ],
      })
    } else {
      p.parts.push({
        id: shortid.generate(),
        tag: '',
        prop: filter === 'Hard Bounced' ? 'Bounced' : filter,
        test: '',
        type: 'Info',
        value: 'true',
        addedend: moment().format(),
        addednum: 30,
        operator: 'equals',
        addedtype: 'inpast',
        addedstart: moment().subtract(30, 'days').format(),
      });
    }

    return p;
  }

  doSearch = async segment => {
    var ret = (await axios.post('/api/lists/' + this.props.id + '/find', segment)).data;
    if (ret.result) {
      return this.doSearchFinish(segment, ret.result);
    } else {
      var id = ret.id;

      while (true) {
        await delay(2000);

        var results = (await axios.get('/api/listfind/' + id)).data;

        if (results.error) {
          notify.show(results.error, "error");
          return;
        } else if (results.complete) {
          return this.doSearchFinish(segment, results.result);
        }
      }
    }
  }

  doSearchFinish = async (segment, result) => {
    if (result.rows.length < PAGE_SIZE && result.has_next) {
      // something went wrong with the paging, reset to first page and run again
      segment.before = undefined;
      segment.after = undefined;
      return this.doSearch(segment);
    }

    this.setState({result});
  }

  redoSearch = async () => {
    return this.handleSearch(this.state.searchedData.before, this.state.searchedData.after);
  }

  handleSearch = async (before, after) => {
    const segment = this.searchToSegment(this.state.search, this.state.filter, {id: 'Email', desc: false}, before, after);
    this.setState({isSearching: true, isPaging: !!(before || after), searchedData: segment});

    try {
      await this.doSearch(segment, before, after);
    } finally {
      this.setState({isSearching: false, isPaging: false});
    }

    this.setState({mode: 'results'});
  }

  goBack = () => {
    this.props.history.push('/contacts');
  }

  editContact = () => {
    this.props.history.push('/contacts/editcontact?id=' + _.filter(_.keys(this.state.selected), e => this.state.selected[e])[0] + '&listid=' + this.props.id);
  }

  onTagChange = event => {
    this.setState({tags: getvalue(event)});
  }

  addTagsAll = async () => {
    try {
      await axios.post('/api/lists/' + this.props.id + '/tag', {
        segment: this.state.searchedData,
        tags: this.state.tags,
      });
      notify.show("Tag request submitted", "success");
    } finally {
      this.setState({tagModal: null});
    }
  }

  removeTagsAll = async () => {
    try {
      await axios.post('/api/lists/' + this.props.id + '/tag', {
        segment: this.state.searchedData,
        removetags: this.state.tags,
      });
      notify.show("Untag request submitted", "success");
    } finally {
      this.setState({tagModal: null});
    }
  }

  addTagsSel = async () => {
    try {
      await axios.post('/api/lists/' + this.props.id + '/tag', {
        emails: _.filter(_.keys(this.state.selected), e => this.state.selected[e]),
        tags: this.state.tags,
      });
      notify.show("Contact(s) tagged", "success");
    } finally {
      this.setState({tagModal: null}, () => {
        this.redoSearch();
      });
    }
  }

  removeTagsSel = async () => {
    try {
      await axios.post('/api/lists/' + this.props.id + '/tag', {
        emails: _.filter(_.keys(this.state.selected), e => this.state.selected[e]),
        removetags: this.state.tags,
      });
      notify.show("Contact(s) untagged", "success");
    } finally {
      this.setState({tagModal: null}, () => {
        this.redoSearch();
      });
    }
  }

  searchChanged = value => {
    this.setState({search: value}, () => {
      this.handleSearch();
    });
  }

  filterChanged = event => {
    this.setState({filter: getvalue(event)}, () => {
      this.handleSearch();
    });
  }

  selectionDesc = () => {
    let result = this.state.result;

    let selcount = this.selectedCount();

    let sa = this.state.selectAll;

    if (sa) {
      return 'all ' + result.count.toLocaleString() + ' contact' + (result.count===1?'':'s');
    } else {
      return selcount.toLocaleString() + ' selected contact' + (selcount===1?'':'s');
    }
  }

  deleteAllConfirmed = async () => {
    await axios.post('/api/lists/' + this.props.id + '/bulkdelete', {
      segment: this.state.searchedData
    });
    notify.show("Delete request submitted", "success");
  }

  deleteSelConfirmed = async () => {
    await axios.post('/api/lists/' + this.props.id + '/bulkdelete', {
      emails: _.filter(_.keys(this.state.selected), e => this.state.selected[e]),
    });
    notify.show("Contact(s) deleted", "success");
    this.redoSearch();
  }

  tagModalClicked = () => {
    this.setState({tagModal: 'tag'});
  }

  untagModalClicked = () => {
    this.setState({tagModal: 'untag'});
  }

  render() {
    var result = this.state.result;

    let columns = [{
      Header: <Checkbox className="nomargin" checked={this.state.selectAll}
                        onChange={this.onHeaderCheckChange} disabled={this.state.isPaging} />,
      accessor: '',
      Cell: ({...props}) => {
        return <Checkbox className="nomargin" id={props.original.Email} checked={this.isSelected(props.original)}
                         onChange={this.onCheckChange} disabled={this.state.selectAll || this.state.isPaging} />;
      },
      width: 35,
    }];

    if (result && result.allprops) {
      _.map(result.allprops, (p, i) => {
        columns.push({
          Header: p === '!!tags' ? 'Tags' : p,
          headerClassName: i === 0?'text-left':'text-center',
          className: i === 0?'text-left':'text-center',
          Cell: ({...props}) => <ValueCell prop={p} value={props.value} listid={this.props.id} />,
          accessor: p,
        });
      });
    }

    let selcount = this.selectedCount();

    let sa = this.state.selectAll;

    let listName = this.props.list && (this.props.list.name || '')

    return (
      <SaveNavbar title={`Search for Contacts ${listName ? 'in ' + listName : ''}`}
                  hideSave={true} onBack={this.goBack} user={this.props.user}>
        <LoaderPanel isLoading={this.props.isLoading}>
          <EDFormSection onSubmit={e => e.preventDefault()}>
            <EDFormBox className="wide">
              <EDFormGroup className="text-center">
                <Modal bsSize="large" show={!!this.state.tagModal} onHide={() => this.setState({tagModal: null})}>
                  <Modal.Body>
                    <Select2
                      multiple
                      value={this.state.tags}
                      data={this.props.tags}
                      onChange={this.onTagChange}
                      style={{width:'100%'}}
                      options={{
                        tags: true,
                        placeholder: "Enter tags here",
                        createTag: function (params) {
                          const fixed = fixTag(params.term);
                          if (!fixed) {
                            return null;
                          }
                          return {
                            id: fixTag(params.term),
                            text: fixTag(params.term)
                          }
                        }
                      }}
                    />
                  </Modal.Body>
                  <Modal.Footer>
                    <LoaderButton onClick={
                      this.state.tagModal === 'tag' ? 
                        (sa?this.addTagsAll:this.addTagsSel) :
                        (sa?this.removeTagsAll:this.removeTagsSel)
                    }
                      text={
                        this.state.tagModal === 'tag' ?
                        (sa?
                          <span>
                            Add Tag{this.state.tags.length===1?'':'s'} To All {result.count.toLocaleString()} Contacts
                          </span>
                        :
                          <span>
                            Add Tag{this.state.tags.length===1?'':'s'} To {selcount===0?'Selected':selcount} Contacts
                          </span>
                        ) :
                        (sa ?
                          <span>
                            Remove Tag{this.state.tags.length===1?'':'s'} From All {result.count.toLocaleString()} Contacts
                          </span>
                          :
                          <span>
                            Remove Tag{this.state.tags.length===1?'':'s'} From {selcount===0?'Selected':selcount} Contact{selcount===1?'':'s'}
                          </span>
                        )
                      }
                      disabled={!this.state.tags.length}
                      loadingText={this.state.tagModal === 'tag' ? "Tagging..." : 'untag'}
                      id="tag-button"
                    />
                    <Button onClick={() => this.setState({tagModal: null})}>Cancel</Button>
                  </Modal.Footer>
                </Modal>
                <div style={{display: 'flex', justifyContent: 'space-between'}}>
                  <ConfirmDropdown
                    id={'actions-split'}
                    menu="Delete"
                    extra={true}
                    disabled={!sa && !selcount}
                    title="Delete Contacts Confirmation"
                    prompt={"Are you sure you wish to delete " + this.selectionDesc() + "?"}
                    onConfirm={sa ? this.deleteAllConfirmed : this.deleteSelConfirmed}
                    left={true}
                    text="Actions">
                    <MenuItem disabled={!sa && !selcount} onClick={this.tagModalClicked}>Tag...</MenuItem>
                    <MenuItem disabled={!sa && !selcount} onClick={this.untagModalClicked}>Untag...</MenuItem>
                    <MenuItem disabled={sa || selcount !== 1} onClick={this.editContact}>Edit...</MenuItem>
                  </ConfirmDropdown>
                  <div style={{display: 'flex', gap: '12px'}}>
                    <FormControl id="filter" componentClass="select" value={this.state.filter} onChange={this.filterChanged} style={{width: 'auto'}}>
                      <option>Active</option>
                      <option>Unsubscribed</option>
                      <option>Complained</option>
                      <option>Hard Bounced</option>
                      <option>Soft Bounced</option>
                    </FormControl>
                    <SearchControl value={this.state.search} onChange={this.searchChanged} />
                  </div>
                </div>
              </EDFormGroup>
              {
                (this.state.isSearching && !this.state.isPaging) &&
                <div className="text-center">
                  <h4>Please be patient while our highly trained badgers are combing through your vast data repository...</h4>
                  <LoaderIcon />
                </div>
              }
              {
              ((!this.state.isSearching || this.state.isPaging) && result) &&
              (!result.rows.length ?
              <h4 className="text-center">
                No data found for query
              </h4>
              :
              <div>
                <h5>
                  Displaying {result.rows.length} of {result.count.toLocaleString()} matching contacts
                </h5>
                <ReactTable
                  data={result.rows}
                  columns={columns}
                  minRows={0}
                  multiSort={false}
                  showPagination={false}
                  defaultPageSize={PAGE_SIZE}
                  sortable={false}
                />
                {
                  result.rows.length < result.count &&
                  <div className="form-inline space-bottom space15" style={{display: 'flex', justifyContent: 'space-between'}}>
                    <Button style={{width: '120px'}} onClick={this.previous} disabled={!result.has_previous || this.state.isPaging}>Previous</Button>
                    {
                      this.state.isPaging &&
                      <span>
                        <LoaderIcon />{' '}Loading {this.state.searchedData.before ? 'previous' : 'next'} page, please wait...
                      </span>
                    }
                    <Button style={{width: '120px'}} onClick={this.next} disabled={!result.has_next || this.state.isPaging}>Next</Button>
                  </div>
                }
              </div>)
              }
            </EDFormBox>
          </EDFormSection>
        </LoaderPanel>
      </SaveNavbar>
    );
  }
}

export default withLoadSave({
  initial: [],
  extend: ContactsFind,
  extra: {
    list: async ({id}) => (await axios.get('/api/lists/' + id)).data,
    tags: async() => (await axios.get('/api/recenttags')).data,
  },
});
