import React from 'react';
import notify from '../utils/notify';

const labels = {success: 'Success', error: 'Error', warning: 'Warning'};

export default class Notifications extends React.Component {
  state = {notification: null};
  hovered = false;
  focused = false;

  componentDidMount() {
    this.unsubscribe = notify.subscribe(notification => {
      clearTimeout(this.timer);
      const previous = this.state.notification;
      // Switching live regions replaces the card, so old pointer/focus state no longer applies.
      if (!previous || !notification || (previous.type === 'error') !== (notification.type === 'error')) {
        this.hovered = false;
        this.focused = false;
      }
      this.setState({notification}, () => this.schedule());
    });
  }

  componentWillUnmount() {
    this.unsubscribe();
    clearTimeout(this.timer);
  }

  schedule = () => {
    clearTimeout(this.timer);
    const notification = this.state.notification;
    if (notification && !this.hovered && !this.focused && notification.duration > 0) {
      this.timer = setTimeout(() => notify.dismiss(notification), notification.duration);
    }
  };

  dismiss = () => {
    this.hovered = false;
    this.focused = false;
    notify.dismiss(this.state.notification);
  };

  render() {
    const notification = this.state.notification;
    const type = notification && labels[notification.type] ? notification.type : 'info';
    return <div className="app-notifications">
      <div role="status" aria-live="polite" aria-atomic="true">
        {notification && type !== 'error' ? this.card(notification, type) : null}
      </div>
      <div role="alert" aria-live="assertive" aria-atomic="true">
        {notification && type === 'error' ? this.card(notification, type) : null}
      </div>
    </div>;
  }

  card(notification, type) {
    return <div className={'app-toast app-toast--' + type}
      onMouseEnter={() => { this.hovered = true; this.schedule(); }}
      onMouseLeave={() => { this.hovered = false; this.schedule(); }}
      onFocus={() => { this.focused = true; this.schedule(); }}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          this.focused = false;
          this.schedule();
        }
      }}>
      <div className="app-toast__content">
        <strong className="app-toast__title">{labels[type] || 'Notice'}</strong>
        <div className="app-toast__message">{notification.text}</div>
      </div>
      <button type="button" className="app-toast__close" aria-label="Dismiss notification"
        onClick={this.dismiss} onKeyDown={event => {
          if (event.key === 'Escape') { event.stopPropagation(); this.dismiss(); }
        }}><span aria-hidden="true">×</span></button>
    </div>;
  }
}
