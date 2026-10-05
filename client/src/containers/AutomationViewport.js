import React, {Component} from 'react';
import {Button} from 'react-bootstrap';
import './AutomationViewport.css';
import AutomationStepFinder from './AutomationStepFinder';

// View preferences only. No canonical workflow data is changed here.
export default class AutomationViewport extends Component {
  state = {scale: 1, height: 0, panning: false};
  componentDidMount() {
    window.addEventListener('resize', this.measure);
    document.addEventListener('mousemove', this.pan);
    document.addEventListener('mouseup', this.stopPan);
    window.addEventListener('blur', this.stopPan);
    if (window.ResizeObserver) {
      this.observer = new window.ResizeObserver(this.measure);
      this.observer.observe(this.canvas);
    }
    this.measure();
  }
  componentDidUpdate() {this.measure();}
  componentWillUnmount() {
    this.clearHighlight();
    window.removeEventListener('resize', this.measure);
    document.removeEventListener('mousemove', this.pan);
    document.removeEventListener('mouseup', this.stopPan);
    window.removeEventListener('blur', this.stopPan);
    if (this.observer) this.observer.disconnect();
  }
  clearHighlight = () => {
    clearTimeout(this.highlightTimer);
    if (this.highlighted) {
      this.highlighted.classList.remove('automation-found-step');
      if (this.addedTabIndex) this.highlighted.removeAttribute('tabindex');
    }
    this.highlighted = null;
  }
  jumpTo = id => {
    const items = this.props.getNavigationItems ? this.props.getNavigationItems().filter(item => item.id === id) : [];
    if (items.length !== 1 || items[0].ambiguous) return 'This step is missing or its ID is ambiguous. Review the draft in Edit list.';
    // Compare attributes directly: IDs are exact strings, not CSS selectors.
    const targets = Array.from(this.canvas.querySelectorAll('[data-preview-node-id]')).filter(element => element.getAttribute('data-preview-node-id') === id);
    if (targets.length !== 1) return 'This step cannot be located uniquely in the preview. Use Edit list.';
    this.clearHighlight();
    const target = targets[0];
    this.highlighted = target;
    this.addedTabIndex = !target.hasAttribute('tabindex');
    if (this.addedTabIndex) target.setAttribute('tabindex', '-1');
    target.classList.add('automation-found-step');
    target.focus({preventScroll: true});
    const bounds = this.viewport.getBoundingClientRect();
    const node = target.getBoundingClientRect();
    this.viewport.scrollLeft += node.left + node.width / 2 - bounds.left - this.viewport.clientWidth / 2;
    this.viewport.scrollTop += node.top + node.height / 2 - bounds.top - this.viewport.clientHeight / 2;
    if ((bounds.top < 0 || bounds.bottom > window.innerHeight) && this.viewport.scrollIntoView) this.viewport.scrollIntoView({block: 'nearest'});
    this.highlightTimer = setTimeout(this.clearHighlight, 4000);
    return '';
  }
  measure = () => {
    this.align();
    const height = this.canvas.offsetHeight;
    if (height !== this.state.height) this.setState({height});
  }
  align = () => {
    const client = this.viewport.clientWidth;
    if (!client) return;
    const width = (this.props.width + 48) * this.state.scale;
    if (!this.lastSize) this.viewport.scrollLeft = Math.max(0, (width - client) / 2);
    else if (this.lastSize.scale === this.state.scale) this.viewport.scrollLeft += (width - this.lastSize.width + this.lastSize.client - client) / 2;
    this.lastSize = {width, client, scale: this.state.scale};
  }
  zoom = value => {
    const scale = Math.max(0.01, Math.min(2, value));
    const viewport = this.viewport;
    const x = (viewport.scrollLeft + viewport.clientWidth / 2) / this.state.scale;
    const y = (viewport.scrollTop + viewport.clientHeight / 2) / this.state.scale;
    this.setState({scale}, () => {
      viewport.scrollLeft = Math.max(0, x * scale - viewport.clientWidth / 2);
      viewport.scrollTop = Math.max(0, y * scale - viewport.clientHeight / 2);
    });
  }
  fit = () => {
    const scale = Math.min(1, (this.viewport.clientWidth - 24) / (this.props.width + 48),
      (this.viewport.clientHeight - 24) / Math.max(1, this.canvas.offsetHeight));
    this.zoom(scale);
    this.setState({}, () => {this.viewport.scrollLeft = 0; this.viewport.scrollTop = 0;});
  }
  startPan = event => {
    if (event.button !== 0) return;
    let target = event.target;
    while (target && target !== this.viewport) {
      if (target.matches('button, input, select, textarea, a, label, [draggable="true"], [data-preview-node-id]')) return;
      target = target.parentElement;
    }
    event.preventDefault();
    this.drag = {x: event.clientX, y: event.clientY, left: this.viewport.scrollLeft, top: this.viewport.scrollTop};
    this.setState({panning: true});
  }
  pan = event => {
    if (!this.drag) return;
    this.viewport.scrollLeft = this.drag.left + this.drag.x - event.clientX;
    this.viewport.scrollTop = this.drag.top + this.drag.y - event.clientY;
  }
  stopPan = () => {
    if (this.drag) {this.drag = null; this.setState({panning: false});}
  }
  render() {
    const {scale, height, panning} = this.state;
    const zoomLevels = Array.from({length: 20}, (_, index) => (20 - index) / 10).concat([0.05, 0.01]);
    if (!zoomLevels.includes(scale)) zoomLevels.push(scale);
    zoomLevels.sort((a, b) => b - a);
    return <div>
      <div className={'automation-preview-scroll automation-navigable-viewport' + (panning ? ' is-panning' : '')}
        tabIndex="0" role="region" aria-label="Automation graph" onMouseDown={this.startPan}
        ref={element => {this.viewport = element;}}>
        <div style={{position: 'relative', width: (this.props.width + 48) * scale, height: height * scale, margin: '0 auto', overflow: 'hidden'}}>
          <div className="automation-preview-canvas" ref={element => {this.canvas = element;}}
            style={{width: this.props.width, minWidth: 0, paddingRight: 48, boxSizing: 'content-box', transform: 'scale(' + scale + ')', transformOrigin: 'top left'}}>
            {this.props.children(scale)}
          </div>
        </div>
      </div>
      <div className="automation-view-controls" role="group" aria-label="Graph navigation">
        <select aria-label="Zoom level" value={scale} onChange={event => this.zoom(Number(event.target.value))}>
          {zoomLevels.map(value => <option key={value} value={value}>{Math.round(value * 100)}%</option>)}
        </select>
        <Button bsSize="xsmall" onClick={this.fit}>Fit to view</Button>
        {this.props.getNavigationItems && <AutomationStepFinder getItems={this.props.getNavigationItems} onJump={this.jumpTo} />}
      </div>
    </div>;
  }
}
