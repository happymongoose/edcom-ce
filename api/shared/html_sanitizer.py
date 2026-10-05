from __future__ import annotations

from html import escape as html_escape
from html.parser import HTMLParser
from typing import List, Tuple
from urllib.parse import urlparse
import re


ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "center",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}

VOID_TAGS = {"br", "hr", "img"}
BLOCKED_TAGS = {
    "applet",
    "audio",
    "embed",
    "form",
    "frame",
    "frameset",
    "iframe",
    "input",
    "link",
    "meta",
    "object",
    "script",
    "style",
    "svg",
    "textarea",
    "video",
}

GLOBAL_ATTRS = {
    "align",
    "bgcolor",
    "border",
    "cellpadding",
    "cellspacing",
    "class",
    "colspan",
    "height",
    "role",
    "rowspan",
    "style",
    "valign",
    "width",
}

TAG_ATTRS = {
    "a": {"href", "name", "target", "title"},
    "img": {"alt", "height", "referrerpolicy", "src", "title", "width"},
    "table": {"align", "bgcolor", "border", "cellpadding", "cellspacing", "width"},
    "td": {"align", "bgcolor", "colspan", "height", "rowspan", "valign", "width"},
    "th": {"align", "bgcolor", "colspan", "height", "rowspan", "valign", "width"},
}

ALLOWED_CSS = {
    "background",
    "background-color",
    "border",
    "border-bottom",
    "border-bottom-color",
    "border-bottom-style",
    "border-bottom-width",
    "border-collapse",
    "border-color",
    "border-left",
    "border-left-color",
    "border-left-style",
    "border-left-width",
    "border-radius",
    "border-right",
    "border-right-color",
    "border-right-style",
    "border-right-width",
    "border-spacing",
    "border-style",
    "border-top",
    "border-top-color",
    "border-top-style",
    "border-top-width",
    "border-width",
    "color",
    "display",
    "font",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "height",
    "letter-spacing",
    "line-height",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-width",
    "min-width",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "text-align",
    "text-decoration",
    "vertical-align",
    "white-space",
    "width",
}

BAD_CSS_RE = re.compile(
    r"expression\s*\(|javascript:|vbscript:|behavior\s*:|-moz-binding|[<>]",
    re.IGNORECASE,
)
URL_CSS_RE = re.compile(r"url\s*\(", re.IGNORECASE)
SAFE_CSS_URL_RE = re.compile(
    r"url\s*\(\s*['\"]?(https?:|data:image/(gif|jpe?g|png|webp);base64,|/)",
    re.IGNORECASE,
)


def _safe_url(value: str, allow_image_data: bool = False) -> bool:
    value = value.strip()
    lower = value.lower()
    if not value:
        return True
    if value.startswith("{{") or value.startswith("{%"):
        return True
    if allow_image_data and re.match(
        r"^data:image/(gif|jpe?g|png|webp);base64,", value, re.IGNORECASE
    ):
        return True
    parsed = urlparse(value)
    if not parsed.scheme:
        return True
    return lower.startswith(("http:", "https:", "mailto:", "tel:"))


def _sanitize_style(value: str) -> str:
    rules: List[str] = []
    for raw_rule in value.split(";"):
        if ":" not in raw_rule:
            continue
        prop, val = raw_rule.split(":", 1)
        prop = prop.strip().lower()
        val = val.strip()
        if prop not in ALLOWED_CSS:
            continue
        if BAD_CSS_RE.search(val):
            continue
        if URL_CSS_RE.search(val) and not SAFE_CSS_URL_RE.search(val):
            continue
        rules.append(f"{prop}: {val}")
    return "; ".join(rules)


class _EmailHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: List[str] = []
        self.blocked_depth = 0
        self.open_tags: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.blocked_depth:
            if tag in BLOCKED_TAGS:
                self.blocked_depth += 1
            return
        if tag in BLOCKED_TAGS:
            self.blocked_depth = 1
            return
        if tag not in ALLOWED_TAGS:
            return

        clean_attrs: List[str] = []
        allowed_attrs = GLOBAL_ATTRS | TAG_ATTRS.get(tag, set())
        for name, value in attrs:
            name = name.lower()
            value = value or ""
            if name.startswith("on") or name == "srcdoc" or name not in allowed_attrs:
                continue
            if name in {"href", "src"} and not _safe_url(value, tag == "img"):
                continue
            if name == "style":
                value = _sanitize_style(value)
                if not value:
                    continue
            clean_attrs.append(
                '%s="%s"' % (name, html_escape(value, quote=True))
            )
        if tag == "a" and any(attr == 'target="_blank"' for attr in clean_attrs):
            clean_attrs.append('rel="noopener noreferrer"')
        if (
            tag == "img"
            and any(attr.lower().startswith('src="http') for attr in clean_attrs)
            and not any(attr.lower().startswith('referrerpolicy=') for attr in clean_attrs)
        ):
            clean_attrs.append('referrerpolicy="no-referrer"')

        attr_text = (" " + " ".join(clean_attrs)) if clean_attrs else ""
        self.output.append(f"<{tag}{attr_text}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.blocked_depth:
            if tag in BLOCKED_TAGS:
                self.blocked_depth -= 1
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag in self.open_tags:
            while self.open_tags:
                open_tag = self.open_tags.pop()
                self.output.append(f"</{open_tag}>")
                if open_tag == tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.output.append(html_escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self.blocked_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.blocked_depth:
            self.output.append(f"&#{name};")

    def get_html(self) -> str:
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")
        return "".join(self.output)


def sanitize_email_html(value: str) -> str:
    parser = _EmailHTMLSanitizer()
    parser.feed(value or "")
    parser.close()
    return parser.get_html()
