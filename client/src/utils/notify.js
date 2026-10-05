// Keep the existing application-wide show(message, type, timeout) API.
class Notify {
  constructor() {
    this.current = null;
    this.listeners = [];
  }

  show(text, type, timeout) {
    this.current = {text, type, duration: timeout || 7000};
    this.emit();
  }

  dismiss(notification) {
    // An old timer must never dismiss a newer notification.
    if (notification !== this.current) return;
    this.current = null;
    this.emit();
  }

  subscribe(listener) {
    this.listeners.push(listener);
    listener(this.current);
    return () => { this.listeners = this.listeners.filter(item => item !== listener); };
  }

  emit() {
    this.listeners.forEach(listener => listener(this.current));
  }
}

export default new Notify();
