const ALLOWED_TAGS = {
  a: true,
  abbr: true,
  b: true,
  blockquote: true,
  br: true,
  center: true,
  code: true,
  div: true,
  em: true,
  h1: true,
  h2: true,
  h3: true,
  h4: true,
  h5: true,
  h6: true,
  hr: true,
  i: true,
  img: true,
  li: true,
  ol: true,
  p: true,
  pre: true,
  s: true,
  small: true,
  span: true,
  strong: true,
  sub: true,
  sup: true,
  table: true,
  tbody: true,
  td: true,
  tfoot: true,
  th: true,
  thead: true,
  tr: true,
  u: true,
  ul: true,
};

const BLOCKED_TAGS = {
  applet: true,
  audio: true,
  embed: true,
  form: true,
  frame: true,
  frameset: true,
  iframe: true,
  input: true,
  link: true,
  meta: true,
  object: true,
  script: true,
  style: true,
  svg: true,
  textarea: true,
  video: true,
};

const GLOBAL_ATTRS = {
  align: true,
  bgcolor: true,
  border: true,
  cellpadding: true,
  cellspacing: true,
  class: true,
  colspan: true,
  height: true,
  role: true,
  rowspan: true,
  style: true,
  valign: true,
  width: true,
};

const TAG_ATTRS = {
  a: {href: true, name: true, target: true, title: true},
  img: {alt: true, height: true, referrerpolicy: true, src: true, title: true, width: true},
  table: {align: true, bgcolor: true, border: true, cellpadding: true, cellspacing: true, width: true},
  td: {align: true, bgcolor: true, colspan: true, height: true, rowspan: true, valign: true, width: true},
  th: {align: true, bgcolor: true, colspan: true, height: true, rowspan: true, valign: true, width: true},
};

const ALLOWED_CSS = {
  background: true,
  backgroundColor: true,
  border: true,
  borderBottom: true,
  borderBottomColor: true,
  borderBottomStyle: true,
  borderBottomWidth: true,
  borderCollapse: true,
  borderColor: true,
  borderLeft: true,
  borderLeftColor: true,
  borderLeftStyle: true,
  borderLeftWidth: true,
  borderRadius: true,
  borderRight: true,
  borderRightColor: true,
  borderRightStyle: true,
  borderRightWidth: true,
  borderSpacing: true,
  borderStyle: true,
  borderTop: true,
  borderTopColor: true,
  borderTopStyle: true,
  borderTopWidth: true,
  borderWidth: true,
  color: true,
  display: true,
  font: true,
  fontFamily: true,
  fontSize: true,
  fontStyle: true,
  fontWeight: true,
  height: true,
  letterSpacing: true,
  lineHeight: true,
  margin: true,
  marginBottom: true,
  marginLeft: true,
  marginRight: true,
  marginTop: true,
  maxWidth: true,
  minWidth: true,
  padding: true,
  paddingBottom: true,
  paddingLeft: true,
  paddingRight: true,
  paddingTop: true,
  textAlign: true,
  textDecoration: true,
  verticalAlign: true,
  whiteSpace: true,
  width: true,
};

function isSafeUrl(value, allowImageData) {
  if (!value) {
    return true;
  }
  const trimmed = value.trim();
  const lower = trimmed.toLowerCase();
  if (trimmed.indexOf('{{') === 0 || trimmed.indexOf('{%') === 0) {
    return true;
  }
  if (allowImageData && /^data:image\/(gif|jpe?g|png|webp);base64,/i.test(trimmed)) {
    return true;
  }
  return /^(https?:|mailto:|tel:|#|\/)/i.test(trimmed) || lower.indexOf(':') === -1;
}

function sanitizeStyle(value) {
  return value.split(';').map(rule => {
    const colon = rule.indexOf(':');
    if (colon === -1) {
      return '';
    }
    const prop = rule.slice(0, colon).trim();
    const val = rule.slice(colon + 1).trim();
    const camel = prop.replace(/-([a-z])/g, (m, c) => c.toUpperCase());
    const lower = val.toLowerCase();
    if (!ALLOWED_CSS[camel] || /expression\s*\(|javascript:|vbscript:|behavior\s*:|-moz-binding|[<>]/i.test(lower)) {
      return '';
    }
    if (/url\s*\(/i.test(lower) && !/url\s*\(\s*['"]?(https?:|data:image\/(gif|jpe?g|png|webp);base64,|\/)/i.test(lower)) {
      return '';
    }
    return prop + ': ' + val;
  }).filter(Boolean).join('; ');
}

function authQuery() {
  const params = [];
  if (window.localStorage && localStorage['uid'] && localStorage['cookieid']) {
    params.push('uid=' + encodeURIComponent(localStorage['uid']));
    params.push('cookieid=' + encodeURIComponent(localStorage['cookieid']));
  }
  if (window.sessionStorage && sessionStorage['impersonateid']) {
    params.push('impersonate=' + encodeURIComponent(sessionStorage['impersonateid']));
  }
  return params.join('&');
}

function previewImageUrl(src) {
  const auth = authQuery();
  if (!auth || !/^https?:\/\//i.test(src)) {
    return src;
  }
  return '/api/htmlpreviewimage?url=' + encodeURIComponent(src) + '&' + auth;
}

function sanitizeNode(node, doc, options) {
  if (node.nodeType === Node.TEXT_NODE) {
    return doc.createTextNode(node.textContent);
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const tag = node.tagName.toLowerCase();
  if (BLOCKED_TAGS[tag]) {
    return null;
  }

  if (!ALLOWED_TAGS[tag]) {
    const fragment = doc.createDocumentFragment();
    Array.prototype.forEach.call(node.childNodes, child => {
      const sanitized = sanitizeNode(child, doc, options);
      if (sanitized) {
        fragment.appendChild(sanitized);
      }
    });
    return fragment;
  }

  const clean = doc.createElement(tag);
  Array.prototype.forEach.call(node.attributes, attr => {
    const name = attr.name.toLowerCase();
    const value = attr.value;
    if (name.indexOf('on') === 0 || name === 'srcdoc') {
      return;
    }
    if (!GLOBAL_ATTRS[name] && !(TAG_ATTRS[tag] && TAG_ATTRS[tag][name])) {
      return;
    }
    if ((name === 'href' || name === 'src') && !isSafeUrl(value, tag === 'img')) {
      return;
    }
    if (name === 'style') {
      const cleanStyle = sanitizeStyle(value);
      if (cleanStyle) {
        clean.setAttribute(name, cleanStyle);
      }
      return;
    }
    clean.setAttribute(name, value);
  });
  if (tag === 'a' && clean.getAttribute('target') === '_blank') {
    clean.setAttribute('rel', 'noopener noreferrer');
  }
  if (tag === 'img' && /^https?:\/\//i.test(clean.getAttribute('src') || '') && !clean.getAttribute('referrerpolicy')) {
    clean.setAttribute('referrerpolicy', 'no-referrer');
  }
  if (tag === 'img' && options && options.proxyImages) {
    clean.setAttribute('src', previewImageUrl(clean.getAttribute('src') || ''));
  }
  Array.prototype.forEach.call(node.childNodes, child => {
    const sanitized = sanitizeNode(child, doc, options);
    if (sanitized) {
      clean.appendChild(sanitized);
    }
  });
  return clean;
}

export default function sanitizeHTML(input, options) {
  if (!input) {
    return '';
  }
  const parser = new DOMParser();
  const parsed = parser.parseFromString('<div>' + input + '</div>', 'text/html');
  const doc = document.implementation.createHTMLDocument('');
  const container = doc.createElement('div');
  Array.prototype.forEach.call(parsed.body.firstChild.childNodes, child => {
    const sanitized = sanitizeNode(child, doc, options || {});
    if (sanitized) {
      container.appendChild(sanitized);
    }
  });
  return container.innerHTML;
}
