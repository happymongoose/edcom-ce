import React, {Component} from 'react';

let serial = 0;

// Presentation only: all endpoints are resolved by exact canonical node IDs.
export default class AutomationGoToConnections extends Component {
  state = {line: null};
  markerId = 'automation-jump-arrow-' + (++serial);

  componentDidMount() {
    window.addEventListener('resize', this.schedule);
    window.addEventListener('scroll', this.schedule, true);
    document.addEventListener('click', this.dismissOnClick);
    document.addEventListener('keydown', this.dismissOnEscape);
    if (window.ResizeObserver) {
      this.observer = new window.ResizeObserver(this.schedule);
      this.observer.observe(this.root);
    }
  }
  componentDidUpdate() { this.schedule(); }
  componentWillUnmount() {
    window.removeEventListener('resize', this.schedule);
    window.removeEventListener('scroll', this.schedule, true);
    document.removeEventListener('click', this.dismissOnClick);
    document.removeEventListener('keydown', this.dismissOnEscape);
    if (this.observer) this.observer.disconnect();
    if (this.frame) window.cancelAnimationFrame(this.frame);
    this.clearHighlight();
  }

  anchor = element => {
    while (element && element !== this.root) {
      if (element.getAttribute && element.hasAttribute('data-preview-node-id')) return element;
      element = element.parentElement;
    }
    return null;
  }
  show = event => {
    const anchor = this.anchor(event.target);
    const node = anchor && this.props.nodes.find(item => item.id === anchor.getAttribute('data-preview-node-id'));
    // Keep the connection visible while moving to an off-screen destination.
    if (node && node.type === 'go_to') {
      this.source = anchor;
      this.schedule();
    }
  }
  dismiss = () => { this.source = null; this.schedule(); }
  dismissOnEscape = event => { if (event.key === 'Escape') this.dismiss(); }
  dismissOnClick = event => {
    const anchor = this.root.contains(event.target) && this.anchor(event.target);
    const node = anchor && this.props.nodes.find(item => item.id === anchor.getAttribute('data-preview-node-id'));
    if (!node || node.type !== 'go_to') this.dismiss();
  }
  schedule = () => {
    if (!window.requestAnimationFrame) {this.measure(); return;}
    if (this.frame) window.cancelAnimationFrame(this.frame);
    this.frame = window.requestAnimationFrame(this.measure);
  }
  clearHighlight = () => {
    if (this.destination) this.destination.classList.remove('automation-jump-destination');
    this.destination = null;
  }
  measure = () => {
    this.frame = null;
    this.clearHighlight();
    let line = null;
    if (!this.props.disabled && this.source && this.root.contains(this.source)) {
      const sourceId = this.source.getAttribute('data-preview-node-id');
      const sources = this.props.nodes.filter(node => node.id === sourceId);
      const node = sources.length === 1 && sources[0];
      const targets = node ? this.props.nodes.filter(item => item.id === node.target_node_id) : [];
      const destination = targets.length === 1 && Array.from(this.root.querySelectorAll('[data-preview-node-id]'))
        .find(element => element !== this.source && element.getAttribute('data-preview-node-id') === node.target_node_id);
      if (destination) {
        const root = this.root.getBoundingClientRect();
        const from = this.source.getBoundingClientRect();
        const to = destination.getBoundingClientRect();
        if (from.width && to.width) {
          const scale = this.props.scale || 1;
          const x1 = (from.right - root.left) / scale, y1 = (from.top + from.height / 2 - root.top) / scale;
          const x2 = (to.right - root.left) / scale, y2 = (to.top + to.height / 2 - root.top) / scale;
          const bend = Math.max(x1, x2) + 16;
          line = {path: `M ${x1} ${y1} H ${bend} V ${y2} H ${x2}`, label: 'Go to destination: ' + (targets[0].label || targets[0].type)};
          this.destination = destination;
          destination.classList.add('automation-jump-destination');
        }
      }
    }
    if (JSON.stringify(line) !== JSON.stringify(this.state.line)) this.setState({line});
  }

  render() {
    const line = this.state.line;
    return <div className="automation-jump-layer" ref={element => {this.root = element;}}
      onMouseOver={this.show} onFocus={this.show}>
      {this.props.children}
      {line && <svg className="automation-jump-overlay" role="img" aria-label={line.label}>
        <defs><marker id={this.markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#496bc5" />
        </marker></defs>
        <path d={line.path} fill="none" stroke="#496bc5" strokeWidth="2" strokeDasharray="6 4" markerEnd={'url(#' + this.markerId + ')'} />
      </svg>}
    </div>;
  }
}
