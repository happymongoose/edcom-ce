import React, { Component } from "react";
import parse from "../utils/parse";
import update from 'immutability-helper';
import _ from "underscore";

export default ({extend: ExtendedComponent, initial, get, extra, extramerge, post, patch, merge}) => {
  return class extends Component {
    constructor(props) {
      super(props);

      var p = this.mergeParams(initial);

      this.state = {
        p: p,
        data: initial,
        isLoading: true,
        isSaving: false,
      }

      this._loadedCB = null;
      this._formRef = null;
      this._formClose = false;
    }

    mergeParams(obj) {
      var p = parse(this);
      _.extend(p, this.props.match ? this.props.match.params : {});

      _.each(p, (v, k) => {
        if (k !== 'id') {
          obj[k] = v;
        }
      });

      _.extend(obj, merge);

      return p;
    }

    componentWillMount() {
      this.reloadData();
    }

    reloadExtra = async () => {
        if (extra) {
          var s = {
            extra: {}
          };
          var promises = [];
          var n;
          for (n in extra) {
            promises.push(extra[n]({...this.state.p}));
          }
          var results = await Promise.all(promises);
          for (n in extra) {
            s.extra[n] = results.shift();
          }
          this.setState(s);
        }
    }

    reloadData = async () => {
      try {
        var s = {
          extra: {}
        };
        
        var promises = [];
        var n;
        if (extra) {
          for (n in extra) {
            promises.push(extra[n]({...this.state.p}));
          }
        }
        if (this.state.p.id !== 'new' && get) {
          promises.push(get({...this.state.p}));
        }

        var results = await Promise.all(promises);

        if (extra) {
          for (n in extra) {
            s.extra[n] = results.shift();
          }
        }

        if (this.state.p.id !== 'new') {
          if (get) {
            s.data = results.shift();
            this.mergeParams(s.data);
          }
        } else {
          s.data = _.clone(this.state.data);
        }

        function finddata(e, ex) {
          return ex.id === s.data[e];
        }

        for (var e in extramerge) {
          if (!s.data[e] || !_.find(s.extra[extramerge[e]], finddata.bind(null, e))) {
            if (s.extra[extramerge[e]].length)
              s.data[e] = s.extra[extramerge[e]][0].id;
            else
              s.data[e] = '';
          }
        }

        this.setState(s);
      } finally {
        this.setState({isLoading: false}, this._loadedCB);
      }
    }

    setLoadedCB = cb => {
      this._loadedCB = cb;
    }

    updateData = (u, cb) => {
      this.setState({ data: update(this.state.data, u) }, cb);
    }

    saveData = async m => {
      this.setState({ isSaving: true });

      const d = _.extend(this.state.data, m);

      try {
        if (this.state.p.id === 'new') {
          return await post({data: d, ...this.state.p});
        } else {
          return await patch({data: d, ...this.state.p});
        }
      } finally {
        this.setState({ isSaving: false });
      }
    }

    formRef = r => {
      this._formRef = r;
    }

    formSubmit = close => {
      if (_.isBoolean(close) && close) {
        this._formClose = true;
      } else {
        this._formClose = false;
      }
      this._formRef.childNodes[0].click();
    }

    formClose = event => {
      event.preventDefault();

      return this._formClose;
    }

    render() {
      return <ExtendedComponent id={this.state.p.id} data={this.state.data} update={this.updateData} save={this.saveData} reload={this.reloadData} reloadExtra={this.reloadExtra} isLoading={this.state.isLoading} isSaving={this.state.isSaving} setLoadedCB={this.setLoadedCB} formRef={this.formRef} formSubmit={this.formSubmit} formClose={this.formClose} {...this.state.extra} {...this.props} />
    }
  }
}
