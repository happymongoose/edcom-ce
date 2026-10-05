import falcon
from . import automation_subject_tests as subject_tests
import copy
import hashlib
import email.utils
import json
import logging
import os
import re
import shortuuid
import traceback
import time
import dateutil.parser
from contextlib import contextmanager, nullcontext
from functools import wraps
from datetime import datetime, timedelta
from dateutil.tz import tzutc
from html import unescape as html_unescape
from html.parser import HTMLParser
from jsonschema import validate
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

from .shared import config as _  # noqa: F401
from .shared import contacts
from .shared.crud import (
    CRUDCollection,
    CRUDSingle,
    check_noadmin,
    get_orig,
)
from .shared.db import DB, JsonObj, json_iter, json_obj, open_db
from .shared.tasks import tasks, HIGH_PRIORITY
from .shared.utils import user_log
from .shared.utils import emailre
from . import automation_exit_rules as exit_rules
from .shared.utils import fix_tag
from .shared.utils import is_true
from .shared.utils import generate_html, remove_newlines
from .shared.utils import check_automation_diagnostics
from .shared.utils import gather_init, gather_complete, gather_check, run_task
from .shared.send import check_test_limit, send_backend_mail, validate_sender_domains, MailNotSentError
from .transactional import add_test_txn_log
from .shared.segments import (
    Cache,
    segment_get_segments,
    segment_get_campaignids,
    segment_get_params,
    get_segment_sentrows,
    get_segment_rows,
    segment_eval_parts,
)

log = logging.getLogger(__name__)

URL_SCHEME_RE = re.compile(r"^[a-zA-Z]+:")


def _normalize_automation_click_url(url: str | None) -> str:
    value = html_unescape(str(url or "").strip())
    if not value:
        return ""
    if not URL_SCHEME_RE.search(value) and not value.startswith("{{"):
        value = "http://%s" % value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value.lower()
    if not parts.scheme or value.startswith("{{"):
        return value
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            parts.query,
            parts.fragment,
        )
    )


def _automation_click_match_mode(value: str | None) -> str:
    if value == "url":
        return "url_exact"
    return value or "any"


def _automation_click_url_prefix_match(clicked_url: str | None, configured_url: str | None) -> bool:
    clicked = _normalize_automation_click_url(clicked_url)
    configured = _normalize_automation_click_url(configured_url)
    if not clicked or not configured:
        return False
    if clicked == configured:
        return True
    if not clicked.startswith(configured):
        return False
    # Keep prefix matching conservative: a page URL matches query/hash variants,
    # while /somepage does not unexpectedly match /somepage-other.
    if "?" in configured or "#" in configured or configured.endswith(("/", "&", "=")):
        return True
    return clicked[len(configured):len(configured) + 1] in ("?", "#")


class _AutomationEmailLinkParser(HTMLParser):

    def __init__(self):
        super(_AutomationEmailLinkParser, self).__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if (tag or "").lower() != "a":
            return
        for key, value in attrs:
            if (key or "").lower() == "href":
                self.links.append(value or "")
                return


def _automation_email_html_fragments(email_doc: JsonObj) -> List[str]:
    fragments = []
    raw_text = email_doc.get("rawText")
    if isinstance(raw_text, str):
        raw_value = raw_text.strip()
        if raw_value:
            if (email_doc.get("type") or "raw") == "beefree":
                try:
                    raw_doc = json.loads(raw_value)
                    html = raw_doc.get("html") if isinstance(raw_doc, dict) else None
                    if isinstance(html, str):
                        fragments.append(html)
                    else:
                        fragments.append(raw_value)
                except (TypeError, ValueError):
                    fragments.append(raw_value)
            else:
                fragments.append(raw_value)
    parts = email_doc.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            for field in ("html", "content", "value", "text"):
                value = part.get(field)
                if isinstance(value, str) and value.strip():
                    fragments.append(value)
    return fragments


def _automation_email_discovered_links(email_doc: JsonObj) -> List[JsonObj]:
    grouped = {}
    order = []
    for fragment in _automation_email_html_fragments(email_doc):
        parser = _AutomationEmailLinkParser()
        try:
            parser.feed(fragment)
        except Exception:
            continue
        for href in parser.links:
            original = html_unescape(str(href or "").strip())
            normalized = _normalize_automation_click_url(original)
            if not original or not normalized:
                continue
            tracked = "notrack" not in original.lower()
            key = (normalized, tracked)
            if key not in grouped:
                grouped[key] = {
                    "normalized_url": normalized,
                    "display_url": original,
                    "occurrence_count": 0,
                    "tracked": tracked,
                }
                order.append(key)
            grouped[key]["occurrence_count"] += 1
    return [grouped[key] for key in order][:100]


NODE_ID_SCHEMA = {
    "type": "string",
    "pattern": "^[0-9a-zA-Z_-]{1,64}$",
}


ADD_TAG_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label"],
    "oneOf": [{"required": ["draft_tag"]}, {"required": ["draft_tags"]}],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["add_tag"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "draft_tags": {"type": "array", "maxItems": 100, "uniqueItems": True, "items": {"type": "string", "maxLength": 1024}},
        "draft_tag": {
            "type": "string",
            "maxLength": 1024,
        },
    },
    "additionalProperties": False,
}


REMOVE_TAG_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label"],
    "oneOf": [{"required": ["draft_tag"]}, {"required": ["draft_tags"]}],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["remove_tag"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "draft_tags": {"type": "array", "maxItems": 100, "uniqueItems": True, "items": {"type": "string", "maxLength": 1024}},
        "draft_tag": {
            "type": "string",
            "maxLength": 1024,
        },
    },
    "additionalProperties": False,
}


ADD_TO_LIST_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label"],
    "oneOf": [{"required": ["list_id"]}, {"required": ["list_ids"]}],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["add_to_list"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "list_ids": {"type": "array", "maxItems": 100, "uniqueItems": True, "items": {"type": "string", "minLength": 1, "maxLength": 64}},
        "list_id": {
            "type": "string",
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}


REMOVE_FROM_LIST_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label"],
    "oneOf": [{"required": ["list_id"]}, {"required": ["list_ids"]}],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["remove_from_list"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "list_ids": {"type": "array", "maxItems": 100, "uniqueItems": True, "items": {"type": "string", "minLength": 1, "maxLength": 64}},
        "list_id": {
            "type": "string",
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}


ENROL_AUTOMATION_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "automation_id"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {"enum": ["enrol_automation"]},
        "label": {"type": "string", "minLength": 1, "maxLength": 1024},
        "automation_id": {"type": "string", "maxLength": 64},
    },
    "additionalProperties": False,
}


REMOVE_AUTOMATION_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "automation_id"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {"enum": ["remove_automation"]},
        "label": {"type": "string", "minLength": 1, "maxLength": 1024},
        "automation_id": {"type": "string", "maxLength": 64},
    },
    "additionalProperties": False,
}


WAIT_DURATION_SCHEMA = {
    "type": "object",
    "required": ["days", "hours", "minutes"],
    "properties": {
        "days": {
            "type": "integer",
            "minimum": 0,
        },
        "hours": {
            "type": "integer",
            "minimum": 0,
        },
        "minutes": {
            "type": "integer",
            "minimum": 0,
        },
    },
    "additionalProperties": False,
}


WAIT_DURATION_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label"],
    "oneOf": [{"required": ["duration"]}, {"required": ["wait_until"]}],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["wait_duration"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "duration": WAIT_DURATION_SCHEMA,
        "wait_until": {"type": "string", "maxLength": 64},
    },
    "additionalProperties": False,
}


IF_HAS_TAG_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "draft_tag", "yes_node_id", "no_node_id"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["if_has_tag"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "draft_tag": {
            "type": "string",
            "maxLength": 1024,
        },
        "yes_node_id": {
            "type": "string",
            "maxLength": 64,
        },
        "no_node_id": {
            "type": "string",
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}


IF_MISSING_TAG_NODE_SCHEMA = copy.deepcopy(IF_HAS_TAG_NODE_SCHEMA)
IF_MISSING_TAG_NODE_SCHEMA["properties"]["type"]["enum"] = ["if_missing_tag"]


CONDITION_ITEM_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "required": ["type", "tag"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["has_tag", "missing_tag"],
                },
                "tag": {
                    "type": "string",
                    "maxLength": 1024,
                },
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["type", "automation_email_id"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["opened_email", "not_opened_email"],
                },
                "automation_email_id": {
                    "type": "string",
                    "maxLength": 64,
                },
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["type", "automation_email_id"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["clicked_email", "not_clicked_email"],
                },
                "automation_email_id": {
                    "type": "string",
                    "maxLength": 64,
                },
                "click_match": {
                    "type": "string",
                    "enum": ["any", "url", "url_exact", "url_prefix"],
                },
                "link_url": {
                    "type": "string",
                    "maxLength": 2048,
                },
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["type", "list_id"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["in_list", "not_in_list"],
                },
                "list_id": {
                    "type": "string",
                    "maxLength": 64,
                },
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["group"],
                },
                "mode": {
                    "type": "string",
                    "enum": ["all", "any"],
                },
                "items": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                    },
                },
            },
            "additionalProperties": False,
        },
    ],
}


# Preserve singular draft definitions; plural predicates match ANY (or NONE when negative).
for condition_type, field, max_length in (
    ("has_tag", "tags", 1024),
    ("missing_tag", "tags", 1024),
    ("in_list", "list_ids", 64),
    ("not_in_list", "list_ids", 64),
):
    CONDITION_ITEM_SCHEMA["oneOf"].append({
        "type": "object",
        "required": ["type", field],
        "properties": {
            "type": {"type": "string", "enum": [condition_type]},
            field: {"type": "array", "maxItems": 100, "uniqueItems": True,
                    "items": {"type": "string", "maxLength": max_length}},
        },
        "additionalProperties": False,
    })


CONDITION_GROUP_SCHEMA = {
    "type": "object",
    "required": ["mode", "items"],
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["all", "any"],
        },
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": CONDITION_ITEM_SCHEMA,
        },
    },
    "additionalProperties": False,
}


IF_CONDITIONS_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "condition", "yes_node_id", "no_node_id"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["if_conditions"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "condition": CONDITION_GROUP_SCHEMA,
        "yes_node_id": {
            "type": "string",
            "maxLength": 64,
        },
        "no_node_id": {
            "type": "string",
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}


GO_TO_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "target_node_id"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["go_to"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "target_node_id": {
            "type": "string",
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}


SEND_EMAIL_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "automation_email_id"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["send_email"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "automation_email_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}


EMAIL_ENGAGEMENT_CONDITION_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "automation_email_id", "yes_node_id", "no_node_id"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["if_opened_email", "if_clicked_email"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "automation_email_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
        "yes_node_id": {
            "type": "string",
            "maxLength": 64,
        },
        "no_node_id": {
            "type": "string",
            "maxLength": 64,
        },
        "click_match": {
            "type": "string",
            "enum": ["any", "url", "url_exact", "url_prefix"],
        },
        "link_url": {
            "type": "string",
            "maxLength": 2048,
        },
    },
    "additionalProperties": False,
}


EXIT_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label"],
    "properties": {
        "id": NODE_ID_SCHEMA,
        "type": {
            "type": "string",
            "enum": ["exit"],
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
    },
    "additionalProperties": False,
}


REENTRY_SCHEMA = {
    "type": "string",
    "enum": ["once", "multiple"],
}

TERMINAL_ENROLMENT_STATUSES = ("completed", "exited", "cancelled", "failed")
ACTIVE_ENROLMENT_STATUSES = (
    "ready",
    "waiting",
    "held",
    "paused_ready",
    "paused_waiting",
    "running",
)


ENTRY_TRIGGER_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["manual"],
                },
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["tag_added", "tag_removed"],
                },
                "tag": {
                    "type": "string",
                    "maxLength": 1024,
                },
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["list_joined", "list_left"],
                },
                "list_id": {
                    "type": "string",
                    "maxLength": 64,
                },
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["segment_entered", "segment_left"],
                },
                "segment_id": {
                    "type": "string",
                    "maxLength": 64,
                },
            },
            "additionalProperties": False,
        },
    ],
}


ENTRY_SCHEMA = {
    "oneOf": ENTRY_TRIGGER_SCHEMA["oneOf"] + [
        {
            "type": "object",
            "required": ["type", "triggers"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["multi"],
                },
                "triggers": {
                    "type": "array",
                    "minItems": 1,
                    "items": ENTRY_TRIGGER_SCHEMA,
                },
            },
            "additionalProperties": False,
        },
    ],
}


MOVE_PLACEMENT_SCHEMA = {
    "type": "object", "required": ["previous", "next", "incoming"],
    "properties": {
        "previous": {"type": ["string", "null"]}, "next": {"type": ["string", "null"]},
        "incoming": {"type": "array", "items": {
            "type": "object", "required": ["id", "field"],
            "properties": {"id": NODE_ID_SCHEMA, "field": {"enum": ["yes_node_id", "no_node_id", "target_node_id"]}},
            "additionalProperties": False,
        }},
    }, "additionalProperties": False,
}

DRAFT_SCHEMA = {
    "type": "object",
    "required": ["nodes"],
    "properties": {
        "moves": {"type": "object", "propertyNames": NODE_ID_SCHEMA, "additionalProperties": {
            "type": "object", "required": ["action", "published_revision", "placement"],
            "properties": {
                "action": {"enum": ["follow", "exit"]},
                "published_revision": {"type": "integer", "minimum": 1},
                "placement": MOVE_PLACEMENT_SCHEMA,
            }, "additionalProperties": False,
        }},
        "nodes": {
            "type": "array",
            "items": {
                "oneOf": [
                    ADD_TAG_NODE_SCHEMA,
                    REMOVE_TAG_NODE_SCHEMA,
                    ADD_TO_LIST_NODE_SCHEMA,
                    REMOVE_FROM_LIST_NODE_SCHEMA,
                    ENROL_AUTOMATION_NODE_SCHEMA,
                    REMOVE_AUTOMATION_NODE_SCHEMA,
                    WAIT_DURATION_NODE_SCHEMA,
                    IF_HAS_TAG_NODE_SCHEMA,
                    IF_MISSING_TAG_NODE_SCHEMA,
                    IF_CONDITIONS_NODE_SCHEMA,
                    GO_TO_NODE_SCHEMA,
                    SEND_EMAIL_NODE_SCHEMA,
                    EMAIL_ENGAGEMENT_CONDITION_NODE_SCHEMA,
                    EXIT_NODE_SCHEMA,
                ],
            },
        },
    },
    "additionalProperties": False,
}


# State predicates, not historical events: matching any rule both exits and
# excludes a contact. Change events will prompt evaluation of these predicates.
EXIT_RULES_SCHEMA = {
    "type": "array",
    "maxItems": 20,
    "items": {
        "oneOf": [
            {
                "type": "object",
                "required": ["type", "tags"],
                "properties": {
                    "type": {"enum": ["has_tag", "missing_tag"]},
                    "tags": {
                        "type": "array", "minItems": 1, "maxItems": 100,
                        "items": {"type": "string", "minLength": 1, "maxLength": 1024},
                    },
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["type", "list_ids"],
                "properties": {
                    "type": {"enum": ["in_list", "not_in_list"]},
                    "list_ids": {
                        "type": "array", "minItems": 1, "maxItems": 100,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 64},
                    },
                },
                "additionalProperties": False,
            },
        ],
    },
}


AUTOMATION_CREATE_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "status": {
            "type": "string",
            "enum": ["draft"],
        },
        "reentry": REENTRY_SCHEMA,
    },
    "additionalProperties": False,
}


AUTOMATION_PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "status": {
            "type": "string",
            "enum": ["draft"],
        },
        "reentry": REENTRY_SCHEMA,
        "entry": ENTRY_SCHEMA,
        "exit_rules": EXIT_RULES_SCHEMA,
        "draft": DRAFT_SCHEMA,
    },
    "additionalProperties": False,
}


AUTOMATION_PUBLISH_SCHEMA = {
    "type": "object",
    "required": ["request_id", "review", "resolutions"],
    "properties": {
        "request_id": NODE_ID_SCHEMA,
        "accept_exit_rules": {"const": True},
        "review": {
            "type": "object",
            "required": ["draft_fingerprint", "published_fingerprint", "published_revision"],
            "properties": {
                "draft_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "published_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "published_revision": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        },
        "resolutions": {
            "type": "object",
            "propertyNames": NODE_ID_SCHEMA,
            "additionalProperties": {
                "oneOf": [
                    {"type": "object", "required": ["action", "destination_node_id"],
                     "properties": {"action": {"const": "move"}, "destination_node_id": NODE_ID_SCHEMA},
                     "additionalProperties": False},
                    {"type": "object", "required": ["action"],
                     "properties": {"action": {"const": "exit"}}, "additionalProperties": False},
                ],
            },
        },
    },
    "additionalProperties": False,
}


AUTOMATION_ENROLMENT_SCHEMA = {
    "type": "object",
    "required": ["email"],
    "properties": {
        "email": {
            "type": "string",
            "minLength": 1,
        },
    },
    "additionalProperties": False,
}

AUTOMATION_TRIGGER_EVENT_SCHEMA = {
    "type": "object",
    "required": ["event_type", "contact_email"],
    "properties": {
        "event_type": {
            "type": "string",
            "enum": ["tag_added", "tag_removed", "list_joined", "list_left", "segment_entered", "segment_left"],
        },
        "contact_email": {
            "type": "string",
            "minLength": 1,
            "maxLength": 320,
        },
        "tag": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1024,
        },
        "list_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
        "segment_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
        "source": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["manual", "debug", "automation", "api"],
                },
                "automation_id": {
                    "type": ["string", "null"],
                    "maxLength": 128,
                },
                "enrolment_id": {
                    "type": ["string", "null"],
                    "maxLength": 128,
                },
                "node_id": {
                    "type": ["string", "null"],
                    "maxLength": 128,
                },
                "step_run_id": {
                    "type": ["string", "null"],
                    "maxLength": 128,
                },
            },
            "additionalProperties": False,
        },
        "correlation_id": {
            "type": "string",
            "maxLength": 128,
        },
        "depth": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
        },
    },
    "additionalProperties": False,
}

AUTOMATION_SEGMENT_TRIGGER_BASELINE_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["baseline", "diff"],
        },
        "segment_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
        "limit_segments": {
            "type": "integer",
            "minimum": 1,
        },
        "limit_buckets": {
            "type": "integer",
            "minimum": 1,
        },
        "limit_events": {
            "type": "integer",
            "minimum": 1,
        },
    },
    "additionalProperties": False,
}

AUTOMATION_TRIGGER_PROCESS_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
        },
    },
    "additionalProperties": False,
}

AUTOMATION_LIST_ENROLMENT_SCHEMA = {
    "type": "object",
    "required": ["list_id"],
    "properties": {
        "list_id": {
            "type": "string",
            "minLength": 1,
        },
    },
    "additionalProperties": False,
}

AUTOMATION_SEGMENT_ENROLMENT_SCHEMA = {
    "type": "object",
    "required": ["segment_id"],
    "properties": {
        "segment_id": {
            "type": "string",
            "minLength": 1,
        },
    },
    "additionalProperties": False,
}

AUTOMATION_EMAIL_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 1024,
        },
        "subject": {
            "type": "string",
            "maxLength": 1024,
        },
        "preheader": {
            "type": "string",
            "maxLength": 1024,
        },
        "fromname": {
            "type": "string",
            "maxLength": 1024,
        },
        "fromemail": {
            "type": "string",
            "maxLength": 1024,
        },
        "replyto": {
            "type": "string",
            "maxLength": 1024,
        },
        "returnpath": {
            "type": "string",
            "maxLength": 1024,
        },
        "type": {
            "type": "string",
            "enum": ["", "raw", "wysiwyg", "beefree"],
        },
        "rawText": {
            "type": "string",
        },
        "parts": {
            "type": "array",
        },
        "bodyStyle": {
            "type": "object",
        },
    },
    "additionalProperties": False,
}

AUTOMATION_EMAIL_PATCH_SCHEMA = copy.deepcopy(AUTOMATION_EMAIL_CREATE_SCHEMA)

AUTOMATION_EMAIL_TEST_SCHEMA = {
    "type": "object",
    "required": ["to"],
    "properties": {
        "to": {
            "type": "string",
            "minLength": 1,
        },
        "route": {
            "type": "string",
        },
        "include_in_log": {
            "type": "boolean",
        },
    },
    "additionalProperties": False,
}


AUTOMATION_EMAIL_FROM_SOURCE_SCHEMA = {
    "type": "object",
    "required": ["source_id"],
    "properties": {
        "source_type": {
            "type": "string",
            "enum": [
                "automation_email",
                "transactional_template",
                "broadcast",
                "funnel_message",
            ],
        },
        "source_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}

BULK_DETAIL_LIMIT = 100


def _validate_doc(doc: JsonObj, schema: JsonObj) -> None:
    try:
        validate(doc, schema)
    except Exception as e:
        raise falcon.HTTPBadRequest(title="Input validation error", description=str(e))


def _validate_unique_node_ids(nodes: list[JsonObj], title: str = "Input validation error") -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for node in nodes:
        # Draft/publish callers already validate the schema. Avoid coercing IDs
        # while checking potentially malformed historical published snapshots.
        node_id = node.get("id") if isinstance(node, dict) else None
        if not isinstance(node_id, str):
            continue
        if node_id in seen:
            duplicates.add(node_id)
        seen.add(node_id)
    if duplicates:
        ids = ", ".join(json.dumps(node_id) for node_id in sorted(duplicates))
        raise falcon.HTTPBadRequest(
            title=title,
            description=_bounded_error_text("Automation node IDs must be unique. Duplicate IDs: %s." % ids),
        )


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _parse_datetime(value: str) -> datetime:
    parsed = dateutil.parser.parse(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tzutc()).replace(tzinfo=None)
    return parsed


def _prepare_doc(doc: JsonObj, create: bool) -> None:
    if doc.get("status", "draft") != "draft":
        raise falcon.HTTPBadRequest(
            title="Invalid automation status",
            description="Only draft automations can be saved at this stage.",
        )

    now = _utc_now()
    doc["status"] = "draft"
    doc["reentry"] = doc.get("reentry", "once")
    doc["modified"] = now
    if create:
        doc["created"] = now


def _prepare_patch_doc(doc: JsonObj) -> None:
    if "status" in doc and doc["status"] != "draft":
        raise falcon.HTTPBadRequest(
            title="Invalid automation status",
            description="Only publishing can update an automation to published.",
        )

    doc.pop("status", None)
    doc["modified"] = _utc_now()


def _validation_error(message: str) -> None:
    raise falcon.HTTPBadRequest(title="Automation publish validation failed", description=message)


def _published_single_entry(entry: JsonObj) -> JsonObj:
    entry_type = entry.get("type")
    if entry_type == "manual":
        return {"type": "manual"}
    if entry_type in ("tag_added", "tag_removed"):
        tag = (entry.get("tag") or "").strip()
        if not tag:
            trigger_label = "Tag added" if entry_type == "tag_added" else "Tag removed"
            _validation_error("%s entry trigger requires a tag." % trigger_label)
        return {
            "type": entry_type,
            "tag": tag,
        }
    if entry_type in ("list_joined", "list_left"):
        list_id = (entry.get("list_id") or "").strip()
        if not list_id:
            trigger_label = "Joined list" if entry_type == "list_joined" else "Left list"
            _validation_error("%s entry trigger requires a contact list." % trigger_label)
        return {
            "type": entry_type,
            "list_id": list_id,
        }
    if entry_type in ("segment_entered", "segment_left"):
        segment_id = (entry.get("segment_id") or "").strip()
        if not segment_id:
            trigger_label = "Entered segment" if entry_type == "segment_entered" else "Left segment"
            _validation_error("%s entry trigger requires a segment." % trigger_label)
        return {
            "type": entry_type,
            "segment_id": segment_id,
        }
    _validation_error("Automation entry trigger type is not supported.")


def _entry_triggers(entry: JsonObj | None) -> List[JsonObj]:
    if not entry:
        return []
    if entry.get("type") == "multi":
        return [trigger for trigger in entry.get("triggers") or [] if isinstance(trigger, dict)]
    return [entry]


def _entry_trigger_key(trigger: JsonObj) -> str:
    trigger_type = trigger.get("type")
    if trigger_type == "manual":
        return "manual"
    if trigger_type in ("tag_added", "tag_removed"):
        return "%s:%s" % (trigger_type, trigger.get("tag") or "")
    if trigger_type in ("list_joined", "list_left"):
        return "%s:%s" % (trigger_type, trigger.get("list_id") or "")
    if trigger_type in ("segment_entered", "segment_left"):
        return "%s:%s" % (trigger_type, trigger.get("segment_id") or "")
    return "%s:" % (trigger_type or "")


def _published_entry(entry: JsonObj) -> JsonObj:
    triggers = [_published_single_entry(trigger) for trigger in _entry_triggers(entry)]
    if not triggers:
        _validation_error("Automation entry requires at least one trigger.")

    seen = set()
    for trigger in triggers:
        key = _entry_trigger_key(trigger)
        if key in seen:
            _validation_error("Automation entry contains duplicate triggers.")
        seen.add(key)

    if len(triggers) == 1:
        return triggers[0]
    return {
        "type": "multi",
        "triggers": triggers,
    }


def _action_lists(node: JsonObj) -> list[str]:
    # Drafts may be incomplete; executable actions require a nonempty exact ID set.
    if "list_ids" in node and "list_id" in node:
        return []
    ids = node.get("list_ids") if "list_ids" in node else [node.get("list_id")]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
        return []
    if any(not isinstance(value, str) or not value or len(value) > 64 for value in ids):
        return []
    return ids if len(set(ids)) == len(ids) else []


def _action_tags(node: JsonObj) -> list[str]:
    # Legacy singular configurations retain their exact spelling and behaviour.
    if "draft_tags" not in node:
        tag = node.get("draft_tag")
        return [tag] if isinstance(tag, str) and tag else []
    tags = node["draft_tags"]
    if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 1024 for tag in tags):
        return []
    return list(dict.fromkeys(tags))


def _validate_tag_condition_node(node: JsonObj, node_ids: set[str], label: str) -> None:
    if not node.get("draft_tag"):
        _validation_error("%s nodes must have draft tag configuration." % label)
    _validate_branch_targets(node, node_ids, label)


def _validate_branch_targets(node: JsonObj, node_ids: set[str], label: str) -> None:
    if not node.get("yes_node_id"):
        _validation_error("%s nodes must have a yes target." % label)
    if not node.get("no_node_id"):
        _validation_error("%s nodes must have a no target." % label)
    if node.get("yes_node_id") not in node_ids:
        _validation_error("%s yes target must exist in the draft workflow." % label)
    if node.get("no_node_id") not in node_ids:
        _validation_error("%s no target must exist in the draft workflow." % label)
    if node.get("yes_node_id") == node.get("id") or node.get("no_node_id") == node.get("id"):
        _validation_error("%s nodes cannot target themselves." % label)


def _condition_selection(item: JsonObj, singular: str, plural: str) -> list[str]:
    values = item.get(plural) if plural in item else [item.get(singular)]
    if (not isinstance(values, list) or not values or len(values) > 100
            or any(not isinstance(value, str) or not value.strip() for value in values)
            or len(set(values)) != len(values)
            or (plural in item and singular in item)):
        _validation_error("Condition must select between 1 and 100 distinct %s." % plural)
    return values


def _validate_conditions_node(db: DB, automation: JsonObj, node: JsonObj, node_ids: set[str]) -> None:
    _validate_branch_targets(node, node_ids, "If conditions")
    condition = node.get("condition") or {}
    mode = condition.get("mode")
    if mode not in ("all", "any"):
        _validation_error("If conditions nodes must use all or any mode.")
    items = condition.get("items") or []
    if not items:
        _validation_error("If conditions nodes must contain at least one condition.")
    if len(items) > 20:
        _validation_error("If conditions nodes cannot contain more than 20 conditions.")

    for index, item in enumerate(items):
        item_type = item.get("type")
        label = "If conditions item %s" % (index + 1)
        if item_type == "group":
            _validation_error("Nested condition groups are not supported yet.")
        if item_type in ("has_tag", "missing_tag"):
            if "tags" not in item and not (item.get("tag") or "").strip():
                _validation_error("%s must select a tag." % label)
            _condition_selection(item, "tag", "tags")
        elif item_type in ("opened_email", "not_opened_email", "clicked_email", "not_clicked_email"):
            automation_email_id = item.get("automation_email_id")
            if not automation_email_id:
                _validation_error("%s must select an automation email." % label)
            if not _automation_email_exists(
                db,
                automation.get("cid"),
                automation.get("id"),
                automation_email_id,
            ):
                _validation_error("%s must reference an email from this automation." % label)
            if item_type in ("clicked_email", "not_clicked_email"):
                click_match = _automation_click_match_mode(item.get("click_match"))
                if click_match not in ("any", "url_exact", "url_prefix"):
                    _validation_error("%s has an unsupported click match mode." % label)
                if click_match in ("url_exact", "url_prefix") and not _normalize_automation_click_url(item.get("link_url")):
                    _validation_error("%s URL conditions must have a link URL." % label)
        elif item_type in ("in_list", "not_in_list"):
            if "list_ids" not in item and not item.get("list_id"):
                _validation_error("%s must select a contact list." % label)
            for list_id in _condition_selection(item, "list_id", "list_ids"):
                if db.lists.get(list_id) is None:
                    _validation_error("%s must reference a contact list from this account." % label)
        else:
            _validation_error("%s has an unsupported condition type." % label)


def _wait_deadline(value: Any) -> datetime:
    try:
        parsed = dateutil.parser.isoparse(value)
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(tzutc()).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        _validation_error("Wait until must be a valid date and time including its UTC offset.")


def _compatible_wait(old: JsonObj, new: JsonObj) -> bool:
    return new.get("type") == "wait_duration" and ("wait_until" in old) == ("wait_until" in new)


def _duration_minutes(duration: JsonObj) -> int:
    return (
        int(duration.get("days", 0)) * 24 * 60
        + int(duration.get("hours", 0)) * 60
        + int(duration.get("minutes", 0))
    )


def _wake_at(start: datetime, duration: JsonObj) -> str:
    wake = start + timedelta(minutes=_duration_minutes(duration))
    return wake.isoformat() + "Z"


def _iso_datetime(value: datetime) -> str:
    return value.isoformat() + "Z"


def _remaining_seconds(wake_at: str | None, now: datetime) -> int:
    if not wake_at:
        return 0
    return max(0, int((_parse_datetime(wake_at) - now).total_seconds()))


def _node_by_id(nodes: list[JsonObj], node_id: str | None) -> JsonObj | None:
    for node in nodes:
        if node.get("id") == node_id:
            return node
    return None


def _automation_email_exists(db: DB, cid: str, automation_id: str, email_id: str) -> bool:
    return bool(
        db.single(
            """
            select id
            from automation_emails
            where cid = %s and automation_id = %s and id = %s
            limit 1
            """,
            cid,
            automation_id,
            email_id,
        )
    )


def _contact_has_tag(db: DB, cid: str, contact_id: int, tag: str) -> bool:
    return bool(
        db.single(
            f"""select contact_id
            from contacts."contact_values_{cid}"
            where contact_id = %s and type = 'tag' and value = %s
            limit 1""",
            contact_id,
            tag,
        )
    )


def _contact_is_in_list(db: DB, cid: str, contact_id: int, list_id: str) -> bool:
    return bool(
        db.single(
            f"""select contact_id
            from contacts."contact_lists_{cid}"
            where contact_id = %s and list_id = %s
            limit 1""",
            contact_id,
            list_id,
        )
    )


def _truthy_contact_prop(props: JsonObj, name: str) -> bool:
    values = props.get(name) or []
    if not values:
        return False
    return is_true(str(values[0]) if values[0] is not None else None)


def _automation_send_suppression_reason(
    db: DB, cid: str, contact_id: int, contact_email: str
) -> str | None:
    props = db.single(
        f"""select props
        from contacts."contacts_{cid}"
        where contact_id = %s and lower(email) = %s""",
        contact_id,
        contact_email.strip().lower(),
    )
    props = props or {}
    if _truthy_contact_prop(props, "Unsubscribed"):
        return "unsubscribed"
    if _truthy_contact_prop(props, "Complained"):
        return "complained"
    if _truthy_contact_prop(props, "Bounced"):
        return "bounced"

    log_reason = db.row(
        """
        select unsubscribed, complained, bounced
        from unsublogs
        where cid = %s and email = %s
            and (unsubscribed or complained or bounced)
        """,
        cid,
        contact_email.strip().lower(),
    )
    if log_reason is not None:
        unsubscribed, complained, bounced = log_reason
        if unsubscribed:
            return "unsubscribed"
        if complained:
            return "complained"
        if bounced:
            return "bounced"

    domain = _contact_domain(contact_email)
    if db.single(
        "select true from exclusions where cid = %s and item = %s",
        cid,
        contact_email.strip().lower(),
    ):
        return "excluded_email"
    if domain and db.single(
        "select true from exclusions where cid = %s and item = %s",
        cid,
        domain,
    ):
        return "excluded_domain"

    return None


def _contact_list_counter_flags(contact: JsonObj) -> tuple[int, int, int, int]:
    props = contact.get("props") or {}

    def is_truthy(name: str) -> int:
        values = props.get(name) or []
        if not values:
            return 0
        value = values[0]
        if value is None or value == "":
            return 0
        return 1 if str(value).lower() == "true" else 0

    return (
        is_truthy("Bounced"),
        is_truthy("Unsubscribed"),
        is_truthy("Complained"),
        is_truthy("Soft Bounced"),
    )


def _contact_domain(email_address: str) -> str:
    if "@" not in email_address:
        return ""
    return email_address.rsplit("@", 1)[-1].strip().lower()


def _add_contact_to_list(
    db: DB,
    cid: str,
    contact_id: int,
    contact_email: str,
    list_id: str,
    automation_trigger_source: JsonObj | None = None,
    automation_trigger_correlation_id: str | None = None,
    automation_trigger_depth: int = 0,
    strict_events: bool = False,
) -> JsonObj:
    lst = db.lists.get(list_id)
    if lst is None:
        raise falcon.HTTPBadRequest(
            title="Automation list is missing",
            description="The published list node references a contact list that was not found.",
        )

    inserted = db.single(
        f"""
        insert into contacts."contact_lists_{cid}" (contact_id, list_id)
        values (%s, %s)
        on conflict (contact_id, list_id) do nothing
        returning list_id
        """,
        contact_id,
        list_id,
    )
    added = inserted is not None

    if added:
        contact = db.row_or_error(
            f"""select props from contacts."contacts_{cid}" where contact_id = %s""",
            contact_id,
        )
        bounced, unsubscribed, complained, soft_bounced = _contact_list_counter_flags(
            {"props": contact[0]}
        )
        domain = _contact_domain(contact_email)
        if domain:
            db.execute(
                """
                insert into list_domains (list_id, domain, count) values (%s, %s, 1)
                on conflict (list_id, domain) do update set count = list_domains.count + 1
                """,
                list_id,
                domain,
            )
        contacts.patch_list(
            db,
            list_id,
            1,
            bounced,
            unsubscribed,
            complained,
            soft_bounced,
        )
        try:
            contacts.maybe_insert_list_joined_trigger_event(
                db,
                cid,
                contact_email,
                contact_id,
                list_id,
                automation_trigger_source,
                automation_trigger_correlation_id,
                automation_trigger_depth,
            )
        except Exception:
            if strict_events:
                raise
            log.exception("Error creating automation list_joined trigger event")

    return {
        "list_id": list_id,
        "list_name": lst.get("name"),
        "added": added,
    }


def _remove_contact_from_list(
    db: DB,
    cid: str,
    contact_id: int,
    contact_email: str,
    list_id: str,
    automation_trigger_source: JsonObj | None = None,
    automation_trigger_correlation_id: str | None = None,
    automation_trigger_depth: int = 0,
    strict_events: bool = False,
) -> JsonObj:
    lst = db.lists.get(list_id)
    if lst is None:
        raise falcon.HTTPBadRequest(
            title="Automation list is missing",
            description="The published list node references a contact list that was not found.",
        )

    contact = db.row(
        f"""
        select c.props
        from contacts."contacts_{cid}" c
        join contacts."contact_lists_{cid}" l on l.contact_id = c.contact_id
        where c.contact_id = %s and l.list_id = %s
        """,
        contact_id,
        list_id,
    )
    removed = False

    if contact is not None:
        deleted = db.execute(
            f"""
            delete from contacts."contact_lists_{cid}"
            where contact_id = %s and list_id = %s
            """,
            contact_id,
            list_id,
        ).rowcount
        removed = deleted > 0

        if removed:
            bounced, unsubscribed, complained, soft_bounced = _contact_list_counter_flags(
                {"props": contact[0]}
            )
            domain = _contact_domain(contact_email)
            if domain:
                db.execute(
                    """
                    update list_domains set count = count - 1
                    where list_id = %s and domain = %s
                    """,
                    list_id,
                    domain,
                )
                db.execute(
                    "delete from list_domains where list_id = %s and count <= 0",
                    list_id,
                )
            contacts.patch_list(
                db,
                list_id,
                -1,
                -bounced,
                -unsubscribed,
                -complained,
                -soft_bounced,
            )
            try:
                contacts.maybe_insert_list_left_trigger_event(
                    db,
                    cid,
                    contact_email,
                    contact_id,
                    list_id,
                    automation_trigger_source,
                    automation_trigger_correlation_id,
                    automation_trigger_depth,
                )
            except Exception:
                if strict_events:
                    raise
                log.exception("Error creating automation list_left trigger event")

    return {
        "list_id": list_id,
        "list_name": lst.get("name"),
        "removed": removed,
    }


def _prepare_exit_rules(rules: list[JsonObj]) -> list[JsonObj]:
    """Canonicalise tag spelling; list IDs retain exact, case-sensitive values."""
    _validate_doc(rules, EXIT_RULES_SCHEMA)
    prepared = copy.deepcopy(rules)
    for rule in prepared:
        if rule["type"] in ("has_tag", "missing_tag"):
            tags = [fix_tag(tag) for tag in rule["tags"]]
            if any(not tag for tag in tags):
                raise falcon.HTTPBadRequest(title="Input validation error",
                    description="Exit rules must select nonempty tags.")
            rule["tags"] = list(dict.fromkeys(tags))
        elif any(not value.strip() for value in rule["list_ids"]):
            raise falcon.HTTPBadRequest(title="Input validation error",
                description="Exit rules must select nonempty list IDs.")
    return prepared


def _validate_publish_exit_rules(db: DB, rules: list[JsonObj]) -> None:
    prepared = _prepare_exit_rules(rules)
    for rule in prepared:
        for list_id in rule.get("list_ids", []):
            if db.lists.get(list_id) is None:
                _validation_error("Exit rules must reference contact lists from this account.")


def _automation_publish_inputs(automation: JsonObj) -> JsonObj:
    # Keep saved review identity and the authoritative publication path aligned.
    inputs = {
        "name": automation.get("name"),
        "entry": automation.get("entry"),
        "reentry": automation.get("reentry", "once"),
        "draft": automation.get("draft"),
    }
    # Absent and explicitly empty rules both mean disabled. Preserve the review
    # identity of existing workflows; every nonempty/invalid value is included.
    if "exit_rules" in automation and automation["exit_rules"] != []:
        inputs["exit_rules"] = automation["exit_rules"]
    return inputs


def _automation_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _published_snapshot(db: DB, automation: JsonObj) -> JsonObj:
    inputs = _automation_publish_inputs(automation)
    _validate_publish_exit_rules(db, inputs.get("exit_rules", []))
    if not inputs["name"] or not inputs["name"].strip():
        _validation_error("Automation must have a name before publishing.")

    entry = inputs["entry"]
    if entry is None:
        _validation_error("Automation entry is required.")
    _validate_doc(entry, ENTRY_SCHEMA)
    entry = _published_entry(entry)
    for trigger in _entry_triggers(entry):
        if trigger.get("type") in ("list_joined", "list_left") and db.lists.get(trigger.get("list_id")) is None:
            _validation_error("List entry trigger must reference a contact list from this account.")
        if trigger.get("type") in ("segment_entered", "segment_left") and db.segments.get(trigger.get("segment_id")) is None:
            _validation_error("Segment entry trigger must reference a segment from this account.")

    reentry = inputs["reentry"]
    _validate_doc(reentry, REENTRY_SCHEMA)

    draft = inputs["draft"]
    if draft is None:
        _validation_error("Automation draft workflow is required.")
    _validate_doc(draft, DRAFT_SCHEMA)

    nodes = draft.get("nodes") or []
    if not nodes:
        _validation_error("Automation draft must contain at least one node.")
    _validate_unique_node_ids(nodes, "Automation publish validation failed")
    node_positions = {node.get("id"): index for index, node in enumerate(nodes)}
    node_ids = set(node_positions.keys())
    for index, node in enumerate(nodes):
        if not node.get("id"):
            _validation_error("Every automation node must have a stable ID.")
        if not node.get("label") or not node.get("label").strip():
            _validation_error("Every automation node must have a label.")
        if node.get("type") == "add_tag" and not _action_tags(node):
            _validation_error("Add tag nodes must have draft tag configuration.")
        if node.get("type") == "remove_tag" and not _action_tags(node):
            _validation_error("Remove tag nodes must have draft tag configuration.")
        if node.get("type") == "remove_automation":
            _remove_action_target(db, automation.get("id"), node.get("automation_id"))
        if node.get("type") == "enrol_automation":
            _enrol_action_target(db, automation.get("id"), node.get("automation_id"))
        if node.get("type") in ("add_to_list", "remove_from_list"):
            list_ids = _action_lists(node)
            if not list_ids:
                _validation_error("%s nodes must select a contact list." % node.get("type"))
            for list_id in list_ids:
                if db.lists.get(list_id) is None:
                    _validation_error(
                        "%s node at step %s must reference a contact list from this account."
                        % (node.get("type"), index + 1)
                    )
        if node.get("type") == "if_has_tag":
            _validate_tag_condition_node(node, node_ids, "If has tag")
        if node.get("type") == "if_missing_tag":
            _validate_tag_condition_node(node, node_ids, "If missing tag")
        if node.get("type") == "if_conditions":
            _validate_conditions_node(db, automation, node, node_ids)
        if node.get("type") in ("if_opened_email", "if_clicked_email"):
            node_label = "If opened email" if node.get("type") == "if_opened_email" else "If clicked email"
            automation_email_id = node.get("automation_email_id")
            if not automation_email_id:
                _validation_error("%s nodes must select an automation email." % node_label)
            if not _automation_email_exists(
                db,
                automation.get("cid"),
                automation.get("id"),
                automation_email_id,
            ):
                _validation_error(
                    "%s node at step %s must reference an email from this automation."
                    % (node_label, index + 1)
                )
            if not node.get("yes_node_id"):
                _validation_error("%s nodes must have a yes target." % node_label)
            if not node.get("no_node_id"):
                _validation_error("%s nodes must have a no target." % node_label)
            if node.get("yes_node_id") not in node_ids:
                _validation_error("%s yes target must exist in the draft workflow." % node_label)
            if node.get("no_node_id") not in node_ids:
                _validation_error("%s no target must exist in the draft workflow." % node_label)
            if node.get("yes_node_id") == node.get("id") or node.get("no_node_id") == node.get("id"):
                _validation_error("%s nodes cannot target themselves." % node_label)
            if node.get("type") == "if_clicked_email":
                click_match = _automation_click_match_mode(node.get("click_match"))
                if click_match in ("url_exact", "url_prefix") and not _normalize_automation_click_url(node.get("link_url")):
                    _validation_error("If clicked email URL conditions must have a link URL.")
        if node.get("type") == "go_to":
            target_node_id = node.get("target_node_id")
            if not target_node_id:
                _validation_error("Go to nodes must have a target.")
            if target_node_id not in node_ids:
                _validation_error("Go to target must exist in the draft workflow.")
            if target_node_id == node.get("id"):
                _validation_error("Go to nodes cannot target themselves.")
        if node.get("type") == "send_email":
            automation_email_id = node.get("automation_email_id")
            if not automation_email_id:
                _validation_error("Send email nodes must select an automation email.")
            if not _automation_email_exists(
                db,
                automation.get("cid"),
                automation.get("id"),
                automation_email_id,
            ):
                _validation_error(
                    "Send email node at step %s must reference an email from this automation."
                    % (index + 1)
                )
        if node.get("type") == "wait_duration" and "wait_until" in node:
            _wait_deadline(node["wait_until"])
        elif node.get("type") == "wait_duration":
            total_minutes = _duration_minutes(node.get("duration", {}))
            if total_minutes < 5:
                _validation_error("Wait duration nodes must wait at least 5 minutes.")
            if total_minutes > 365 * 24 * 60:
                _validation_error("Wait duration nodes cannot wait more than 365 days.")
    return {
        "entry": copy.deepcopy(entry),
        "reentry": reentry,
        "nodes": copy.deepcopy(nodes),
        **({"exit_rules": _prepare_exit_rules(inputs["exit_rules"])} if inputs.get("exit_rules") else {}),
    }


def _enrolment_obj(row) -> JsonObj | None:
    if row is None:
        return None

    id, cid, automation_id, contact_id, contact_email, data = row
    data["id"] = id
    data["cid"] = cid
    data["automation_id"] = automation_id
    data["contact_id"] = contact_id
    data["contact_email"] = contact_email
    return data


def _automation_email_obj(row) -> JsonObj | None:
    if row is None:
        return None

    id, cid, automation_id, data = row
    data["id"] = id
    data["cid"] = cid
    data["automation_id"] = automation_id
    for field in ("fromname", "fromemail", "replyto", "returnpath"):
        data[field] = data.get(field) or ""
    return data


def _default_automation_email(doc: JsonObj | None = None) -> JsonObj:
    doc = copy.deepcopy(doc or {})
    now = _utc_now()
    name = (doc.get("name") or "New automation email").strip()
    subject = (doc.get("subject") or "Click Here to Edit").strip()
    email_type = doc["type"] if "type" in doc else "raw"

    return {
        "name": name or "New automation email",
        "subject": subject or "Click Here to Edit",
        "preheader": doc.get("preheader", ""),
        "fromname": doc.get("fromname", ""),
        "fromemail": doc.get("fromemail", ""),
        "replyto": doc.get("replyto", ""),
        "returnpath": doc.get("returnpath", ""),
        "type": email_type,
        "rawText": doc.get("rawText") or "<p>Hello</p>",
        "parts": doc.get("parts") or [],
        "bodyStyle": doc.get("bodyStyle") or {},
        "created": now,
        "modified": now,
    }


def _prepare_automation_email_patch(doc: JsonObj) -> JsonObj:
    patch = copy.deepcopy(doc)
    if "name" in patch:
        patch["name"] = (patch.get("name") or "").strip()
        if not patch["name"]:
            raise falcon.HTTPBadRequest(
                title="Invalid email name",
                description="Automation email name is required.",
            )
    if "subject" in patch:
        patch["subject"] = (patch.get("subject") or "").strip()
        if not patch["subject"]:
            raise falcon.HTTPBadRequest(
                title="Invalid email subject",
                description="Automation email subject is required.",
            )
    for field in ("fromname", "fromemail", "replyto", "returnpath"):
        if field in patch:
            patch[field] = (patch.get(field) or "").strip()
    if "type" in patch and patch["type"] not in ("", "raw", "wysiwyg", "beefree"):
        raise falcon.HTTPBadRequest(
            title="Invalid email type",
            description="Automation email type must be raw, wysiwyg or beefree.",
        )
    patch["modified"] = _utc_now()
    return patch


def _automation_for_email_route(db: DB, automation_id: str) -> JsonObj:
    automation = db.automations.get(automation_id)
    if automation is None:
        raise falcon.HTTPForbidden()
    return automation


def _get_automation_email(
    db: DB,
    cid: str,
    automation_id: str,
    email_id: str,
) -> JsonObj:
    email = _automation_email_obj(
        db.row(
            """
            select id, cid, automation_id, data
            from automation_emails
            where cid = %s and automation_id = %s and id = %s
            """,
            cid,
            automation_id,
            email_id,
        )
    )
    if email is None:
        raise falcon.HTTPForbidden()
    for field in ("fromname", "fromemail", "replyto", "returnpath"):
        email[field] = email.get(field) or ""
    return email


def _unique_automation_email_name(
    db: DB,
    cid: str,
    automation_id: str,
    name: str,
) -> str:
    base = (name or "Automation email").strip() or "Automation email"
    candidate = "Copy of %s" % base
    existing = db.single(
        """
        select id
        from automation_emails
        where cid = %s and automation_id = %s and data->>'name' = %s
        limit 1
        """,
        cid,
        automation_id,
        candidate,
    )
    if existing is None:
        return candidate

    orig, i = get_orig(candidate)
    while True:
        candidate = "%s (%s)" % (orig, i)
        existing = db.single(
            """
            select id
            from automation_emails
            where cid = %s and automation_id = %s and data->>'name' = %s
            limit 1
            """,
            cid,
            automation_id,
            candidate,
        )
        if existing is None:
            return candidate
        i += 1


def _automation_email_copy_data(
    db: DB,
    cid: str,
    target_automation_id: str,
    source_email: JsonObj,
) -> JsonObj:
    now = _utc_now()
    data = {
        "name": _unique_automation_email_name(
            db,
            cid,
            target_automation_id,
            source_email.get("name") or "Automation email",
        ),
        "subject": source_email.get("subject") or "Click Here to Edit",
        "preheader": source_email.get("preheader") or "",
        "fromname": source_email.get("fromname") or "",
        "fromemail": source_email.get("fromemail") or "",
        "replyto": source_email.get("replyto") or "",
        "returnpath": source_email.get("returnpath") or "",
        "type": source_email["type"] if "type" in source_email else "raw",
        "rawText": source_email.get("rawText") or "",
        "parts": copy.deepcopy(source_email.get("parts") or []),
        "bodyStyle": copy.deepcopy(source_email.get("bodyStyle") or {}),
        "created": now,
        "modified": now,
    }
    return _prepare_automation_email_patch(data)


def _transactional_template_obj(row) -> JsonObj | None:
    if row is None:
        return None

    id, cid, data = row
    data["id"] = id
    data["cid"] = cid
    return data


def _broadcast_source_obj(row) -> JsonObj | None:
    if row is None:
        return None

    id, cid, data = row
    data["id"] = id
    data["cid"] = cid
    return data


def _funnel_message_source_obj(row) -> JsonObj | None:
    if row is None:
        return None

    message_id, cid, message_data, funnel_id, funnel_data = row
    message_data["id"] = message_id
    message_data["cid"] = cid
    message_data["source_funnel_id"] = funnel_id
    message_data["source_funnel_name"] = funnel_data.get("name") or funnel_id
    funnel_meta = None
    for item in funnel_data.get("messages") or []:
        if item.get("id") == message_id:
            funnel_meta = item
            break
    if funnel_meta is None:
        raise falcon.HTTPBadRequest(
            title="Invalid funnel message source",
            description="The selected funnel message is not referenced by its funnel metadata.",
        )
    message_data["name"] = "%s: %s" % (
        message_data["source_funnel_name"],
        message_data.get("subject") or "Untitled message",
    )
    for field in ("fromname", "returnpath", "fromemail", "replyto"):
        message_data[field] = funnel_meta.get(field) or ""
    return message_data


def _node_references_automation_email(node: JsonObj, email_id: str) -> bool:
    return (
        node.get("email_id") == email_id
        or node.get("automation_email_id") == email_id
        or (node.get("type") == "if_conditions" and any(
            item.get("automation_email_id") == email_id
            for item in (node.get("condition") or {}).get("items", [])
        ))
    )


def _automation_references_email(automation: JsonObj, email_id: str) -> JsonObj | None:
    for workflow_name in ("draft", "published"):
        workflow = automation.get(workflow_name) or {}
        for index, node in enumerate(workflow.get("nodes") or []):
            if _node_references_automation_email(node, email_id):
                return {
                    "workflow": workflow_name,
                    "step": index + 1,
                    "node_id": node.get("id"),
                    "node_label": node.get("label"),
                    "node_type": node.get("type"),
                }
    return None


def _published_enrolment_context(automation: JsonObj) -> tuple[JsonObj, List[JsonObj], str]:
    published = automation.get("published")
    if not published:
        raise falcon.HTTPBadRequest(
            title="Automation is not published",
            description="Publish the automation before enrolling contacts.",
        )

    nodes = published.get("nodes") or []
    if not nodes:
        raise falcon.HTTPBadRequest(
            title="Automation has no published nodes",
            description="Publish a workflow with at least one node before enrolling contacts.",
        )

    reentry = published.get("reentry", automation.get("reentry", "once"))
    _validate_doc(reentry, REENTRY_SCHEMA)
    return published, nodes, reentry


def _enrol_action_target(db: DB, source_id: str, target_id: str) -> JsonObj:
    if not isinstance(target_id, str) or not target_id or target_id == source_id:
        _validation_error("Enrol in another automation must select a different automation.")
    target = db.automations.get(target_id)
    if not target or target.get("status") not in ("published", "paused"):
        _validation_error("Enrol in another automation must target a published automation in this account.")
    _, nodes, _ = _published_enrolment_context(target)
    _validate_doc({"nodes": nodes}, DRAFT_SCHEMA)
    _validate_unique_node_ids(nodes)
    return target


def _commit_automation_enrolment_action(db: DB, cid: str, source_id: str,
        enrolment: JsonObj, node: JsonObj, claim_token: str, run_id: str,
        success: JsonObj, update: JsonObj, visited: List[str], inherited: list) -> None:
    """Target creation and source acknowledgement are one database-only action."""
    target_id = node.get("automation_id")
    if not isinstance(target_id, str) or not target_id or target_id == source_id:
        _validation_error("Enrol in another automation must select a different automation.")
    depth = _safe_int(enrolment.get("trigger_depth"), 0) + 1
    if depth >= _automation_trigger_max_depth():
        _validation_error("Cross-automation enrolment depth limit reached. Review the chain before resuming.")
    try:
        with db.transaction():
            # Opposite-direction actions acquire both automation locks in the
            # same order. Never run a destination action in this transaction.
            for aid in sorted((source_id, target_id)):
                if db.single("select id from automations where cid = %s and id = %s for update", cid, aid) is None:
                    _validation_error("The source or target automation is no longer available in this account.")
            current = db.row("select data from automation_enrolments where cid = %s and automation_id = %s and id = %s for update",
                             cid, source_id, enrolment["id"])
            if not current or current[0].get("claim_token") != claim_token:
                raise falcon.HTTPConflict(title="Automation execution claim was lost",
                    description="The source claim changed before target enrolment. No target enrolment was created.")
            target = _enrol_action_target(db, source_id, target_id)
            if db.single(f'select contact_id from contacts."contacts_{cid}" where contact_id = %s for update', enrolment["contact_id"]) is None:
                _validation_error("The contact no longer exists in this account.")
            outcome = _create_enrolment_for_contact_locked(db, cid, target_id, target,
                enrolment["contact_id"], enrolment["contact_email"], "automation:%s" % enrolment["id"],
                enrolment.get("trigger_correlation_id") or "automation:%s" % enrolment["id"], depth)
            if outcome["status"] == "enrolled":
                trace = copy.deepcopy(inherited)
                trace.extend([source_id, nid] for nid in visited if [source_id, nid] not in trace)
                db.execute("update automation_enrolments set data = data || %s where cid = %s and id = %s",
                    {"cross_automation_visits": trace, "source_automation_id": source_id,
                     "source_enrolment_id": enrolment["id"], "source_node_id": node["id"],
                     "source_step_run_id": run_id}, cid, outcome["enrolment_id"])
            success.update({"action": "enrol_automation", "automation_id": target_id,
                "outcome": outcome["status"], "reason": outcome.get("reason"),
                "target_enrolment_id": outcome.get("enrolment_id") or outcome.get("existing_enrolment_id")})
            source = db.automations.get(source_id)
            if source.get("status") == "paused" and update["status"] == "ready":
                update.update(status="paused_ready", paused_at=source.get("paused_at") or _utc_now())
            _patch_step_run(db, cid, run_id, success)
            _advance_claimed_enrolment(db, cid, source_id, enrolment["id"], claim_token, update)
    except falcon.HTTPError:
        raise
    except Exception:
        log.exception("Cross-automation enrolment transaction failed")
        raise falcon.HTTPBadRequest(title="Automation enrolment action failed",
            description="No target enrolment or source advancement was committed. The source is held for review.")


def _remove_action_target(db: DB, source_id: str, target_id: str) -> JsonObj:
    if not isinstance(target_id, str) or not target_id or target_id == source_id:
        _validation_error("Remove from another automation must select a different automation.")
    target = db.automations.get(target_id)
    if not target or target.get("status") not in ("published", "paused") or not target.get("published"):
        _validation_error("Remove from another automation must target a published automation in this account.")
    # Cancellation does not execute or traverse the target graph.
    return target


def _commit_automation_removal_action(db: DB, cid: str, source_id: str,
        enrolment: JsonObj, node: JsonObj, claim_token: str, run_id: str,
        success: JsonObj, update: JsonObj) -> None:
    """Cancel target passes and acknowledge the source in one short transaction."""
    target_id = node.get("automation_id")
    if not isinstance(target_id, str) or not target_id or target_id == source_id:
        _validation_error("Remove from another automation must select a different automation.")
    try:
        with db.transaction():
            # Same ordering as enrol_automation, publication, claims and pause.
            # Never acquire these locks around external action execution.
            for aid in sorted((source_id, target_id)):
                if db.single("select id from automations where cid = %s and id = %s for update", cid, aid) is None:
                    _validation_error("The source or target automation is no longer available in this account.")
            current = db.row("select data from automation_enrolments where cid = %s and automation_id = %s and id = %s for update",
                             cid, source_id, enrolment["id"])
            if not current or current[0].get("claim_token") != claim_token:
                raise falcon.HTTPConflict(title="Automation execution claim was lost",
                    description="The source claim changed before target removal. No target enrolment was cancelled.")
            _remove_action_target(db, source_id, target_id)
            rows = db.execute("""
                select id, data from automation_enrolments
                where cid = %s and automation_id = %s and contact_id = %s
                    and (coalesce(data->>'status', '') <> all(%s)
                         or nullif(data->>'claim_token', '') is not null)
                order by id for update
                """, cid, target_id, enrolment["contact_id"], list(TERMINAL_ENROLMENT_STATUSES)).fetchall()
            # Validate the complete cohort before changing any target pass.
            for _, previous in rows:
                if previous.get("status") == "running" or previous.get("claim_token"):
                    raise falcon.HTTPConflict(title="Target automation enrolment is currently running",
                        description="No contacts were removed. The source is held. Let the target action finish, or use existing stale-claim recovery, then retry the source step.")
                if previous.get("status") not in AutomationEnrolmentCancel.CANCELLABLE_STATUSES:
                    raise falcon.HTTPConflict(title="Target automation enrolment state is invalid",
                        description="No contacts were removed. Review the target enrolment state before retrying the held source step.")
            now = _utc_now()
            for target_enrolment_id, previous in rows:
                db.execute("""
                    update automation_enrolments set data = data || %s
                    where cid = %s and automation_id = %s and id = %s
                    """, {
                        **_claim_clear_patch(), **_retry_clear_patch(),
                        "status": "cancelled", "modified": now, "cancelled_at": now,
                        "cancelled_by_uid": None,
                        "cancelled_metadata": {
                            "source": "automation_action", "previous_status": previous["status"],
                            "source_automation_id": source_id, "source_enrolment_id": enrolment["id"],
                            "source_node_id": node["id"], "source_step_run_id": run_id,
                        },
                        "wake_at": None, "wait": None, "paused_at": None, "resumed_at": None,
                    }, cid, target_id, target_enrolment_id)
            success.update({"action": "remove_automation", "automation_id": target_id,
                "outcome": "cancelled" if rows else "skipped", "reason": None if rows else "no_active_enrolment",
                "removed_count": len(rows), "target_enrolment_ids": [row[0] for row in rows]})
            source = db.automations.get(source_id)
            if source.get("status") == "paused" and update["status"] == "ready":
                update.update(status="paused_ready", paused_at=source.get("paused_at") or now)
            _patch_step_run(db, cid, run_id, success)
            _advance_claimed_enrolment(db, cid, source_id, enrolment["id"], claim_token, update)
    except falcon.HTTPError:
        raise
    except Exception:
        log.exception("Cross-automation removal transaction failed")
        raise falcon.HTTPBadRequest(title="Automation removal action failed",
            description="No target cancellation or source advancement was committed. The source is held for review.")


@contextmanager
def _locked_automation(db: DB, cid: str, automation_id: str):
    # DB.transaction() is not nestable. Reuse an existing transaction when a
    # caller owns one; otherwise keep this state transition short.
    with db.transaction() if db.conn.autocommit else nullcontext():
        if db.single(
            "select id from automations where cid = %s and id = %s for update",
            cid, automation_id,
        ) is None:
            raise falcon.HTTPForbidden()
        yield db.automations.get(automation_id)


def _automation_state_transition(method):
    @wraps(method)
    def locked(self, req, resp, id, *args, **kwargs):
        check_noadmin(req)
        db = req.context["db"]
        with _locked_automation(db, db.get_cid(), id):
            return method(self, req, resp, id, *args, **kwargs)
    return locked


def _create_enrolment_for_contact(
    db: DB,
    cid: str,
    automation_id: str,
    automation: JsonObj,
    contact_id: int,
    contact_email: str,
    source: str,
    trigger_correlation_id: str | None = None,
    trigger_depth: int | None = None,
) -> JsonObj:
    # Bulk/trigger callers may have loaded this automation before publication.
    with _locked_automation(db, cid, automation_id) as current:
        return _create_enrolment_for_contact_locked(
            db, cid, automation_id, current, contact_id, contact_email, source,
            trigger_correlation_id, trigger_depth,
        )


def _create_enrolment_for_contact_locked(
    db: DB,
    cid: str,
    automation_id: str,
    automation: JsonObj,
    contact_id: int,
    contact_email: str,
    source: str,
    trigger_correlation_id: str | None = None,
    trigger_depth: int | None = None,
) -> JsonObj:
    published, nodes, reentry = _published_enrolment_context(automation)
    if exit_rules.matching_rule(db, cid, contact_id, published):
        return {"status": "skipped", "reason": "exit_rule", "title": "Contact excluded by exit rule",
            "description": "This contact matches a published exit rule and cannot enter this automation.",
            "contact_id": contact_id, "contact_email": contact_email}

    existing_enrolment_id = db.single(
        """
        select id
        from automation_enrolments
        where cid = %s and automation_id = %s and contact_id = %s
        limit 1
        """,
        cid,
        automation_id,
        contact_id,
    )
    if reentry == "once" and existing_enrolment_id:
        return {
            "status": "skipped",
            "reason": "once",
            "title": "Contact already enrolled",
            "description": "This automation only allows a contact to enter once.",
            "contact_id": contact_id,
            "contact_email": contact_email,
            "existing_enrolment_id": existing_enrolment_id,
        }

    if reentry == "multiple":
        active_enrolment_id = db.single(
            """
            select id
            from automation_enrolments
            where cid = %s
                and automation_id = %s
                and contact_id = %s
                and coalesce(data->>'status', '') <> all(%s)
            limit 1
            """,
            cid,
            automation_id,
            contact_id,
            list(TERMINAL_ENROLMENT_STATUSES),
        )
        if active_enrolment_id:
            return {
                "status": "skipped",
                "reason": "active_pass",
                "title": "Contact already has an active automation pass",
                "description": "This contact already has an active enrolment in this automation.",
                "contact_id": contact_id,
                "contact_email": contact_email,
                "existing_enrolment_id": active_enrolment_id,
            }

    now = _utc_now()
    enrolment_id = shortuuid.uuid()
    data = {
        "status": "held" if automation.get("status") == "paused" else "ready",
        "source": source,
        "current_node_id": nodes[0]["id"],
        "published_revision": automation.get("published_revision"),
        "created": now,
        "modified": now,
    }
    if trigger_correlation_id:
        data["trigger_correlation_id"] = trigger_correlation_id
    if trigger_depth is not None:
        data["trigger_depth"] = trigger_depth

    db.execute(
        """
        insert into automation_enrolments
            (id, cid, automation_id, contact_id, contact_email, data)
        values (%s, %s, %s, %s, %s, %s)
        """,
        enrolment_id,
        cid,
        automation_id,
        contact_id,
        contact_email,
        data,
    )

    return {
        "status": "enrolled",
        "enrolment_id": enrolment_id,
        "contact_id": contact_id,
        "contact_email": contact_email,
    }


def _empty_bulk_result() -> JsonObj:
    return {
        "enrolled_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "skipped": [],
        "errors": [],
    }


def _record_bulk_outcome(result: JsonObj, outcome: JsonObj) -> None:
    if outcome.get("status") == "enrolled":
        result["enrolled_count"] += 1
    elif outcome.get("status") == "skipped":
        result["skipped_count"] += 1
        if len(result["skipped"]) < BULK_DETAIL_LIMIT:
            result["skipped"].append({
                "contact_id": outcome.get("contact_id"),
                "contact_email": outcome.get("contact_email"),
                "reason": outcome.get("reason"),
                "description": outcome.get("description"),
                "existing_enrolment_id": outcome.get("existing_enrolment_id"),
            })
    else:
        result["error_count"] += 1
        if len(result["errors"]) < BULK_DETAIL_LIMIT:
            result["errors"].append(outcome)


def _finish_bulk_list_enrolment(data: List[JsonObj]) -> JsonObj:
    result = _empty_bulk_result()
    for item in data:
        result["enrolled_count"] += int(item.get("enrolled_count", 0) or 0)
        result["skipped_count"] += int(item.get("skipped_count", 0) or 0)
        result["error_count"] += int(item.get("error_count", 0) or 0)
        for skipped in item.get("skipped", []):
            if len(result["skipped"]) < BULK_DETAIL_LIMIT:
                result["skipped"].append(skipped)
        for error in item.get("errors", []):
            if len(result["errors"]) < BULK_DETAIL_LIMIT:
                result["errors"].append(error)

    return {
        "complete": True,
        "result": result,
    }


def _check_automation_gather_owner(db: DB, gatherid: str, cid: str, name: str) -> None:
    row = db.row(
        "select cid, data->>'name' from taskgather where id = %s",
        gatherid,
    )
    if row is None:
        return

    gather_cid, gather_name = row
    if gather_cid != cid or gather_name != name:
        raise falcon.HTTPForbidden()


def _step_run_obj(row) -> JsonObj | None:
    if row is None:
        return None

    id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data = row
    data["id"] = id
    data["cid"] = cid
    data["automation_id"] = automation_id
    data["enrolment_id"] = enrolment_id
    data["contact_id"] = contact_id
    data["node_id"] = node_id
    data["node_type"] = node_type
    return data


def _automation_execution_route(db: DB, cid: str) -> JsonObj:
    oldcid = db.get_cid()
    db.set_cid(None)
    try:
        company = db.companies.get(cid)
        if company is None:
            raise falcon.HTTPForbidden()

        published_routes = []
        for route_id in company.get("routes") or []:
            route = db.routes.get(route_id)
            if route is not None and route.get("published") is not None:
                published_routes.append(route)

        if not published_routes:
            raise falcon.HTTPBadRequest(
                title="No postal route available",
                description="Assign exactly one published postal route to this account before sending automation emails.",
            )
        if len(published_routes) > 1:
            raise falcon.HTTPBadRequest(
                title="Multiple postal routes available",
                description="Automation email execution requires exactly one published postal route for this account.",
            )
        return published_routes[0]
    finally:
        db.set_cid(oldcid)


def _automation_email_sender(email_doc: JsonObj) -> tuple[str, str, str, str]:
    fromname = remove_newlines(email_doc.get("fromname", "").strip())
    returnpath = remove_newlines(email_doc.get("returnpath", "").strip())
    fromemail = remove_newlines((email_doc.get("fromemail") or returnpath).strip())
    replyto = remove_newlines((email_doc.get("replyto") or fromemail or returnpath).strip())

    if not fromname:
        raise falcon.HTTPBadRequest(
            title="Automation email sender is incomplete",
            description="The selected automation email is missing From Name.",
        )
    if not returnpath:
        raise falcon.HTTPBadRequest(
            title="Automation email sender is incomplete",
            description="The selected automation email is missing Sender Email Address.",
        )

    return fromname, fromemail, returnpath, replyto


def _automation_preflight_message(severity: str, code: str, message: str) -> JsonObj:
    return {
        "severity": severity,
        "code": code,
        "message": _bounded_error_text(message),
    }


def _automation_email_has_body(email_doc: JsonObj) -> bool:
    email_type = email_doc.get("type", "raw")
    raw = email_doc.get("rawText")
    parts = email_doc.get("parts") or []
    if email_type == "beefree":
        try:
            bee_doc = json.loads(str(raw or ""))
        except (TypeError, ValueError):
            return False
        return bool(str((bee_doc or {}).get("html") or "").strip())
    if email_type in ("raw", "wysiwyg"):
        return bool(str(raw or "").strip())
    return bool(str(raw or "").strip()) or bool(parts)


def _preflight_email_address(address: str, label: str, required: bool) -> JsonObj | None:
    value = (address or "").strip()
    if not value:
        if required:
            return _automation_preflight_message(
                "error",
                "missing_%s" % label,
                "%s is required." % label.replace("_", " ").title(),
            )
        return None
    _, parsed = email.utils.parseaddr(value)
    if "@" not in (parsed or value):
        return _automation_preflight_message(
            "error",
            "invalid_%s" % label,
            "%s must be a valid email address." % label.replace("_", " ").title(),
        )
    return None


def _route_policy_ids(route: JsonObj) -> list[str]:
    published = route.get("published") or {}
    policy_ids = []
    for rule in published.get("rules") or route.get("rules") or []:
        for split in rule.get("splits") or []:
            policy = split.get("policy") or ""
            if policy:
                policy_ids.append(policy)
    return policy_ids


def _preflight_backend_row(
    backend_type: str,
    backend_id: str,
    name: str,
    source: str,
    pct: Any = None,
    policy_id: str | None = None,
) -> JsonObj:
    row: JsonObj = {
        "type": backend_type,
        "id": _bounded_error_text(backend_id or ""),
        "name": _bounded_error_text(name or backend_id or ""),
        "source": source,
    }
    if pct is not None:
        row["pct"] = pct
    if policy_id:
        row["policy_id"] = _bounded_error_text(policy_id)
    return row


def _preflight_backend_maps(db: DB) -> tuple[dict[str, JsonObj], dict[str, dict[str, JsonObj]]]:
    policies = {policy["id"]: policy for policy in db.policies.find()}
    backends = {
        "mailgun": {backend["id"]: backend for backend in db.mailgun.find()},
        "ses": {backend["id"]: backend for backend in db.ses.find()},
        "sparkpost": {backend["id"]: backend for backend in db.sparkpost.find()},
        "easylink": {backend["id"]: backend for backend in db.easylink.find()},
        "smtprelay": {backend["id"]: backend for backend in db.smtprelays.find()},
        "mta_sink": {backend["id"]: backend for backend in db.sinks.find()},
        "debug_log": {backend["id"]: backend for backend in db.debug_email_backends.find()},
    }
    return policies, backends


def _preflight_direct_backend(
    policy_id: str,
    backends: dict[str, dict[str, JsonObj]],
    pct: Any,
) -> JsonObj | None:
    for backend_type, backend_by_id in backends.items():
        backend = backend_by_id.get(policy_id)
        if backend is not None:
            return _preflight_backend_row(
                backend_type,
                policy_id,
                backend.get("name") or policy_id,
                "route_split",
                pct,
            )
    return None


def _preflight_route_backend_details(db: DB, route: JsonObj) -> JsonObj:
    details: JsonObj = {
        "backend_types": [],
        "backends": [],
        "unresolved": [],
        "has_debug": False,
        "has_drop_all": False,
        "has_live_provider": False,
        "has_unresolved": False,
    }
    published = route.get("published") or {}
    policies, backends = _preflight_backend_maps(db)

    for rule_index, rule in enumerate(published.get("rules") or []):
        for split_index, split in enumerate(rule.get("splits") or []):
            policy_id = split.get("policy") or ""
            pct = split.get("pct")
            if not policy_id:
                details["has_drop_all"] = True
                continue

            direct = _preflight_direct_backend(policy_id, backends, pct)
            if direct is not None:
                details["backends"].append(direct)
                continue

            policy = policies.get(policy_id)
            if policy is None:
                details["has_unresolved"] = True
                details["unresolved"].append(
                    {
                        "id": _bounded_error_text(policy_id),
                        "source": "route_split",
                        "reason": "missing_policy_or_backend",
                        "rule": rule_index + 1,
                        "split": split_index + 1,
                    }
                )
                continue

            published_policy = policy.get("published")
            if not published_policy:
                details["has_unresolved"] = True
                details["unresolved"].append(
                    {
                        "id": _bounded_error_text(policy_id),
                        "source": "route_split",
                        "reason": "unpublished_policy",
                        "rule": rule_index + 1,
                        "split": split_index + 1,
                    }
                )
                continue

            sinks = published_policy.get("sinks") or []
            if not sinks:
                details["has_unresolved"] = True
                details["unresolved"].append(
                    {
                        "id": _bounded_error_text(policy_id),
                        "source": "delivery_policy",
                        "reason": "policy_has_no_sinks",
                        "rule": rule_index + 1,
                        "split": split_index + 1,
                    }
                )
                continue

            for sink in sinks:
                sink_id = sink.get("sink") or ""
                sink_obj = backends["mta_sink"].get(sink_id)
                if sink_obj is None:
                    details["has_unresolved"] = True
                    details["unresolved"].append(
                        {
                            "id": _bounded_error_text(sink_id),
                            "policy_id": _bounded_error_text(policy_id),
                            "source": "policy_sink",
                            "reason": "missing_sink",
                            "rule": rule_index + 1,
                            "split": split_index + 1,
                        }
                    )
                    continue
                details["backends"].append(
                    _preflight_backend_row(
                        "mta_sink",
                        sink_id,
                        sink_obj.get("name") or sink_id,
                        "policy_sink",
                        sink.get("pct"),
                        policy_id,
                    )
                )

    seen_types = []
    seen_backend_keys = set()
    deduped_backends = []
    for backend in details["backends"]:
        key = (backend.get("type"), backend.get("id"), backend.get("source"), backend.get("policy_id"))
        if key in seen_backend_keys:
            continue
        seen_backend_keys.add(key)
        deduped_backends.append(backend)
        backend_type = backend.get("type")
        if backend_type and backend_type not in seen_types:
            seen_types.append(backend_type)

    details["backends"] = deduped_backends[:25]
    details["backend_types"] = seen_types
    details["has_debug"] = "debug_log" in seen_types
    details["has_live_provider"] = bool([t for t in seen_types if t != "debug_log"])
    details["has_unresolved"] = bool(details["unresolved"])
    details["unresolved"] = details["unresolved"][:25]
    return details


def _automation_preflight_route(db: DB, cid: str) -> JsonObj:
    result: JsonObj = {
        "status": "unknown",
        "route_id": None,
        "route_name": "",
        "assigned": False,
        "published": False,
        "ready_for_debug": False,
        "debug": False,
        "drop_all": False,
        "mixed": False,
        "backend_types": [],
        "backends": [],
        "unresolved": [],
        "errors": [],
        "warnings": [],
    }
    oldcid = db.get_cid()
    db.set_cid(None)
    try:
        company = db.companies.get(cid)
        if company is None:
            result["errors"].append(
                _automation_preflight_message("error", "missing_account", "Customer account was not found.")
            )
            result["status"] = "missing"
            return result

        published_routes = []
        for route_id in company.get("routes") or []:
            route = db.routes.get(route_id)
            if route is not None and route.get("published") is not None:
                published_routes.append(route)

        if not published_routes:
            result["status"] = "missing"
            result["errors"].append(
                _automation_preflight_message(
                    "error",
                    "no_route",
                    "Assign exactly one published postal route to this account before sending automation emails.",
                )
            )
            return result
        if len(published_routes) > 1:
            result["status"] = "multiple"
            result["assigned"] = True
            result["published"] = True
            result["routes"] = [
                {
                    "route_id": route.get("id"),
                    "route_name": route.get("name") or route.get("id") or "",
                    "published": True,
                    "assigned": True,
                }
                for route in published_routes[:10]
            ]
            result["errors"].append(
                _automation_preflight_message(
                    "error",
                    "multiple_routes",
                    "Automation email execution requires exactly one published postal route for this account.",
                )
            )
            return result

        route = published_routes[0]
        result["route_id"] = route.get("id")
        result["route_name"] = route.get("name") or route.get("id") or ""
        result["assigned"] = True
        result["published"] = True
        policy_ids = _route_policy_ids(route)
        if not policy_ids:
            result["status"] = "drop_all"
            result["drop_all"] = True
            result["errors"].append(
                _automation_preflight_message(
                    "error",
                    "drop_all_route",
                    "The assigned postal route has no sending backend. Real automation execution will not send email.",
                )
            )
            return result

        db.set_cid(route["cid"])
        details = _preflight_route_backend_details(db, route)
        result["backend_types"] = details["backend_types"]
        result["backends"] = details["backends"]
        result["unresolved"] = details["unresolved"]
        result["debug"] = details["has_debug"]
        result["drop_all"] = details["has_drop_all"]
        result["mixed"] = len(result["backend_types"]) > 1 or (
            bool(result["backend_types"]) and (result["drop_all"] or details["has_unresolved"])
        )

        if details["has_drop_all"]:
            result["status"] = "mixed_drop_all" if result["backend_types"] else "drop_all"
            result["errors"].append(
                _automation_preflight_message(
                    "error",
                    "drop_all_route",
                    "The assigned postal route includes a no-backend split. Real automation execution may not send email.",
                )
            )
            return result

        if details["has_unresolved"]:
            result["status"] = "mixed_unresolved" if result["backend_types"] else "unresolved"
            result["warnings"].append(
                _automation_preflight_message(
                    "warning",
                    "unresolved_route_backend",
                    "The assigned postal route includes a policy or backend that could not be resolved. Confirm route configuration before production use.",
                )
            )
            return result

        if details["has_debug"] and not details["has_live_provider"]:
            result["status"] = "debug_log"
            result["ready_for_debug"] = True
            result["mixed"] = False
            result["warnings"].append(
                _automation_preflight_message(
                    "warning",
                    "debug_route",
                    "The assigned route uses the debug_log backend. This is suitable for dev testing, not production sending.",
                )
            )
            return result
        if details["has_debug"]:
            result["status"] = "mixed_debug"
            result["mixed"] = True
            result["warnings"].append(
                _automation_preflight_message(
                    "warning",
                    "mixed_debug_route",
                    "The assigned route includes a debug_log backend split. Confirm route configuration before production use.",
                )
            )
            return result

        result["status"] = "published_route"
        return result
    finally:
        db.set_cid(oldcid)


def _automation_email_preflight(
    db: DB,
    cid: str,
    automation_id: str,
    node: JsonObj,
    step: int,
) -> JsonObj:
    node_result: JsonObj = {
        "node_id": node.get("id"),
        "step": step,
        "label": node.get("label") or "",
        "type": node.get("type"),
        "automation_email_id": node.get("automation_email_id") or "",
        "email_name": "",
        "subject": "",
        "editor_type": "",
        "errors": [],
        "warnings": [],
    }
    automation_email_id = node.get("automation_email_id")
    email_doc = _automation_email_obj(
        db.row(
            """
            select id, cid, automation_id, data
            from automation_emails
            where cid = %s and automation_id = %s and id = %s
            """,
            cid,
            automation_id,
            automation_email_id,
        )
    )
    if email_doc is None:
        node_result["errors"].append(
            _automation_preflight_message(
                "error",
                "missing_email",
                "Step %s references an automation email that was not found." % step,
            )
        )
        return node_result

    node_result["email_name"] = email_doc.get("name") or ""
    node_result["subject"] = email_doc.get("subject") or ""
    node_result["editor_type"] = email_doc.get("type", "raw")

    if not (email_doc.get("fromname") or "").strip():
        node_result["errors"].append(
            _automation_preflight_message("error", "missing_fromname", "From Name is required.")
        )
    returnpath_error = _preflight_email_address(email_doc.get("returnpath") or "", "returnpath", True)
    if returnpath_error is not None:
        node_result["errors"].append(returnpath_error)
    fromemail_error = _preflight_email_address(email_doc.get("fromemail") or "", "fromemail", False)
    if fromemail_error is not None:
        node_result["errors"].append(fromemail_error)
    replyto_error = _preflight_email_address(email_doc.get("replyto") or "", "replyto", False)
    if replyto_error is not None:
        node_result["errors"].append(replyto_error)
    if not (email_doc.get("subject") or "").strip():
        node_result["errors"].append(
            _automation_preflight_message("error", "missing_subject", "Email subject is required.")
        )
    if not _automation_email_has_body(email_doc):
        node_result["errors"].append(
            _automation_preflight_message("error", "missing_body", "Email body/content is required.")
        )

    try:
        validate_sender_domains(
            db,
            cid,
            email_doc.get("fromemail") or email_doc.get("returnpath"),
            email_doc.get("returnpath"),
        )
    except falcon.HTTPError as e:
        node_result["errors"].append(
            _automation_preflight_message(
                "error",
                "sender_domain_not_verified",
                e.description or e.title or "Sender domain is not verified.",
            )
        )

    return node_result


def _automation_send_email_preflight(db: DB, cid: str, automation: JsonObj, mode: str) -> JsonObj:
    if mode not in ("draft", "published"):
        raise falcon.HTTPBadRequest(
            title="Invalid preflight mode",
            description="mode must be draft or published.",
        )
    workflow = automation.get(mode) or {}
    nodes = workflow.get("nodes") or []
    send_nodes = [
        (index, node)
        for index, node in enumerate(nodes)
        if node.get("type") == "send_email"
    ]
    route = _automation_preflight_route(db, cid) if send_nodes else {}
    result: JsonObj = {
        "automation_id": automation.get("id"),
        "mode": mode,
        "ready": False,
        "errors": [],
        "warnings": [],
        "info": [
            _automation_preflight_message(
                "info",
                "suppression_behavior",
                "Suppressed contacts skip send_email successfully and advance without retry/backoff.",
            )
        ],
        "route": route,
        "nodes": [],
    }
    result["errors"].extend(route.get("errors") or [])
    result["warnings"].extend(route.get("warnings") or [])
    if not send_nodes:
        result["info"].append(
            _automation_preflight_message(
                "info",
                "no_send_email_nodes",
                "This workflow has no send-email nodes.",
            )
        )
    for index, node in send_nodes:
        node_result = _automation_email_preflight(db, cid, automation["id"], node, index + 1)
        result["nodes"].append(node_result)
        result["errors"].extend(node_result["errors"])
        result["warnings"].extend(node_result["warnings"])
    result["ready"] = not result["errors"]
    return result


CLAIM_STALE_AFTER = timedelta(minutes=30)
AUTOMATION_RETRY_BACKOFFS = (timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60))
AUTOMATION_MAX_RETRIES = len(AUTOMATION_RETRY_BACKOFFS)
AUTOMATION_ERROR_TEXT_LIMIT = 1000
AUTOMATION_PROCESS_DEFAULT_LIMIT = 25
AUTOMATION_PROCESS_MAX_LIMIT = 100
AUTOMATION_PROCESS_ERROR_LIMIT = 100
AUTOMATION_PROCESS_ACCOUNT_LIMIT = 50
AUTOMATION_RECOVERY_DEFAULT_LIMIT = 50
AUTOMATION_RECOVERY_MAX_LIMIT = 100
CHECK_AUTOMATION_ENROLMENTS_LOCK = 58413921
CHECK_AUTOMATION_SEGMENT_TRIGGERS_LOCK = 58413922
AUTOMATION_RETENTION_CLEANUP_LOCK = 98337413
AUTOMATION_RECOVERY_ENROLMENT_CLAIMS_LOCK = 58413931
AUTOMATION_RECOVERY_TRIGGER_EVENT_CLAIMS_LOCK = 58413932
AUTOMATION_RECOVERY_SEGMENT_SCANNER_CLAIMS_LOCK = 58413933
AUTOMATION_RETENTION_DEBUG_LOG_DAYS = 14
AUTOMATION_RETENTION_TRIGGER_EVENT_DAYS = 30
AUTOMATION_RETENTION_ACCOUNT_LIMIT = 25
AUTOMATION_RETENTION_DELETE_LIMIT = 1000
AUTOMATION_TRIGGER_DEFAULT_LIMIT = 25
AUTOMATION_TRIGGER_MAX_LIMIT = 100
AUTOMATION_TRIGGER_DETAIL_LIMIT = 100
AUTOMATION_TRIGGER_COOLDOWN_MINUTES = 15
AUTOMATION_TRIGGER_EVENT_LIST_DEFAULT_LIMIT = 50
AUTOMATION_TRIGGER_EVENT_RESPONSE_DETAIL_LIMIT = 25
AUTOMATION_TRIGGER_FINISHED_STATUSES = ("processed", "suppressed", "failed", "enrolled")
AUTOMATION_SEGMENT_TRIGGER_STATUS_DEFAULT_LIMIT = 50
AUTOMATION_SEGMENT_TRIGGER_STATUS_MAX_LIMIT = 100
AUTOMATION_SEGMENT_TRIGGER_STATUS_REFERENCE_LIMIT = 10
AUTOMATION_SEGMENT_TRIGGER_STATUS_EVENT_DAYS = 7
AUTOMATION_SEGMENT_BASELINE_DEFAULT_SEGMENT_LIMIT = 10
AUTOMATION_SEGMENT_BASELINE_MAX_SEGMENT_LIMIT = 50
AUTOMATION_SEGMENT_BASELINE_DEFAULT_BUCKET_LIMIT = 25
AUTOMATION_SEGMENT_BASELINE_MAX_BUCKET_LIMIT = 100
AUTOMATION_SEGMENT_DIFF_DEFAULT_EVENT_LIMIT = 100
AUTOMATION_SEGMENT_DIFF_MAX_EVENT_LIMIT = 500
AUTOMATION_SEGMENT_SCAN_ACCOUNT_LIMIT = 25
TAG_TRIGGER_EVENT_TYPES = ("tag_added", "tag_removed")
LIST_TRIGGER_EVENT_TYPES = ("list_joined", "list_left")
SEGMENT_TRIGGER_EVENT_TYPES = ("segment_entered", "segment_left")
SUPPORTED_TRIGGER_EVENT_TYPES = TAG_TRIGGER_EVENT_TYPES + LIST_TRIGGER_EVENT_TYPES + SEGMENT_TRIGGER_EVENT_TYPES
AUTOMATION_PROCESSING_STATUSES = (
    "ready",
    "waiting",
    "held",
    "paused_ready",
    "paused_waiting",
    "running",
    "stale_running",
    "failed",
    "completed",
    "exited",
    "cancelled",
    "total",
)


def _claim_clear_patch() -> JsonObj:
    return {
        "running_status": None,
        "claim_token": None,
        "claimed_at": None,
        "claimed_node_id": None,
        "claimed_published_revision": None,
    }


def _retry_clear_patch() -> JsonObj:
    return {
        "retry_count": None,
        "retry_after": None,
        "last_error": None,
        "last_failed_node_id": None,
        "last_failed_node_type": None,
        "last_failed_step_run_id": None,
        "last_failure_retryable": None,
        "last_failure_class": None,
    }


def _bounded_error_text(value: object) -> str:
    text = str(value or "")
    if len(text) > AUTOMATION_ERROR_TEXT_LIMIT:
        return text[:AUTOMATION_ERROR_TEXT_LIMIT] + "... [truncated]"
    return text


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _retry_after_blocks_processing(value: object, now: datetime) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        retry_after = _parse_datetime(text)
    except Exception:
        return False
    return retry_after > now


def _automation_failure_is_retryable(error: falcon.HTTPError) -> bool:
    return error.title in ("Error sending automation email", "Automation email send pending")


def _automation_failure_class(error: falcon.HTTPError, retryable: bool) -> str:
    if error.title == "Automation email send pending":
        return "coordination"
    if retryable:
        return "provider"
    if error.title in (
        "Automation email is missing",
        "Automation email sender is incomplete",
        "No postal route available",
        "Multiple postal routes available",
        "Automation branch target is missing",
        "Automation go to target is missing",
        "Current automation node is missing",
        "Duplicate automation node IDs",
        "Unsupported automation node",
    ):
        return "configuration"
    return "validation"


def _automation_failure_update(
    enrolment: JsonObj,
    error: falcon.HTTPError,
    original_status: str,
    node: JsonObj,
    node_type: str,
    run_id: str | None,
    failed_at: str,
) -> tuple[str, JsonObj]:
    retryable = _automation_failure_is_retryable(error)
    failure_class = _automation_failure_class(error, retryable)
    title = _bounded_error_text(error.title)
    description = _bounded_error_text(error.description or error.title)

    retry_count = _safe_int(enrolment.get("retry_count"), 0)
    retry_after = None
    release_status = "held"
    if retryable:
        retry_count += 1
        if retry_count > AUTOMATION_MAX_RETRIES:
            release_status = "failed"
        else:
            release_status = original_status
            retry_after = (datetime.utcnow() + AUTOMATION_RETRY_BACKOFFS[retry_count - 1]).isoformat() + "Z"

    update = {
        "last_error": {
            "title": title,
            "description": description,
            "at": failed_at,
            "retryable": retryable,
            "failure_class": failure_class,
            "retry_count": retry_count if retryable else None,
            "retry_after": retry_after,
            "status": release_status,
        },
        "last_failed_node_id": node.get("id"),
        "last_failed_node_type": node_type,
        "last_failed_step_run_id": run_id,
        "last_failure_retryable": retryable,
        "last_failure_class": failure_class,
    }
    if retryable:
        update["retry_count"] = retry_count
        update["retry_after"] = retry_after
    else:
        update["retry_count"] = 0
        update["retry_after"] = None
    return release_status, update


def _running_status(enrolment: JsonObj) -> str:
    return enrolment.get("running_status") or enrolment.get("status")


def _read_run_enrolment(db: DB, cid: str, automation_id: str, enrolment_id: str) -> JsonObj | None:
    return _enrolment_obj(
        db.row(
            f"""
            select e.id, e.cid, e.automation_id, e.contact_id, e.contact_email, e.data
            from automation_enrolments e
            join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
            where e.cid = %s and e.automation_id = %s and e.id = %s
            """,
            cid,
            automation_id,
            enrolment_id,
        )
    )


def _raise_run_not_claimable(enrolment: JsonObj | None) -> None:
    if enrolment is None:
        raise falcon.HTTPForbidden()

    status = enrolment.get("status")
    if status == "running":
        raise falcon.HTTPBadRequest(
            title="Automation enrolment is already running",
            description="This enrolment is already being executed. Try again after the current run finishes.",
        )
    if status in ("held", "paused_ready", "paused_waiting"):
        raise falcon.HTTPBadRequest(
            title="Enrolment is paused",
            description="Resume the automation before running this enrolment.",
        )
    raise falcon.HTTPBadRequest(
        title="Enrolment is not ready",
        description="Only ready or elapsed waiting enrolments can run the next automation node.",
    )


def _claim_run_enrolment(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    claim_token: str,
    now: str,
    stale_before: datetime,
) -> JsonObj:
    claimed = _enrolment_obj(
        db.row(
            f"""
            update automation_enrolments e
            set data = e.data || jsonb_build_object(
                'status', 'running',
                'running_status',
                    case
                        when e.data->>'status' = 'running' then e.data->>'running_status'
                        else e.data->>'status'
                    end,
                'claim_token', %s,
                'claimed_at', %s,
                'claimed_node_id', e.data->>'current_node_id',
                'claimed_published_revision', e.data->>'published_revision',
                'modified', %s
            )
            from contacts."contacts_{cid}" c
            where c.contact_id = e.contact_id
                and e.cid = %s
                and e.automation_id = %s
                and e.id = %s
                and (
                    e.data->>'status' in ('ready', 'waiting')
                    or (
                        e.data->>'status' = 'running'
                        and e.data->>'running_status' in ('ready', 'waiting')
                        and nullif(e.data->>'claimed_at', '')::timestamptz < %s
                    )
                )
            returning e.id, e.cid, e.automation_id, e.contact_id, e.contact_email, e.data
            """,
            claim_token,
            now,
            now,
            cid,
            automation_id,
            enrolment_id,
            stale_before,
        )
    )
    if claimed is not None:
        return claimed

    _raise_run_not_claimable(_read_run_enrolment(db, cid, automation_id, enrolment_id))


def _release_run_claim(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    claim_token: str,
    status: str,
    now: str,
    extra: JsonObj | None = None,
) -> None:
    patch = {
        "status": status,
        "modified": now,
    }
    patch.update(_claim_clear_patch())
    if extra:
        patch.update(extra)
    exit_rules.finish_claim(db, cid, automation_id, enrolment_id, claim_token, patch)



def _advance_claimed_enrolment(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    claim_token: str,
    update: JsonObj,
) -> None:
    update = update.copy()
    update.update(_claim_clear_patch())
    update.update(_retry_clear_patch())
    update["subject_gate"] = None
    updated = exit_rules.finish_claim(db, cid, automation_id, enrolment_id, claim_token, update)
    if updated != 1:
        raise falcon.HTTPConflict(
            title="Automation execution claim was lost",
            description="The enrolment claim changed before the execution result could be saved.",
        )


def _insert_step_run(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    contact_id: int,
    node_id: str,
    node_type: str,
    data: JsonObj,
) -> None:
    db.execute(
        """
        insert into automation_step_runs
            (id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        data["id"],
        cid,
        automation_id,
        enrolment_id,
        contact_id,
        node_id,
        node_type,
        data,
    )


def _patch_step_run(db: DB, cid: str, run_id: str, patch: JsonObj) -> None:
    db.execute(
        """
        update automation_step_runs
        set data = data || %s
        where cid = %s and id = %s
        """,
        patch,
        cid,
        run_id,
    )


class Automations(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "automations"
        self.useronly = True
        self.userlog = "automation"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        _validate_doc(doc, AUTOMATION_CREATE_SCHEMA)
        _prepare_doc(doc, True)

        return CRUDCollection.on_post(self, req, resp)


class Automation(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "automations"
        self.useronly = True
        self.userlog = "automation"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        automation = req.context["db"].automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        _validate_doc(doc, AUTOMATION_PATCH_SCHEMA)
        if "exit_rules" in doc:
            doc["exit_rules"] = _prepare_exit_rules(doc["exit_rules"])
        draft = doc.get("draft", automation.get("draft") or {})
        _validate_unique_node_ids(draft.get("nodes") or [])
        _prepare_patch_doc(doc)

        CRUDSingle.on_patch(self, req, resp, id)
        req.context["result"] = req.context["db"].automations.get(id)

    def del_check(self, db: DB, id: str) -> None:
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()

        if (
            automation.get("published_at")
            or automation.get("published")
            or int(automation.get("enrolled_count", 0) or 0) > 0
        ):
            raise falcon.HTTPBadRequest(
                title="Automation cannot be deleted",
                description="Only draft automations that have never been published or enrolled can be deleted.",
            )


class AutomationEmails(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)

        req.context["result"] = [
            _automation_email_obj(row)
            for row in db.execute(
                """
                select id, cid, automation_id, data
                from automation_emails
                where cid = %s and automation_id = %s
                order by lower(data->>'name'), id
                """,
                cid,
                id,
            )
        ]

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        doc = req.context.get("doc") or {}
        _validate_doc(doc, AUTOMATION_EMAIL_CREATE_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)

        data = _default_automation_email(doc)
        data = _prepare_automation_email_patch(data)
        data["created"] = data["modified"]
        email_id = shortuuid.uuid()
        db.execute(
            """
            insert into automation_emails
                (id, cid, automation_id, data)
            values (%s, %s, %s, %s)
            """,
            email_id,
            cid,
            id,
            data,
        )

        resp.status = falcon.HTTP_201
        req.context["result"] = _get_automation_email(db, cid, id, email_id)


class AutomationEmailCopySources(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)

        source_filter = req.get_param("source_filter") or "all"
        if source_filter not in (
            "this",
            "other",
            "all",
            "transactional_templates",
            "broadcasts",
            "funnel_messages",
        ):
            raise falcon.HTTPBadRequest(
                title="Invalid source filter",
                description="Source filter must be this, other, all, transactional_templates, broadcasts or funnel_messages.",
            )

        search = (req.get_param("q") or "").strip().lower()
        sources = []
        if source_filter in ("this", "other", "all"):
            params = [cid]
            conditions = ["ae.cid = %s"]
            if source_filter == "this":
                conditions.append("ae.automation_id = %s")
                params.append(id)
            elif source_filter == "other":
                conditions.append("ae.automation_id <> %s")
                params.append(id)
            if search:
                conditions.append(
                    """
                    (
                        lower(coalesce(ae.data->>'name', '')) like %s
                        or lower(coalesce(ae.data->>'subject', '')) like %s
                        or lower(coalesce(a.data->>'name', '')) like %s
                    )
                    """
                )
                term = "%%%s%%" % search
                params.extend([term, term, term])

            rows = db.execute(
                """
                select
                    ae.id,
                    ae.automation_id,
                    ae.data->>'name',
                    ae.data->>'subject',
                    coalesce(ae.data->>'type', 'raw'),
                    ae.data->>'modified',
                    a.data->>'name'
                from automation_emails ae
                join automations a on a.cid = ae.cid and a.id = ae.automation_id
                where %s
                order by
                    case when ae.automation_id = %%s then 0 else 1 end,
                    lower(coalesce(a.data->>'name', '')),
                    lower(coalesce(ae.data->>'name', '')),
                    ae.id
                limit 100
                """ % " and ".join(conditions),
                *(params + [id])
            )

            sources.extend(
                {
                    "source_type": "automation_email",
                    "source_id": row[0],
                    "source_automation_id": row[1],
                    "name": row[2] or "Untitled email",
                    "subject": row[3] or "",
                    "editor_type": row[4] or "raw",
                    "modified": row[5],
                    "source_automation_name": row[6] or row[1],
                    "source_label": row[6] or row[1],
                    "same_automation": row[1] == id,
                }
                for row in rows
            )

        if source_filter in ("transactional_templates", "all"):
            params = [cid]
            search_query = ""
            if search:
                search_query = """
                    and (
                        lower(coalesce(data->>'name', '')) like %s
                        or lower(coalesce(data->>'subject', '')) like %s
                    )
                """
                term = "%%%s%%" % search
                params.extend([term, term])
            rows = db.execute(
                """
                select
                    id,
                    data->>'name',
                    data->>'subject',
                    coalesce(data->>'type', 'raw'),
                    data->>'modified'
                from txntemplates
                where cid = %%s %s
                order by lower(coalesce(data->>'name', '')), id
                limit 100
                """ % search_query,
                *params
            )
            sources.extend(
                {
                    "source_type": "transactional_template",
                    "source_id": row[0],
                    "name": row[1] or "Untitled template",
                    "subject": row[2] or "",
                    "editor_type": row[3] or "raw",
                    "modified": row[4],
                    "source_label": "Transactional template",
                    "same_automation": False,
                }
                for row in rows
            )

        if source_filter in ("broadcasts", "all"):
            params = [cid]
            search_query = ""
            if search:
                search_query = """
                    and (
                        lower(coalesce(data->>'name', '')) like %s
                        or lower(coalesce(data->>'subject', '')) like %s
                    )
                """
                term = "%%%s%%" % search
                params.extend([term, term])
            rows = db.execute(
                """
                select
                    id,
                    data->>'name',
                    data->>'subject',
                    coalesce(data->>'type', 'raw'),
                    data->>'modified',
                    data->>'sent_at'
                from campaigns
                where cid = %%s
                    and data->>'hidden' is null
                    %s
                order by
                    case when data->>'sent_at' is null then 0 else 1 end,
                    coalesce(data->>'sent_at', data->>'modified') desc nulls last,
                    lower(coalesce(data->>'name', '')),
                    id
                limit 100
                """ % search_query,
                *params
            )
            sources.extend(
                {
                    "source_type": "broadcast",
                    "source_id": row[0],
                    "name": row[1] or "Untitled broadcast",
                    "subject": row[2] or "",
                    "editor_type": row[3] or "raw",
                    "modified": row[4],
                    "sent_at": row[5],
                    "status": "sent" if row[5] else "draft",
                    "source_label": "Broadcast",
                    "same_automation": False,
                }
                for row in rows
            )

        if source_filter in ("funnel_messages", "all"):
            params = [cid]
            search_query = ""
            if search:
                search_query = """
                    and (
                        lower(coalesce(m.data->>'subject', '')) like %s
                        or lower(coalesce(f.data->>'name', '')) like %s
                    )
                """
                term = "%%%s%%" % search
                params.extend([term, term])
            rows = db.execute(
                """
                select
                    m.id,
                    m.data->>'subject',
                    coalesce(m.data->>'type', 'raw'),
                    m.data->>'modified',
                    f.id,
                    f.data->>'name',
                    match_meta.meta->>'whennum',
                    match_meta.meta->>'whentype'
                from messages m
                join funnels f on f.cid = m.cid and f.id = m.data->>'funnel'
                join lateral jsonb_array_elements(coalesce(f.data->'messages', '[]'::jsonb)) match_meta(meta)
                    on match_meta.meta->>'id' = m.id
                where m.cid = %%s %s
                order by
                    lower(coalesce(f.data->>'name', '')),
                    nullif(match_meta.meta->>'whennum', '')::int nulls first,
                    lower(coalesce(m.data->>'subject', '')),
                    m.id
                limit 100
                """ % search_query,
                *params
            )
            sources.extend(
                {
                    "source_type": "funnel_message",
                    "source_id": row[0],
                    "name": "%s: %s" % (row[5] or row[4], row[1] or "Untitled message"),
                    "subject": row[1] or "",
                    "editor_type": row[2] or "raw",
                    "modified": row[3],
                    "source_funnel_id": row[4],
                    "source_funnel_name": row[5] or row[4],
                    "source_label": "Funnel: %s" % (row[5] or row[4]),
                    "sequence_label": (
                        "After %s %s" % (row[6], row[7])
                        if row[6] and row[7]
                        else "First message"
                    ),
                    "same_automation": False,
                }
                for row in rows
            )

        req.context["result"] = sources[:100]


class AutomationEmailFromSource(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        doc = req.context.get("doc") or {}
        _validate_doc(doc, AUTOMATION_EMAIL_FROM_SOURCE_SCHEMA)
        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)

        source_type = doc.get("source_type", "automation_email")
        if source_type == "automation_email":
            source = _automation_email_obj(
                db.row(
                    """
                    select id, cid, automation_id, data
                    from automation_emails
                    where cid = %s and id = %s
                    """,
                    cid,
                    doc["source_id"],
                )
            )
        elif source_type == "transactional_template":
            source = _transactional_template_obj(
                db.row(
                    """
                    select id, cid, data
                    from txntemplates
                    where cid = %s and id = %s
                    """,
                    cid,
                    doc["source_id"],
                )
            )
        elif source_type == "broadcast":
            source = _broadcast_source_obj(
                db.row(
                    """
                    select id, cid, data
                    from campaigns
                    where cid = %s and id = %s
                    """,
                    cid,
                    doc["source_id"],
                )
            )
        elif source_type == "funnel_message":
            source = _funnel_message_source_obj(
                db.row(
                    """
                    select m.id, m.cid, m.data, f.id, f.data
                    from messages m
                    join funnels f on f.cid = m.cid and f.id = m.data->>'funnel'
                    where m.cid = %s and m.id = %s
                    """,
                    cid,
                    doc["source_id"],
                )
            )
        else:
            raise falcon.HTTPBadRequest(
                title="Unsupported source type",
                description="Only automation email, transactional template, broadcast and funnel message sources are supported.",
            )
        if source is None:
            raise falcon.HTTPForbidden()

        data = _automation_email_copy_data(db, cid, id, source)
        email_id = shortuuid.uuid()
        db.execute(
            """
            insert into automation_emails
                (id, cid, automation_id, data)
            values (%s, %s, %s, %s)
            """,
            email_id,
            cid,
            id,
            data,
        )

        resp.status = falcon.HTTP_201
        req.context["result"] = _get_automation_email(db, cid, id, email_id)


class AutomationEmailLinks(object):

    def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        email_id: str,
    ) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)
        email = _automation_email_obj(
            db.row(
                """
                select id, cid, automation_id, data
                from automation_emails
                where cid = %s and automation_id = %s and id = %s
                """,
                cid,
                id,
                email_id,
            )
        )
        if email is None:
            raise falcon.HTTPNotFound()

        req.context["result"] = {
            "automation_id": id,
            "automation_email_id": email_id,
            "links": _automation_email_discovered_links(email),
        }


class AutomationEmail(object):

    def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        email_id: str,
    ) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)
        req.context["result"] = _get_automation_email(db, cid, id, email_id)

    @_automation_state_transition
    def on_patch(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        email_id: str,
    ) -> None:
        check_noadmin(req)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        _validate_doc(doc, AUTOMATION_EMAIL_PATCH_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)
        email = _get_automation_email(db, cid, id, email_id)
        if "type" in doc:
            existing_type = email["type"] if "type" in email else "raw"
            if doc["type"] != existing_type:
                raise falcon.HTTPBadRequest(
                    title="Automation email editor type is fixed",
                    description="Create a new automation email to use a different editor type.",
                )
        experiment = subject_tests.active(db, cid, id, email_id)
        shared_fields = {"rawText", "parts", "bodyStyle", "type", "preheader", "fromname", "fromemail", "replyto", "returnpath"}
        if experiment and experiment["status"] in ("collecting", "observing") and any(
            field in doc and doc[field] != email.get(field) for field in shared_fields
        ):
            subject_tests.error("Choose a winner before changing the shared email content or sender. Subject variants are immutable; add a challenger instead.")
        patch = _prepare_automation_email_patch(doc)

        db.execute(
            """
            update automation_emails
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            patch,
            cid,
            id,
            email_id,
        )
        req.context["result"] = _get_automation_email(db, cid, id, email_id)

    def on_delete(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        email_id: str,
    ) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        automation = _automation_for_email_route(db, id)
        _get_automation_email(db, cid, id, email_id)

        reference = _automation_references_email(automation, email_id)
        if reference is not None:
            raise falcon.HTTPBadRequest(
                title="Automation email is in use",
                description=(
                    "This email is referenced by %s step %s%s."
                    % (
                        reference["workflow"],
                        reference["step"],
                        (
                            " (%s)" % reference["node_label"]
                            if reference.get("node_label")
                            else ""
                        ),
                    )
                ),
            )

        db.execute(
            """
            delete from automation_emails
            where cid = %s and automation_id = %s and id = %s
            """,
            cid,
            id,
            email_id,
        )
        req.context["result"] = {}


class AutomationEmailDuplicate(object):

    def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        email_id: str,
    ) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        _automation_for_email_route(db, id)
        email = _get_automation_email(db, cid, id, email_id)

        data = copy.deepcopy(email)
        for key in ("id", "cid", "automation_id"):
            data.pop(key, None)
        data["created"] = _utc_now()
        data["modified"] = data["created"]

        orig, i = get_orig(data.get("name") or "Automation email")
        while True:
            data["name"] = "%s (%s)" % (orig, i)
            existing = db.single(
                """
                select id
                from automation_emails
                where cid = %s and automation_id = %s and data->>'name' = %s
                limit 1
                """,
                cid,
                id,
                data["name"],
            )
            if existing is None:
                break
            i += 1

        new_email_id = shortuuid.uuid()
        db.execute(
            """
            insert into automation_emails
                (id, cid, automation_id, data)
            values (%s, %s, %s, %s)
            """,
            new_email_id,
            cid,
            id,
            data,
        )
        req.context["result"] = _get_automation_email(db, cid, id, new_email_id)


class AutomationPreflight(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()
        mode = req.get_param("mode") or "draft"
        req.context["result"] = _automation_send_email_preflight(db, cid, automation, mode)


class AutomationEmailTest(object):

    def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        email_id: str,
    ) -> None:
        check_noadmin(req, True)

        db = req.context["db"]
        cid = db.get_cid()

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON",
                description="A valid JSON document is required.",
            )
        _validate_doc(doc, AUTOMATION_EMAIL_TEST_SCHEMA)

        _automation_for_email_route(db, id)
        automation_email = _get_automation_email(db, cid, id, email_id)

        db.set_cid(None)

        db.users.patch(
            req.context["uid"],
            {"lasttest": {"to": doc["to"], "route": doc.get("route", "")}},
        )

        company = db.companies.get(cid)
        user = db.users.get(req.context["uid"])
        if company is None or user is None:
            raise falcon.HTTPForbidden()

        check_test_limit(db, company, doc["to"].strip().lower())

        availroutes = company.get("routes") or []
        route_id = doc.get("route", "")
        if route_id:
            if route_id not in availroutes:
                raise falcon.HTTPForbidden()
        elif len(availroutes) == 1:
            route_id = availroutes[0]
        else:
            raise falcon.HTTPBadRequest(
                title="Missing parameter",
                description="No route specified and multiple are available.",
            )

        route = db.routes.get(route_id)
        if route is None or "published" not in route:
            raise falcon.HTTPForbidden()

        imagebucket = os.environ["s3_imagebucket"]
        parentcompany = db.companies.get(company["cid"])
        if parentcompany is not None:
            imagebucket = parentcompany.get("s3_imagebucket", imagebucket)

        html, _ = generate_html(db, automation_email, "test", imagebucket)

        _, addr = email.utils.parseaddr(doc["to"])
        if not addr:
            addr = remove_newlines(doc["to"])

        fromemail = remove_newlines(user.get("username", ""))
        fromname = remove_newlines(user.get("fullname", "") or company.get("name", ""))
        fromdomain = ""
        if "@" in fromemail:
            fromdomain = fromemail.split("@")[-1].strip().lower()

        frm = email.utils.formataddr((fromname, fromemail)) if fromname else fromemail
        subject = remove_newlines(automation_email["subject"])

        try:
            send_backend_mail(
                db,
                cid,
                route,
                html,
                frm,
                fromemail,
                fromdomain,
                fromemail,
                remove_newlines(doc["to"]),
                addr,
                subject,
            )
        except Exception as e:
            traceback.print_exc()
            if doc.get("include_in_log", False):
                try:
                    add_test_txn_log(
                        db,
                        cid,
                        remove_newlines(doc["to"]),
                        subject,
                        "automation:%s" % id,
                        fromname,
                        fromemail,
                        None,
                        route_id,
                        None,
                        event="Error",
                        status="Error",
                        error=str(e),
                    )
                except Exception:
                    log.exception("error logging automation email test send failure")
            raise falcon.HTTPBadRequest(
                title="Error sending test",
                description="Error sending test: %s" % e,
            )

        if doc.get("include_in_log", False):
            try:
                add_test_txn_log(
                    db,
                    cid,
                    remove_newlines(doc["to"]),
                    subject,
                    "automation:%s" % id,
                    fromname,
                    fromemail,
                    None,
                    route_id,
                    None,
                    status="Sent",
                )
            except Exception:
                log.exception("error logging automation email test send")

        req.context["result"] = {}


def _publish_enrolment_counts(db: DB, cid: str, automation_id: str) -> List[JsonObj]:
    # One statement gives preview consistent counts even as an already-claimed
    # action finishes. Keep JSON types for strict preview classification.
    return [
        {"node_id": node_id, "node_id_type": node_id_type, "status": status,
         "status_type": status_type, "count": count, "claimed_count": claimed}
        for node_id, node_id_type, status, status_type, count, claimed in db.execute(
            """
            select data->>'current_node_id', jsonb_typeof(data->'current_node_id'),
                data->>'status', jsonb_typeof(data->'status'), count(*),
                count(*) filter (where data->>'status' = 'running'
                    or nullif(data->>'claim_token', '') is not null)
            from automation_enrolments
            where cid = %s and automation_id = %s
            group by 1, 2, 3, 4
            """,
            cid, automation_id,
        )
    ]


def _reject_publish_claims(groups: List[JsonObj]) -> None:
    claimed = sum(group["claimed_count"] for group in groups)
    if claimed:
        raise falcon.HTTPConflict(
            title="Automation publication is blocked by execution",
            description=(
                "%s enrolment(s) still have an execution claim. Wait for execution to finish and retry. "
                "For stale claims, verify the worker has stopped before using the existing recovery action."
            ) % claimed,
        )


def _validate_publish_enrolments(db: DB, cid: str, automation_id: str, published: JsonObj) -> None:
    # The automation row lock excludes new claims, enrolments and reactivation.
    # Actions run without this lock, retaining their claim until advancement.
    groups = _publish_enrolment_counts(db, cid, automation_id)
    _reject_publish_claims(groups)
    node_types = {node["id"]: node["type"] for node in published["nodes"]}
    old_nodes = {node["id"]: node for node in (db.automations.get(automation_id).get("published") or {}).get("nodes", [])}
    new_nodes = {node["id"]: node for node in published["nodes"]}
    missing = set()
    incompatible_waits = set()
    for group in groups:
        node_id, status = group["node_id"], group["status"]
        if status in TERMINAL_ENROLMENT_STATUSES:
            continue
        if node_id not in node_types:
            missing.add(node_id)
        elif status in ("waiting", "paused_waiting") and not _compatible_wait(old_nodes.get(node_id, {}), new_nodes[node_id]):
            incompatible_waits.add(node_id)
    if missing or incompatible_waits:
        details = []
        if missing:
            details.append("Nonterminal enrolments need retained node IDs: %s." % ", ".join(
                json.dumps(node_id) for node_id in sorted(missing, key=lambda value: value or "")
            ))
        if incompatible_waits:
            details.append("Waiting enrolments require these nodes to remain Wait steps using the same duration or date/time mode: %s." % ", ".join(
                json.dumps(node_id) for node_id in sorted(incompatible_waits)
            ))
        raise falcon.HTTPConflict(
            title="Automation publication would strand enrolments",
            description=_bounded_error_text(" ".join(details)) + (
                " Restore these draft nodes or allow the affected enrolments to finish before publishing. "
                "No contacts were moved."
            ),
        )


def _publish_review(automation: JsonObj) -> JsonObj:
    return {
        "draft_fingerprint": _automation_fingerprint(_automation_publish_inputs(automation)),
        "published_fingerprint": _automation_fingerprint(automation.get("published")),
        "published_revision": automation.get("published_revision") or 0,
    }


MOVABLE_NODE_TYPES = {"add_tag", "remove_tag", "add_to_list", "remove_from_list", "send_email", "wait_duration"}


def _move_placement(nodes: List[JsonObj], node_id: str) -> JsonObj:
    index = next(i for i, node in enumerate(nodes) if node["id"] == node_id)
    return {
        "previous": nodes[index - 1]["id"] if index else None,
        "next": nodes[index + 1]["id"] if index + 1 < len(nodes) else None,
        "incoming": sorted([
            {"id": node["id"], "field": field} for node in nodes
            for field in ("yes_node_id", "no_node_id", "target_node_id") if node.get(field) == node_id
        ], key=lambda item: (item["id"], item["field"])),
    }


def _assess_move_decisions(automation: JsonObj, proposed: JsonObj, groups: List[JsonObj]) -> tuple:
    """Draft-only instructions bound to the live revision and exact placement."""
    decisions = (automation.get("draft") or {}).get("moves") or {}
    old = {node["id"]: node for node in (automation.get("published") or {}).get("nodes", [])}
    nodes = proposed["nodes"]
    current = {node["id"]: node for node in nodes}
    moves, blockers = [], []
    for node_id, decision in sorted(decisions.items()):
        if (node_id not in old or node_id not in current or current[node_id]["type"] not in MOVABLE_NODE_TYPES
                or old[node_id]["type"] != current[node_id]["type"]
                or decision["published_revision"] != (automation.get("published_revision") or 0)
                or decision["placement"] != _move_placement(nodes, node_id)):
            blockers.append({"code": "stale_move_decision", "node_id": node_id,
                "title": "Moved-step contact decision needs review",
                "description": "Review the move decision for step %s in the visual editor before publishing. Its placement or published workflow changed. Nothing was moved." % json.dumps(node_id)})
            continue
        states = {group["status"]: group["count"] for group in groups
                  if group["node_id"] == node_id and group["status"] in ACTIVE_ENROLMENT_STATUSES}
        moves.append({"node_id": node_id, "label": old[node_id]["label"], "action": decision["action"],
                      "enrolment_count": sum(states.values()), "states": states})
    return moves, blockers


def _publish_impact(db: DB, cid: str, automation: JsonObj, proposed: JsonObj | None = None, rule_cohort=None) -> JsonObj:
    """Read-only assessment; callers hold the automation coordination lock."""
    blockers: List[JsonObj] = []
    result = {
        "review": _publish_review(automation),
        "automation_status": automation.get("status"),
        "sources": [],
        "destinations": [],
        "blockers": blockers,
    }

    if proposed is None:
        try:
            proposed = _published_snapshot(db, automation)
        except falcon.HTTPBadRequest as error:
            blockers.append({
                "code": "invalid_proposed_workflow", "title": error.title,
                "description": _bounded_error_text(error.description or error.title),
            })
    if proposed is not None:
        result["destinations"] = [
            {"node_id": node["id"], "label": node["label"], "type": node["type"]}
            for node in proposed["nodes"]
        ]

    try:
        rule_cohort = rule_cohort if rule_cohort is not None else exit_rules.cohort(db, cid, automation, proposed) if proposed else []
    except falcon.HTTPBadRequest as error:
        rule_cohort = []
        blockers.append({"code": "invalid_exit_rules", "title": error.title, "description": error.description})
    exit_states = {}
    exit_positions = {}
    for _, previous, _ in rule_cohort:
        status = previous.get("status")
        exit_states[status] = exit_states.get(status, 0) + 1
        key = (previous.get("current_node_id"), status)
        exit_positions[key] = exit_positions.get(key, 0) + 1
    result["rule_exits"] = {"enrolment_count": len(rule_cohort), "states": exit_states}
    result["exit_review_required"] = bool(rule_cohort or (proposed is not None and
        proposed.get("exit_rules", []) != (automation.get("published") or {}).get("exit_rules", [])))

    published = automation.get("published")
    old_nodes = []
    old_valid = True
    revision = result["review"]["published_revision"]
    try:
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError()
        if published is not None:
            if not isinstance(published, dict):
                raise ValueError()
            _validate_doc({"nodes": published.get("nodes")}, DRAFT_SCHEMA)
            _validate_unique_node_ids(published["nodes"])
            old_nodes = published["nodes"]
            if not old_nodes or revision == 0:
                raise ValueError()
        elif revision != 0:
            raise ValueError()
    except (falcon.HTTPBadRequest, ValueError):
        old_valid = False
        old_nodes = []
        blockers.append({
            "code": "unsupported_published_workflow",
            "title": "Published workflow is malformed",
            "description": "The stored published workflow or revision cannot be assessed safely. Recovery is not supported by this endpoint.",
        })

    old_by_id = {node["id"]: node for node in old_nodes}
    new_by_id = {node["id"]: node for node in proposed["nodes"]} if proposed is not None else {}
    sources: Dict[str, JsonObj] = {}
    groups = _publish_enrolment_counts(db, cid, automation["id"])
    if old_valid and proposed is not None and (automation.get("draft") or {}).get("moves"):
        result["moves"], move_blockers = _assess_move_decisions(automation, proposed, groups)
        blockers.extend(move_blockers)
    claimed = sum(group["claimed_count"] for group in groups)
    if claimed:
        blockers.append({
            "code": "execution_claims", "title": "Execution claims remain",
            "description": "Publication is blocked until execution claims are released, including stale claims. Preview does not release claims.",
            "enrolment_count": claimed,
        })
    for group in sorted(groups, key=lambda item: (item["node_id"] or "", item["status"] or "", item["node_id_type"] or "", item["status_type"] or "")):
        node_id, status, count = group["node_id"], group["status"], group["count"]
        if group["status_type"] == "string" and status in TERMINAL_ENROLMENT_STATUSES:
            continue
        valid_id = group["node_id_type"] == "string" and re.fullmatch(NODE_ID_SCHEMA["pattern"], node_id or "") is not None
        detail = {"node_id": node_id if valid_id else None, "enrolment_count": count}
        if group["status_type"] != "string" or status not in ACTIVE_ENROLMENT_STATUSES:
            blockers.append({
                "code": "unsupported_enrolment_state", "title": "Enrolment state is malformed",
                "description": "This nonterminal state requires separate review; preview cannot repair it.", **detail,
            })
            state_key = "unsupported"
        else:
            state_key = status
        if not valid_id:
            blockers.append({
                "code": "invalid_current_position", "title": "Enrolment position is invalid",
                "description": "A current node ID is missing or is not a valid string node ID. Recovery is not supported by this endpoint.", **detail,
            })
        elif old_valid and node_id not in old_by_id:
            blockers.append({
                "code": "already_stranded", "title": "Enrolments are already stranded",
                "description": "This position is absent from the current published workflow; it is not a deletion introduced by the draft.", **detail,
            })
        elif old_valid and proposed is not None and node_id not in new_by_id:
            count -= exit_positions.get((node_id, status), 0)
            if count <= 0:
                continue
            source = sources.setdefault(node_id, {
                "node_id": node_id, "label": old_by_id[node_id]["label"],
                "type": old_by_id[node_id]["type"], "enrolment_count": 0, "states": {},
            })
            source["enrolment_count"] += count
            source["states"][state_key] = source["states"].get(state_key, 0) + count
        elif proposed is not None and node_id in new_by_id and status in ("waiting", "paused_waiting") and not _compatible_wait(old_by_id.get(node_id, {}), new_by_id[node_id]):
            blockers.append({
                "code": "incompatible_retained_wait", "title": "Retained wait is incompatible",
                "description": "A retained node with waiting enrolments must remain a Wait step using the same duration or date/time mode.", **detail,
            })
    result["sources"] = [sources[node["id"]] for node in old_nodes if node["id"] in sources]
    return result


class AutomationPublishImpact(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)
        db = req.context["db"]
        cid = db.get_cid()
        with _locked_automation(db, cid, id) as automation:
            req.context["result"] = _publish_impact(db, cid, automation)


def _validate_publish_resolutions(automation: JsonObj, proposed: JsonObj, impact: JsonObj, resolutions: JsonObj) -> None:
    destinations = {node["id"] for node in proposed["nodes"]}
    deleted = {node["id"] for node in (automation.get("published") or {}).get("nodes", [])} - destinations
    for source_id, choice in resolutions.items():
        if source_id not in deleted:
            raise falcon.HTTPBadRequest(
                title="Invalid automation migration resolution",
                description="Source %s is not a deletion from the reviewed published workflow." % json.dumps(source_id),
            )
        if choice["action"] == "move" and choice["destination_node_id"] not in destinations:
            raise falcon.HTTPBadRequest(
                title="Invalid automation migration resolution",
                description="Destination %s does not exist in the proposed workflow." % json.dumps(choice["destination_node_id"]),
            )
    missing = {source["node_id"] for source in impact["sources"]} - set(resolutions)
    if missing:
        raise falcon.HTTPConflict(
            title="Automation migration resolutions required",
            description="Review the current impact and choose a resolution for: %s. Nothing was published or moved." % ", ".join(json.dumps(value) for value in sorted(missing)),
        )


def _record_publish_migration(db: DB, cid: str, automation_id: str, enrolment_id: str, event: JsonObj) -> None:
    db.execute(
        """
        update automation_enrolments
        set data = data || jsonb_build_object('migration_events',
            coalesce(nullif(data->'migration_events', 'null'::jsonb), '[]'::jsonb) || jsonb_build_array(%s::jsonb))
        where cid = %s and automation_id = %s and id = %s
        """,
        event, cid, automation_id, enrolment_id,
    )


def _migrate_publish_enrolments(db: DB, cid: str, automation: JsonObj, request: JsonObj,
                               revision: int, now: str, uid: str) -> List[JsonObj]:
    outcomes = []
    paused = automation.get("status") == "paused"
    choices = dict(request["resolutions"])
    for node_id, decision in ((automation.get("draft") or {}).get("moves") or {}).items():
        choices[node_id] = {"action": decision["action"], "reason": "node_relocated"}
    for source_id, choice in sorted(choices.items()):
        rows = db.execute(
            """
            select id, data from automation_enrolments
            where cid = %s and automation_id = %s
                and data->'current_node_id' = to_jsonb(%s::text)
                and data->>'status' = any(%s)
            order by id for update
            """,
            cid, automation["id"], source_id,
            [status for status in ACTIVE_ENROLMENT_STATUSES if status != "running"],
        ).fetchall()
        for enrolment_id, previous in rows:
            events = previous.get("migration_events")
            if events is not None and (not isinstance(events, list) or any(not isinstance(event, dict) for event in events)):
                raise falcon.HTTPConflict(
                    title="Enrolment migration history is malformed",
                    description="Publication cannot safely append migration history. No changes were committed.",
                )
            if choice["action"] == "follow":
                # Stable ID follows the relocated step. Preserve every timer,
                # retry, pause and held-state field; do not execute the step.
                status = previous["status"]
            else:
                moving = choice["action"] == "move"
                status = ("paused_ready" if paused else "ready") if moving else "exited"
                update = {
                    **_claim_clear_patch(), **_retry_clear_patch(),
                    "current_node_id": choice["destination_node_id"] if moving else source_id,
                    "status": status, "modified": now, "wake_at": None, "wait": None,
                    "paused_at": now if moving and paused else None, "resumed_at": None,
                    "subject_gate": None,
                    "transitions_without_wait": 0,
                    "visited_node_ids": [],
                    "cross_automation_visits": [],
                }
                db.execute(
                    "update automation_enrolments set data = data || %s where cid = %s and automation_id = %s and id = %s",
                    update, cid, automation["id"], enrolment_id,
                )
            _record_publish_migration(db, cid, automation["id"], enrolment_id, {
                "request_id": request["request_id"], "created": now,
                "source_node_id": source_id, **choice,
                "previous_status": previous["status"], "resulting_status": status,
                "previous_published_revision": automation.get("published_revision") or 0,
                "published_revision": revision, "user_id": uid,
            })
        outcomes.append({"source_node_id": source_id, **choice, "enrolment_count": len(rows)})
    return outcomes


class AutomationPublish(object):

    @_automation_state_transition
    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)
        db = req.context["db"]
        cid = db.get_cid()
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()

        request = req.context.get("doc")
        if request is not None:
            _validate_doc(request, AUTOMATION_PUBLISH_SCHEMA)
            fingerprint = _automation_fingerprint(request)
            receipt = automation.get("publication_receipt") or {}
            if receipt.get("request_id") == request["request_id"]:
                if receipt.get("request_fingerprint") != fingerprint:
                    raise falcon.HTTPConflict(
                        title="Publication request ID was already used",
                        description="This operation ID was committed with different content. Reload the automation before reviewing another publication.",
                    )
                if receipt.get("published_revision") == automation.get("published_revision"):
                    req.context["result"] = automation
                    return
            if request["review"] != _publish_review(automation):
                raise falcon.HTTPConflict(
                    title="Automation publish review is stale",
                    description="The saved draft or published workflow changed. Reload publish impact and review the resolutions again.",
                )

        # The automation row is already locked: no new execution can claim it.
        # Refuse before waiting for the account membership lock, which an
        # in-flight tag/list action may hold. Receipt replay above is read-only.
        _reject_publish_claims(_publish_enrolment_counts(db, cid, id))
        contacts.lock_exit_rule_changes(db, cid, publishing=True)
        published = _published_snapshot(db, automation)
        rule_cohort = exit_rules.cohort(db, cid, automation, published)
        impact = _publish_impact(db, cid, automation, published, rule_cohort)
        if impact["exit_review_required"] and (request is None or not request.get("accept_exit_rules")):
            raise falcon.HTTPConflict(title="Exit-rule publication requires review",
                description="Review the current exit-rule impact and confirm that matching enrolments will exit. Nothing was published.")
        if request is None:
            if (automation.get("draft") or {}).get("moves"):
                raise falcon.HTTPConflict(title="Moved-step publication requires review",
                    description="Reload publish impact and publish using its review binding. No contacts were moved.")
            # Preserve the existing bodyless caller and its occupied-node refusal.
            _validate_publish_enrolments(db, cid, id, published)
        if impact["blockers"]:
            blocker = impact["blockers"][0]
            raise falcon.HTTPConflict(title=blocker["title"], description=blocker["description"])
        if request is not None:
            _validate_publish_resolutions(automation, published, impact, request["resolutions"])

        now = _utc_now()
        revision = int(automation.get("published_revision", 0) or 0) + 1
        receipt = None
        for eid, previous, match in rule_cohort:
            metadata = previous.get("pending_rule_exit") or exit_rules.reason(
                {**automation, "published_revision": revision}, previous, match, "publication",
                previous_published_revision=automation.get("published_revision") or 0,
                user_id=req.context["uid"], request_id=request["request_id"])
            db.execute("update automation_enrolments set data=data||%s where cid=%s and automation_id=%s and id=%s",
                exit_rules.exit_patch(previous, metadata), cid, id, eid)
        if request is not None:
            outcomes = _migrate_publish_enrolments(db, cid, automation, request, revision, now, req.context["uid"])
            receipt = {
                "request_id": request["request_id"], "request_fingerprint": fingerprint,
                "previous_published_revision": revision - 1, "published_revision": revision,
                "created": now, "user_id": req.context["uid"], "outcomes": outcomes,
                "rule_exit_count": len(rule_cohort),
            }
        doc = {
            "status": "paused" if automation.get("status") == "paused" else "published",
            "published": published, "published_at": now, "published_by": req.context["uid"],
            "published_revision": revision, "modified": now,
            # A later bodyless publication also supersedes the latest receipt.
            "publication_receipt": receipt,
        }
        if (automation.get("draft") or {}).get("moves"):
            doc["draft"] = {key: value for key, value in automation["draft"].items() if key != "moves"}
        db.automations.patch(id, doc)
        audit = "."
        if receipt is not None:
            audit += " Migration: " + json.dumps({key: value for key, value in receipt.items() if key != "request_fingerprint"}, sort_keys=True)
        user_log(req, "pencil", "published automation ", "automations", id, audit)
        req.context["result"] = db.automations.get(id)


class AutomationPause(object):

    @_automation_state_transition
    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()
        if not automation.get("published"):
            raise falcon.HTTPBadRequest(
                title="Automation is not published",
                description="Publish the automation before pausing it.",
            )
        if automation.get("status") == "paused":
            req.context["result"] = automation
            return

        now_dt = datetime.utcnow()
        now = _iso_datetime(now_dt)

        rows = [
            _enrolment_obj(row)
            for row in db.execute(
                """
                select id, cid, automation_id, contact_id, contact_email, data
                from automation_enrolments
                where cid = %s and automation_id = %s
                """,
                cid,
                id,
            )
        ]
        for enrolment in rows:
            status = enrolment.get("status")
            update = None
            if status == "ready":
                update = {
                    "status": "paused_ready",
                    "paused_at": now,
                    "modified": now,
                }
            elif status == "waiting":
                wait = copy.deepcopy(enrolment.get("wait") or {})
                remaining = _remaining_seconds(enrolment.get("wake_at"), now_dt)
                wait.update(
                    {
                        "paused_at": now,
                        "remaining_seconds": remaining,
                        "frozen_wake_at": enrolment.get("wake_at"),
                    }
                )
                update = {
                    "status": "paused_waiting",
                    "wake_at": None,
                    "wait": wait,
                    "paused_at": now,
                    "modified": now,
                }

            if update is not None:
                db.execute(
                    """
                    update automation_enrolments
                    set data = data || %s
                    where cid = %s and automation_id = %s and id = %s
                    """,
                    update,
                    cid,
                    id,
                    enrolment["id"],
                )

        db.automations.patch(
            id,
            {
                "status": "paused",
                "paused_at": now,
                "modified": now,
            },
        )
        user_log(req, "pause", "paused automation ", "automations", id, ".")
        req.context["result"] = db.automations.get(id)


class AutomationResume(object):

    @_automation_state_transition
    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()
        if not automation.get("published"):
            raise falcon.HTTPBadRequest(
                title="Automation is not published",
                description="Publish the automation before resuming it.",
            )
        if automation.get("status") != "paused":
            req.context["result"] = automation
            return

        now_dt = datetime.utcnow()
        now = _iso_datetime(now_dt)

        rows = [
            _enrolment_obj(row)
            for row in db.execute(
                """
                select id, cid, automation_id, contact_id, contact_email, data
                from automation_enrolments
                where cid = %s and automation_id = %s
                """,
                cid,
                id,
            )
        ]
        for enrolment in rows:
            if exit_rules.apply(db, cid, automation, enrolment["id"], "resume"):
                continue
            status = enrolment.get("status")
            update = None
            if status in ("held", "paused_ready"):
                update = {
                    "status": "ready",
                    "resumed_at": now,
                    "modified": now,
                }
            elif status == "paused_waiting":
                wait = copy.deepcopy(enrolment.get("wait") or {})
                remaining = int(wait.get("remaining_seconds", 0) or 0)
                wake_at = wait.get("wait_until") or _iso_datetime(now_dt + timedelta(seconds=remaining))
                wait.update(
                    {
                        "wake_at": wake_at,
                        "resumed_at": now,
                        "last_remaining_seconds": remaining,
                    }
                )
                update = {
                    "status": "waiting",
                    "wake_at": wake_at,
                    "wait": wait,
                    "resumed_at": now,
                    "modified": now,
                }

            if update is not None:
                db.execute(
                    """
                    update automation_enrolments
                    set data = data || %s
                    where cid = %s and automation_id = %s and id = %s
                    """,
                    update,
                    cid,
                    id,
                    enrolment["id"],
                )

        db.automations.patch(
            id,
            {
                "status": "published",
                "resumed_at": now,
                "modified": now,
            },
        )
        user_log(req, "play", "resumed automation ", "automations", id, ".")
        req.context["result"] = db.automations.get(id)


class AutomationEnrolments(object):

    def _node_position_summary(self, db: DB, cid: str, automation_id: str) -> tuple[JsonObj, JsonObj, JsonObj]:
        automation = db.automations.get(automation_id) or {}
        published_nodes = (automation.get("published") or {}).get("nodes") or []
        published_positions = {
            node.get("id"): index + 1
            for index, node in enumerate(published_nodes)
            if node.get("id")
        }
        active_rows = db.execute(
            f"""
            select e.id, e.data->>'current_node_id'
            from automation_enrolments e
            join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
            where e.cid = %s
              and e.automation_id = %s
              and e.data->>'status' = any(%s)
              and coalesce(e.data->>'current_node_id', '') <> ''
            """,
            cid,
            automation_id,
            list(ACTIVE_ENROLMENT_STATUSES),
        ).fetchall()
        node_counts: JsonObj = {}
        position_counts: JsonObj = {}
        node_ids_by_position: JsonObj = {}
        if not active_rows:
            return node_counts, position_counts, node_ids_by_position

        enrolment_ids = [row[0] for row in active_rows]
        step_rows = db.execute(
            """
            select enrolment_id, node_id
            from automation_step_runs
            where cid = %s and automation_id = %s and enrolment_id = any(%s)
            order by data->>'created', id
            """,
            cid,
            automation_id,
            enrolment_ids,
        ).fetchall()
        step_order_by_enrolment: dict[str, list[str]] = {}
        for enrolment_id, node_id in step_rows:
            if not node_id:
                continue
            order = step_order_by_enrolment.setdefault(enrolment_id, [])
            if node_id not in order:
                order.append(node_id)

        for enrolment_id, current_node_id in active_rows:
            node_counts[current_node_id] = node_counts.get(current_node_id, 0) + 1
            position = published_positions.get(current_node_id)
            if position is None:
                order = step_order_by_enrolment.get(enrolment_id, [])
                if current_node_id in order:
                    position = order.index(current_node_id) + 1
            if position is not None:
                key = str(position)
                position_counts[key] = position_counts.get(key, 0) + 1
                ids = node_ids_by_position.setdefault(key, [])
                if current_node_id not in ids:
                    ids.append(current_node_id)
        return node_counts, position_counts, node_ids_by_position

    def _summary(self, db: DB, cid: str, automation_id: str) -> JsonObj:
        node_counts, position_counts, node_ids_by_position = self._node_position_summary(db, cid, automation_id)
        active = db.single(
            f"""
            select count(distinct coalesce(e.contact_id::text, e.contact_email))
            from automation_enrolments e
            join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
            where e.cid = %s
              and e.automation_id = %s
              and e.data->>'status' = any(%s)
            """,
            cid,
            automation_id,
            list(ACTIVE_ENROLMENT_STATUSES),
        )
        enrolled = db.single(
            f"""
            select count(distinct coalesce(e.contact_id::text, e.contact_email))
            from automation_enrolments e
            join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
            where e.cid = %s and e.automation_id = %s
            """,
            cid,
            automation_id,
        )
        return {
            "active": active or 0,
            "enrolled": enrolled or 0,
            "nodes": node_counts,
            "node_positions": position_counts,
            "node_ids_by_position": node_ids_by_position,
        }

    def _paged(self, req: falcon.Request, db: DB, cid: str, automation_id: str) -> JsonObj:
        page = req.get_param_as_int("page") or 1
        page = max(1, page)
        page_size = req.get_param_as_int("page_size") or 50
        page_size = max(1, min(page_size, 100))
        view = req.get_param("view") or "all"
        if view not in ("active", "all"):
            raise falcon.HTTPBadRequest(
                title="Invalid enrolment view",
                description="Enrolment view must be active or all.",
            )
        search = (req.get_param("search") or "").strip().lower()
        params = [cid, automation_id]
        filters = ["e.cid = %s", "e.automation_id = %s"]
        if view == "active":
            filters.append("e.data->>'status' = any(%s)")
            params.append(list(ACTIVE_ENROLMENT_STATUSES))
        if search:
            filters.append("lower(e.contact_email) like %s")
            params.append("%%%s%%" % search)
        node_id = (req.get_param("node_id") or "").strip()
        if node_id:
            filters.append("e.data->>'current_node_id' = %s")
            params.append(node_id)
        node_position = req.get_param_as_int("node_position")
        if node_position is not None:
            _, _, node_ids_by_position = self._node_position_summary(db, cid, automation_id)
            node_ids = node_ids_by_position.get(str(node_position), [])
            if not node_ids:
                node_ids = ["__no_matching_automation_node__"]
            filters.append("e.data->>'current_node_id' = any(%s)")
            params.append(node_ids)
        where = " and ".join(filters)
        count = db.single(
            f"""
            select count(*) from (
                select distinct coalesce(e.contact_id::text, e.contact_email)
                from automation_enrolments e
                join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
                where {where}
            ) contacts
            """,
            *params,
        )
        rows = db.execute(
            f"""
            with picked as (
                select distinct on (coalesce(e.contact_id::text, e.contact_email))
                    e.id,
                    e.cid,
                    e.automation_id,
                    e.contact_id,
                    e.contact_email,
                    e.data
                from automation_enrolments e
                join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
                where {where}
                order by
                    coalesce(e.contact_id::text, e.contact_email),
                    case when e.data->>'status' = 'ready' then 0 else 1 end,
                    e.data->>'created' desc,
                    e.id desc
            )
            select id, cid, automation_id, contact_id, contact_email, data
            from picked
            order by data->>'created' desc, id desc
            limit %s offset %s
            """,
            *(params + [page_size, (page - 1) * page_size]),
        )
        total = count or 0
        enrolments = [_enrolment_obj(row) for row in rows]
        return {
            "summary": self._summary(db, cid, automation_id),
            "enrolments": enrolments,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "view": view,
            "search": search,
            "node_id": node_id,
            "node_position": node_position,
        }

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        if db.automations.get(id) is None:
            raise falcon.HTTPForbidden()

        if req.get_param("summary") or req.get_param("page") or req.get_param("view") or req.get_param("search"):
            if req.get_param_as_bool("summary") and not (req.get_param("page") or req.get_param("view") or req.get_param("search")):
                req.context["result"] = {
                    "summary": self._summary(db, cid, id),
                }
                return
            req.context["result"] = self._paged(req, db, cid, id)
            return

        req.context["result"] = [
            _enrolment_obj(row)
            for row in db.execute(
                f"""
                select e.id, e.cid, e.automation_id, e.contact_id, e.contact_email, e.data
                from automation_enrolments e
                join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
                where e.cid = %s and e.automation_id = %s
                order by e.data->>'created', e.id
                """,
                cid,
                id,
            )
        ]

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        _validate_doc(doc, AUTOMATION_ENROLMENT_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()

        _published_enrolment_context(automation)

        email = doc["email"].strip().lower()
        match = emailre.search(email)
        if not match:
            raise falcon.HTTPBadRequest(
                title="Invalid email", description="That email address is invalid"
            )
        email = match.group(0)

        contact = db.row(
            f"""select contact_id, email from contacts."contacts_{cid}" where email = %s""",
            email,
        )
        if contact is None:
            raise falcon.HTTPNotFound(
                title="Contact not found",
                description="Contact must exist before it can be enrolled.",
            )
        contact_id, contact_email = contact

        outcome = _create_enrolment_for_contact(
            db,
            cid,
            id,
            automation,
            contact_id,
            contact_email,
            "manual",
        )
        if outcome.get("status") == "skipped" and outcome.get("reason") == "once":
            raise falcon.HTTPBadRequest(
                title=outcome["title"],
                description=outcome["description"],
            )
        if outcome.get("status") == "skipped" and outcome.get("reason") in ("active_pass", "exit_rule"):
            raise falcon.HTTPBadRequest(
                title=outcome["title"],
                description=outcome["description"],
            )

        resp.status = falcon.HTTP_201
        req.context["result"] = _enrolment_obj(
            db.row(
                """
                select id, cid, automation_id, contact_id, contact_email, data
                from automation_enrolments
                where cid = %s and id = %s
                """,
                cid,
                outcome["enrolment_id"],
            )
        )


def _bulk_enrol_list_bucket(
    db: DB,
    cid: str,
    automation_id: str,
    list_id: str,
    hashval: int,
    hashlimit: int,
) -> JsonObj:
    result = _empty_bulk_result()
    db.set_cid(cid)

    automation = db.automations.get(automation_id)
    if automation is None:
        result["error_count"] = 1
        result["errors"].append({
            "description": "Automation was not found for this account.",
        })
        return result
    _published_enrolment_context(automation)

    lst = db.lists.get(list_id)
    if lst is None:
        result["error_count"] = 1
        result["errors"].append({
            "description": "Contact list was not found for this account.",
        })
        return result

    rows = db.execute(
        f"""
        select distinct c.contact_id, c.email
        from contacts."contacts_{cid}" c
        join contacts."contact_lists_{cid}" l on l.contact_id = c.contact_id
        where l.list_id = %s
            and ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
            and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
        order by c.contact_id
        """,
        list_id,
        hashval,
        hashval,
    ).fetchall()

    for contact_id, contact_email in rows:
        try:
            outcome = _create_enrolment_for_contact(
                db,
                cid,
                automation_id,
                automation,
                contact_id,
                contact_email,
                "list:%s" % list_id,
            )
            _record_bulk_outcome(result, outcome)
        except Exception as e:
            _record_bulk_outcome(result, {
                "status": "error",
                "contact_id": contact_id,
                "contact_email": contact_email,
                "description": str(e),
            })

    return result


@tasks.task(priority=HIGH_PRIORITY)
def bulk_enrol_list_bucket(
    cid: str,
    automation_id: str,
    list_id: str,
    hashval: int,
    hashlimit: int,
    gatherid: str,
) -> None:
    with open_db() as db:
        try:
            result = _bulk_enrol_list_bucket(
                db,
                cid,
                automation_id,
                list_id,
                hashval,
                hashlimit,
            )
            gather_complete(db, gatherid, result, False)
        except Exception as e:
            gather_complete(
                db,
                gatherid,
                {
                    "enrolled_count": 0,
                    "skipped_count": 0,
                    "error_count": 1,
                    "skipped": [],
                    "errors": [{"description": str(e)}],
                },
                False,
            )


class AutomationListEnrolments(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        _validate_doc(doc, AUTOMATION_LIST_ENROLMENT_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()

        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()
        _published_enrolment_context(automation)

        list_id = doc["list_id"]
        lst = db.lists.get(list_id)
        if lst is None:
            raise falcon.HTTPForbidden()

        contact_count = db.single(
            f"""
            select count(distinct c.contact_id)
            from contacts."contacts_{cid}" c
            join contacts."contact_lists_{cid}" l on l.contact_id = c.contact_id
            where l.list_id = %s
            """,
            list_id,
        )
        if not contact_count:
            req.context["result"] = _finish_bulk_list_enrolment([_empty_bulk_result()])
            return

        hashlimit = contacts.get_hashlimit(db, cid, [lst])
        if hashlimit == 1:
            result = _bulk_enrol_list_bucket(db, cid, id, list_id, 0, hashlimit)
            req.context["result"] = _finish_bulk_list_enrolment([result])
            return

        gatherid = gather_init(db, "automation_list_enrolment", hashlimit)
        for hashval in range(hashlimit):
            run_task(
                bulk_enrol_list_bucket,
                cid,
                id,
                list_id,
                hashval,
                hashlimit,
                gatherid,
            )

        req.context["result"] = {"id": gatherid}


class AutomationListEnrolmentStatus(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        _check_automation_gather_owner(db, id, cid, "automation_list_enrolment")
        db.set_cid(None)

        data = gather_check(db, id)
        if data is None:
            req.context["result"] = {}
        else:
            req.context["result"] = _finish_bulk_list_enrolment(data)


def _bulk_enrol_segment_bucket(
    db: DB,
    cid: str,
    automation_id: str,
    segment_id: str,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
) -> JsonObj:
    result = _empty_bulk_result()
    db.set_cid(cid)

    automation = db.automations.get(automation_id)
    if automation is None:
        result["error_count"] = 1
        result["errors"].append({
            "description": "Automation was not found for this account.",
        })
        return result
    _published_enrolment_context(automation)

    segment = db.segments.get(segment_id)
    if segment is None:
        result["error_count"] = 1
        result["errors"].append({
            "description": "Segment was not found for this account.",
        })
        return result

    segments: Dict[str, JsonObj] = {}
    segment_get_segments(db, segment["parts"], segments)
    sentrows = get_segment_sentrows(db, cid, campaignids, hashval, hashlimit)
    rows = get_segment_rows(db, cid, hashval, listfactors, hashlimit)

    cache = Cache()
    segcounts: Dict[str, int] = {}
    numrows = len(rows)
    emails = []
    for row in rows:
        if segment_eval_parts(
            segment["parts"],
            segment["operator"],
            row,
            segcounts,
            numrows,
            segments,
            sentrows,
            segment,
            hashlimit,
            cache,
        ):
            emails.append(row["Email"][0])

    if not emails:
        return result

    contact_rows = db.execute(
        f"""
        select contact_id, email
        from contacts."contacts_{cid}"
        where email = any(%s)
            and ({hashlimit} = 1 or mod(contact_id, {hashlimit}) = %s)
        order by contact_id
        """,
        emails,
        hashval,
    ).fetchall()

    for contact_id, contact_email in contact_rows:
        try:
            outcome = _create_enrolment_for_contact(
                db,
                cid,
                automation_id,
                automation,
                contact_id,
                contact_email,
                "segment:%s" % segment_id,
            )
            _record_bulk_outcome(result, outcome)
        except Exception as e:
            _record_bulk_outcome(result, {
                "status": "error",
                "contact_id": contact_id,
                "contact_email": contact_email,
                "description": str(e),
            })

    return result


@tasks.task(priority=HIGH_PRIORITY)
def bulk_enrol_segment_bucket(
    cid: str,
    automation_id: str,
    segment_id: str,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
    gatherid: str,
) -> None:
    with open_db() as db:
        try:
            result = _bulk_enrol_segment_bucket(
                db,
                cid,
                automation_id,
                segment_id,
                hashval,
                listfactors,
                hashlimit,
                campaignids,
            )
            gather_complete(db, gatherid, result, False)
        except Exception as e:
            gather_complete(
                db,
                gatherid,
                {
                    "enrolled_count": 0,
                    "skipped_count": 0,
                    "error_count": 1,
                    "skipped": [],
                    "errors": [{"description": str(e)}],
                },
                False,
            )


class AutomationSegmentEnrolments(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        _validate_doc(doc, AUTOMATION_SEGMENT_ENROLMENT_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()

        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()
        _published_enrolment_context(automation)

        segment_id = doc["segment_id"]
        segment = db.segments.get(segment_id)
        if segment is None:
            raise falcon.HTTPForbidden()

        segments: Dict[str, JsonObj] = {}
        segment_get_segments(db, segment["parts"], segments)
        campaignids = segment_get_campaignids(segment, list(segments.values()))
        hashlimit, listfactors = segment_get_params(db, cid, segment)
        db.set_cid(cid)

        if hashlimit == 1:
            result = _bulk_enrol_segment_bucket(
                db,
                cid,
                id,
                segment_id,
                0,
                listfactors,
                hashlimit,
                campaignids,
            )
            req.context["result"] = _finish_bulk_list_enrolment([result])
            return

        gatherid = gather_init(db, "automation_segment_enrolment", hashlimit)
        for hashval in range(hashlimit):
            run_task(
                bulk_enrol_segment_bucket,
                cid,
                id,
                segment_id,
                hashval,
                listfactors,
                hashlimit,
                campaignids,
                gatherid,
            )

        req.context["result"] = {"id": gatherid}


class AutomationSegmentEnrolmentStatus(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        _check_automation_gather_owner(db, id, cid, "automation_segment_enrolment")
        db.set_cid(None)

        data = gather_check(db, id)
        if data is None:
            req.context["result"] = {}
        else:
            req.context["result"] = _finish_bulk_list_enrolment(data)


class AutomationHistory(object):

    ENROLMENT_LIMIT = 100
    STEP_RUN_LIMIT = 500
    ENGAGEMENT_EVENT_LIMIT = 500

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)
        check_automation_diagnostics(req)

        db = req.context["db"]
        cid = db.get_cid()
        if db.automations.get(id) is None:
            raise falcon.HTTPForbidden()

        enrolments = [
            _enrolment_obj(row)
            for row in db.execute(
                """
                select id, cid, automation_id, contact_id, contact_email, data
                from (
                    select id, cid, automation_id, contact_id, contact_email, data
                    from automation_enrolments
                    where cid = %s and automation_id = %s
                    order by data->>'created' desc, id desc
                    limit %s
                ) e
                order by data->>'created', id
                """,
                cid,
                id,
                self.ENROLMENT_LIMIT,
            )
        ]
        enrolment_ids = [enrolment["id"] for enrolment in enrolments]

        step_runs = []
        if enrolment_ids:
            step_runs = [
                _step_run_obj(row)
                for row in db.execute(
                    """
                    select id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data
                    from (
                        select id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data
                        from automation_step_runs
                        where cid = %s and automation_id = %s and enrolment_id = any(%s)
                        order by data->>'created' desc, id desc
                        limit %s
                    ) s
                    order by data->>'created', id
                    """,
                    cid,
                    id,
                    enrolment_ids,
                    self.STEP_RUN_LIMIT,
                )
            ]

        enrolments_by_id = {enrolment["id"]: enrolment for enrolment in enrolments}
        for enrolment in enrolments:
            enrolment["step_runs"] = []
            enrolment["engagement_events"] = []
        for step_run in step_runs:
            enrolment = enrolments_by_id.get(step_run["enrolment_id"])
            if enrolment is not None:
                enrolment["step_runs"].append(step_run)

        engagement_events = [
            {
                "id": row[0],
                "type": "engagement",
                "event_type": row[8],
                "created": row[9].isoformat() if row[9] else None,
                "contact_id": row[2],
                "contact_email": row[3],
                "enrolment_id": row[6],
                "automation_email_id": row[5],
                "automation_email_name": (row[11] or {}).get("name"),
                "subject": (row[11] or {}).get("subject"),
                "send_step_run_id": row[7],
                "link_url": (row[10] or {}).get("link_url"),
                "link_index": (row[10] or {}).get("link_index"),
                "inferred": (row[10] or {}).get("inferred"),
                "inferred_from_event_type": (row[10] or {}).get("inferred_from_event_type"),
                "inferred_from_link_id": (row[10] or {}).get("inferred_from_link_id"),
                "inferred_from_link_index": (row[10] or {}).get("inferred_from_link_index"),
            }
            for row in db.execute(
                """
                select e.id, e.cid, e.contact_id, e.contact_email, e.automation_id,
                    e.automation_email_id, e.enrolment_id, e.send_step_run_id,
                    e.event_type, e.ts, e.data, ae.data
                from (
                    select id, cid, contact_id, contact_email, automation_id,
                        automation_email_id, enrolment_id, send_step_run_id,
                        event_type, ts, data
                    from automation_email_events
                    where cid = %s and automation_id = %s
                    order by ts desc, id desc
                    limit %s
                ) e
                left join automation_emails ae
                    on ae.cid = e.cid
                    and ae.automation_id = e.automation_id
                    and ae.id = e.automation_email_id
                order by e.ts, e.id
                """,
                cid,
                id,
                self.ENGAGEMENT_EVENT_LIMIT,
            )
        ]
        for engagement_event in engagement_events:
            enrolment = enrolments_by_id.get(engagement_event["enrolment_id"])
            if enrolment is not None:
                enrolment["engagement_events"].append(engagement_event)

        events = []
        for enrolment in enrolments:
            events.append(
                {
                    "type": "enrolment",
                    "created": enrolment.get("created"),
                    "modified": enrolment.get("modified"),
                    "enrolment_id": enrolment["id"],
                    "contact_id": enrolment["contact_id"],
                    "contact_email": enrolment["contact_email"],
                    "status": enrolment.get("status"),
                    "source": enrolment.get("source"),
                    "current_node_id": enrolment.get("current_node_id"),
                    "wake_at": enrolment.get("wake_at"),
                    "paused_at": enrolment.get("paused_at"),
                    "resumed_at": enrolment.get("resumed_at"),
                    "remaining_seconds": (enrolment.get("wait") or {}).get("remaining_seconds"),
                    "published_revision": enrolment.get("published_revision"),
                }
            )

        for step_run in step_runs:
            enrolment = enrolments_by_id.get(step_run["enrolment_id"], {})
            events.append(
                {
                    "type": "step_run",
                    "created": step_run.get("created"),
                    "enrolment_id": step_run["enrolment_id"],
                    "contact_id": step_run["contact_id"],
                    "contact_email": enrolment.get("contact_email"),
                    "node_id": step_run["node_id"],
                    "node_type": step_run["node_type"],
                    "node_label": step_run.get("node_label"),
                    "tag": step_run.get("tag"),
                    "tags": step_run.get("tags"),
                    "changed_tags": step_run.get("changed_tags"),
                    "list_id": step_run.get("list_id"),
                    "list_name": step_run.get("list_name"),
                    "added": step_run.get("added"),
                    "removed": step_run.get("removed"),
                    "duration": step_run.get("duration"),
                    "wait_until": step_run.get("wait_until"),
                    "wake_at": step_run.get("wake_at"),
                    "action": step_run.get("action"),
                    "skipped": step_run.get("skipped"),
                    "result": step_run.get("result"),
                    "branch": step_run.get("branch"),
                    "target_node_id": step_run.get("target_node_id"),
                    "automation_email_id": step_run.get("automation_email_id"),
                    "automation_email_name": step_run.get("automation_email_name"),
                    "subject": step_run.get("subject"),
                    "recipient_email": step_run.get("recipient_email"),
                    "route_id": step_run.get("route_id"),
                    "sent": step_run.get("sent"),
                    "throttled": step_run.get("throttled"),
                    "throttle_reason": step_run.get("throttle_reason"),
                    "email_delivery_status": step_run.get("email_delivery_status"),
                    "suppressed": step_run.get("suppressed"),
                    "suppression_reason": step_run.get("suppression_reason"),
                    "published_revision": step_run.get("published_revision"),
                    "status": step_run.get("status"),
                    "error": step_run.get("error"),
                }
            )

        for enrolment in enrolments:
            for event in enrolment.get("migration_events") or []:
                events.append({"type": "migration", "enrolment_id": enrolment["id"], **event})

        for enrolment in enrolments:
            metadata = enrolment.get("exit_metadata")
            if metadata:
                events.append({"type": "rule_exit", "enrolment_id": enrolment["id"], **metadata})
        events.extend(engagement_events)

        events.sort(key=lambda event: (event.get("created") or "", event["type"]))

        req.context["result"] = {
            "automation_id": id,
            "generated_at": _utc_now(),
            "limits": {
                "enrolments": self.ENROLMENT_LIMIT,
                "step_runs": self.STEP_RUN_LIMIT,
                "engagement_events": self.ENGAGEMENT_EVENT_LIMIT,
            },
            "enrolments": enrolments,
            "events": events,
        }


def _automation_email_condition_metadata(
    db: DB,
    cid: str,
    automation_id: str,
    automation_email_id: str,
) -> JsonObj:
    automation_email = _automation_email_obj(
        db.row(
            """
            select id, cid, automation_id, data
            from automation_emails
            where cid = %s and automation_id = %s and id = %s
            """,
            cid,
            automation_id,
            automation_email_id,
        )
    )
    if automation_email is None:
        raise falcon.HTTPBadRequest(
            title="Automation email is missing",
            description="The published condition references an automation email that was not found.",
        )
    return automation_email


def _automation_email_opened_for_enrolment(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    contact_id: int,
    automation_email_id: str,
) -> bool:
    return bool(
        db.single(
            """
            select true
            from automation_email_events
            where cid = %s
                and automation_id = %s
                and enrolment_id = %s
                and contact_id = %s
                and automation_email_id = %s
                and event_type = 'open'
            limit 1
            """,
            cid,
            automation_id,
            enrolment_id,
            contact_id,
            automation_email_id,
        )
    )


def _automation_email_clicked_for_enrolment(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    contact_id: int,
    automation_email_id: str,
    click_match: str,
    link_url: str | None,
) -> tuple[bool, str]:
    if click_match in ("url_exact", "url_prefix"):
        normalized_link_url = _normalize_automation_click_url(link_url)
        rows = db.execute(
            """
            select data->>'link_url'
            from automation_email_events
            where cid = %s
                and automation_id = %s
                and enrolment_id = %s
                and contact_id = %s
                and automation_email_id = %s
                and event_type = 'click'
            """,
            cid,
            automation_id,
            enrolment_id,
            contact_id,
            automation_email_id,
        ).fetchall()
        for row in rows:
            normalized_row_url = _normalize_automation_click_url(row[0])
            if (
                click_match == "url_exact"
                and normalized_row_url == normalized_link_url
            ) or (
                click_match == "url_prefix"
                and _automation_click_url_prefix_match(row[0], link_url)
            ):
                return True, row[0] or ""
        return False, ""

    return bool(
        db.single(
            """
            select true
            from automation_email_events
            where cid = %s
                and automation_id = %s
                and enrolment_id = %s
                and contact_id = %s
                and automation_email_id = %s
                and event_type = 'click'
            limit 1
            """,
            cid,
            automation_id,
            enrolment_id,
            contact_id,
            automation_email_id,
        )
    ), ""


def _evaluate_automation_condition_item(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    contact_id: int,
    item: JsonObj,
    index: int,
) -> JsonObj:
    item_type = item.get("type")
    result = False
    metadata: JsonObj = {
        "index": index,
        "type": item_type,
    }

    if item_type in ("has_tag", "missing_tag"):
        tags = _condition_selection(item, "tag", "tags")
        has_tag = any(_contact_has_tag(db, cid, contact_id, tag) for tag in tags)
        result = has_tag if item_type == "has_tag" else not has_tag
        metadata.update({"has_tag": has_tag})
        metadata.update({"tags": tags} if "tags" in item else {"tag": tags[0]})
    elif item_type in ("in_list", "not_in_list"):
        list_ids = _condition_selection(item, "list_id", "list_ids")
        # Check all memberships within the contact's account.
        memberships = [_contact_is_in_list(db, cid, contact_id, list_id) for list_id in list_ids]
        in_list = any(memberships)
        result = in_list if item_type == "in_list" else not in_list
        metadata.update({"in_list": in_list})
        metadata.update({"list_ids": list_ids} if "list_ids" in item else {"list_id": list_ids[0]})
    elif item_type in ("opened_email", "not_opened_email"):
        automation_email_id = item.get("automation_email_id") or ""
        automation_email = _automation_email_condition_metadata(db, cid, automation_id, automation_email_id)
        result = _automation_email_opened_for_enrolment(
            db,
            cid,
            automation_id,
            enrolment_id,
            contact_id,
            automation_email_id,
        )
        metadata.update(
            {
                "automation_email_id": automation_email_id,
                "automation_email_name": automation_email.get("name"),
                "subject": automation_email.get("subject"),
            }
        )
    elif item_type in ("clicked_email", "not_clicked_email"):
        automation_email_id = item.get("automation_email_id") or ""
        automation_email = _automation_email_condition_metadata(db, cid, automation_id, automation_email_id)
        raw_click_match = item.get("click_match") or "any"
        click_match = _automation_click_match_mode(raw_click_match)
        if click_match not in ("any", "url_exact", "url_prefix"):
            raise falcon.HTTPBadRequest(
                title="Automation condition is invalid",
                description="The published clicked email condition has an unsupported click match mode.",
            )
        result, matched_link_url = _automation_email_clicked_for_enrolment(
            db,
            cid,
            automation_id,
            enrolment_id,
            contact_id,
            automation_email_id,
            click_match,
            item.get("link_url"),
        )
        metadata.update(
            {
                "automation_email_id": automation_email_id,
                "automation_email_name": automation_email.get("name"),
                "subject": automation_email.get("subject"),
                "click_match": raw_click_match,
                "effective_click_match": click_match,
            }
        )
        if click_match in ("url_exact", "url_prefix"):
            metadata["link_url"] = item.get("link_url") or ""
            metadata["normalized_link_url"] = _normalize_automation_click_url(item.get("link_url"))
            if matched_link_url:
                metadata["matched_link_url"] = matched_link_url
    else:
        raise falcon.HTTPBadRequest(
            title="Automation condition is invalid",
            description="The published condition type is not supported.",
        )

    if item_type in ("not_opened_email", "not_clicked_email"):
        result = not result
    metadata["result"] = result
    return metadata


def _evaluate_automation_condition_group(
    db: DB,
    cid: str,
    automation_id: str,
    enrolment_id: str,
    contact_id: int,
    condition: JsonObj,
) -> JsonObj:
    mode = condition.get("mode")
    items = condition.get("items") or []
    if mode not in ("all", "any") or not items:
        raise falcon.HTTPBadRequest(
            title="Automation condition is invalid",
            description="The published condition group is not valid.",
        )

    evaluated = []
    if mode == "all":
        result = True
        for index, item in enumerate(items):
            item_result = _evaluate_automation_condition_item(db, cid, automation_id, enrolment_id, contact_id, item, index)
            evaluated.append(item_result)
            if not item_result["result"]:
                result = False
                break
    else:
        result = False
        for index, item in enumerate(items):
            item_result = _evaluate_automation_condition_item(db, cid, automation_id, enrolment_id, contact_id, item, index)
            evaluated.append(item_result)
            if item_result["result"]:
                result = True
                break

    return {
        "mode": mode,
        "result": result,
        "evaluated_count": len(evaluated),
        "conditions": evaluated[:20],
    }


def _reserve_automation_email(db: DB, cid: str, automation_id: str, contact_id: int,
                              email_id: str, run_id: str) -> bool:
    """One contact/email handoff per rolling 24 hours, across enrolments.

    The existing automation lock serialises short reservations. External sending
    happens after the transaction commits; ambiguous sends remain fail-closed.
    """
    now = datetime.utcnow()
    cutoff = _iso_datetime(now - timedelta(hours=24))
    with _locked_automation(db, cid, automation_id) as automation:
        if automation is None:
            raise falcon.HTTPForbidden()
        rows = db.execute("""
            select data from automation_step_runs
            where cid = %s and automation_id = %s and contact_id = %s
              and data->>'automation_email_id' = %s and id <> %s
              and coalesce(data->>'email_sent_at', data->>'email_reserved_at', data->>'created') > %s
              and (data->>'sent' = 'true' or data->>'email_delivery_status' in ('reserved', 'accepted', 'uncertain'))
            """, cid, automation_id, contact_id, email_id, run_id, cutoff).fetchall()
        if any(row[0].get("sent") or row[0].get("email_delivery_status") == "accepted" for row in rows):
            return False
        if any(row[0].get("email_delivery_status") == "uncertain" for row in rows):
            raise falcon.HTTPBadRequest(title="Automation email delivery uncertain",
                description="A recent attempt may have sent this email. This enrolment is held to avoid a duplicate; review the delivery before retrying.")
        if rows:
            raise falcon.HTTPBadRequest(title="Automation email send pending",
                description="Another enrolment is sending this contact the same email. Processing will retry.")
        run = db.row("select enrolment_id,node_id from automation_step_runs where cid=%s and id=%s", cid, run_id)
        assignment = subject_tests.reserve(db, cid, automation_id, email_id, run[0], run[1], contact_id, run_id)
        _patch_step_run(db, cid, run_id, {"automation_email_id": email_id,
            "subject_assignment": assignment,
            "email_reserved_at": _iso_datetime(now), "email_delivery_status": "reserved"})
    return True


def _run_next_automation_enrolment(
    db: DB,
    cid: str,
    id: str,
    enrolment_id: str,
    skip_wait: bool = False,
) -> JsonObj:
    with _locked_automation(db, cid, id) as current:
        automation = current
        if automation is None:
            raise falcon.HTTPForbidden()
        current_enrolment = _read_run_enrolment(db, cid, id, enrolment_id)
        if current_enrolment and not current_enrolment.get("claim_token") and current_enrolment.get("status") in AutomationEnrolmentCancel.CANCELLABLE_STATUSES:
            if exit_rules.apply(db, cid, automation, enrolment_id, "before_action") == "exited":
                return {"enrolment": _read_run_enrolment(db, cid, id, enrolment_id), "step_run": None}
        if automation.get("status") == "paused":
            raise falcon.HTTPBadRequest(
                title="Automation is paused",
                description="Resume the automation before running test steps.",
            )

        published = automation.get("published")
        if not published:
            raise falcon.HTTPBadRequest(
                title="Automation is not published",
                description="Automation execution uses the published workflow snapshot.",
            )

        now_dt = datetime.utcnow()
        now = now_dt.isoformat() + "Z"
        claim_token = shortuuid.uuid()
        enrolment = _claim_run_enrolment(
            db,
            cid,
            id,
            enrolment_id,
            claim_token,
            now,
            now_dt - CLAIM_STALE_AFTER,
        )
    if enrolment.get("pending_rule_exit") or exit_rules.matching_rule(db, cid, enrolment["contact_id"], published):
        _advance_claimed_enrolment(db, cid, id, enrolment_id, claim_token, {})
        return {"enrolment": _read_run_enrolment(db, cid, id, enrolment_id), "step_run": None}
    original_status = _running_status(enrolment)
    run_id = shortuuid.uuid()
    run_inserted = False
    current_node_id = enrolment.get("current_node_id")
    node: JsonObj = {"id": current_node_id}
    node_type = "unknown"

    try:
        nodes = published.get("nodes") or []
        _validate_unique_node_ids(nodes, "Duplicate automation node IDs")
        node_index = None
        for i, node in enumerate(nodes):
            if node.get("id") == current_node_id:
                node_index = i
                break

        if node_index is None:
            raise falcon.HTTPBadRequest(
                title="Current automation node is missing",
                description="The enrolment current_node_id was not found in the published workflow.",
            )

        node = nodes[node_index]
        node_type = node.get("type")
        if node_type not in ("add_tag", "remove_tag", "add_to_list", "remove_from_list", "enrol_automation", "remove_automation", "wait_duration", "if_has_tag", "if_missing_tag", "if_conditions", "if_opened_email", "if_clicked_email", "go_to", "send_email", "exit"):
            raise falcon.HTTPBadRequest(
                title="Unsupported automation node",
                description=(
                    "%s nodes are not supported by manual execution yet. "
                    "Only add_tag, remove_tag, add_to_list, remove_from_list, enrol_automation, remove_automation, wait_duration, if_has_tag, if_missing_tag, if_conditions, if_opened_email, if_clicked_email, go_to, send_email and exit nodes can be executed manually."
                    % node_type
                ),
            )

        if original_status == "waiting" and node_type != "wait_duration":
            raise falcon.HTTPBadRequest(
                title="Enrolment wait state is invalid",
                description="Waiting enrolments must remain on a wait_duration node.",
            )

        if original_status == "waiting":
            wake_at = enrolment.get("wake_at")
            if not wake_at:
                raise falcon.HTTPBadRequest(
                    title="Waiting enrolment is missing wake_at",
                    description="The waiting enrolment cannot continue without wake_at metadata.",
                )
            if now_dt < _parse_datetime(wake_at) and not skip_wait:
                _release_run_claim(
                    db,
                    cid,
                    id,
                    enrolment_id,
                    claim_token,
                    "waiting",
                    now,
                )
                raise falcon.HTTPBadRequest(
                    title="Wait has not elapsed",
                    description="This enrolment is waiting until %s." % wake_at,
                )

        # A second defence against repeated transitions, including diagnostic
        # skip-wait calls. Only an actually elapsed wait resets this budget.
        transitions = max(0, _safe_int(enrolment.get("transitions_without_wait"), 0))
        elapsed_wait = False
        if original_status == "waiting":
            started = (enrolment.get("wait") or {}).get("started_at")
            try:
                elapsed_wait = bool(started and now_dt >= _parse_datetime(enrolment["wake_at"])
                                    and ((_parse_datetime(enrolment["wake_at"]) > _parse_datetime(started)) if (enrolment.get("wait") or {}).get("wait_until") else (now_dt - _parse_datetime(started)).total_seconds() >= 300))
            except (TypeError, ValueError):
                elapsed_wait = False
        if elapsed_wait:
            transitions = 0
        visited = enrolment.get("visited_node_ids", [])
        if not isinstance(visited, list) or any(not isinstance(value, str) for value in visited):
            raise falcon.HTTPBadRequest(title="Automation visit history is invalid",
                description="This enrolment has malformed visit history and has been held for review.")
        visited = list(dict.fromkeys(visited))
        if elapsed_wait:
            visited = []
        inherited = enrolment.get("cross_automation_visits", [])
        if not isinstance(inherited, list) or any(
            not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(value, str) or not value for value in pair)
            for pair in inherited
        ):
            _validation_error("Cross-automation visit history is malformed. Review this enrolment before resuming.")
        if elapsed_wait:
            inherited = []
        if original_status != "waiting" and [id, current_node_id] in inherited:
            raise falcon.HTTPBadRequest(title="Automation loop detected",
                description="This contact returned to an already visited step across automations without an elapsed wait. It has been held before repeating the action.")
        if original_status != "waiting" and current_node_id in visited:
            raise falcon.HTTPBadRequest(title="Automation loop detected",
                description="This enrolment returned to step %s without an elapsed wait. It has been held before repeating the action." % current_node_id)
        if transitions >= max(1000, len(nodes) * 2):
            raise falcon.HTTPBadRequest(title="Automation transition safety limit reached",
                description="This enrolment made too many transitions without an elapsed wait and has been held. Review its workflow before resuming.")

        run_data = {
            "id": run_id,
            "status": "running",
            "node_label": node.get("label"),
            "published_revision": automation.get("published_revision"),
            "claim_token": claim_token,
            "created": now,
        }
        _insert_step_run(
            db,
            cid,
            id,
            enrolment_id,
            enrolment["contact_id"],
            current_node_id,
            node_type,
            run_data,
        )
        run_inserted = True
        success_data = {
            "status": "succeeded",
        }

        if original_status == "waiting":
            wake_at = enrolment.get("wake_at")
            wait = enrolment.get("wait") or {}
            success_data.update(
                {
                    "action": "wait_complete",
                    "duration": wait.get("duration", node.get("duration")),
                    "wait_until": wait.get("wait_until"),
                    "wake_at": wake_at,
                    "skipped": skip_wait and now_dt < _parse_datetime(wake_at),
                }
            )

            if node_index + 1 < len(nodes):
                enrolment_update = {
                    "status": "ready",
                    "current_node_id": nodes[node_index + 1]["id"],
                    "wake_at": None,
                    "wait": None,
                    "modified": now,
                }
            else:
                enrolment_update = {
                    "status": "completed",
                    "wake_at": None,
                    "wait": None,
                    "modified": now,
                }
        elif node_type in ("enrol_automation", "remove_automation"):
            # Side effects are deferred to the atomic acknowledgement below.
            enrolment_update = {"status": "ready" if node_index + 1 < len(nodes) else "completed", "modified": now}
            if node_index + 1 < len(nodes):
                enrolment_update["current_node_id"] = nodes[node_index + 1]["id"]
        elif node_type in ("add_tag", "remove_tag"):
            tags = _action_tags(node)
            if not tags:
                raise falcon.HTTPBadRequest(
                    title="%s node is missing tag configuration" % ("Add tag" if node_type == "add_tag" else "Remove tag"),
                    description="The published tag action must select at least one valid tag.",
                )
            tagcounts = {}
            correlation = enrolment.get("trigger_correlation_id") or "automation:%s" % enrolment_id
            depth = _safe_int(enrolment.get("trigger_depth"), 0) + 1
            source = {"type": "automation", "automation_id": id, "enrolment_id": enrolment_id,
                      "node_id": current_node_id, "step_run_id": run_id,
                      "published_revision": automation.get("published_revision")}
            try:
                with db.transaction():
                    contacts.lock_exit_rule_changes(db, cid)
                    # Serialize this contact's tag batch, including concurrent workflows.
                    db.execute(f'select contact_id from contacts."contacts_{cid}" where contact_id = %s for update', enrolment["contact_id"])
                    for tag in sorted(tags):
                        if node_type == "add_tag":
                            db.execute("insert into alltags (cid, tag, added, count) values (%s, %s, now(), 0) on conflict (cid, tag) do nothing", cid, tag)
                            contacts.add_tag(db, cid, enrolment["contact_email"], enrolment["contact_id"], tag,
                                             None, {}, tagcounts, [], source, correlation, depth, automation_trigger_strict=True)
                        else:
                            contacts.remove_tag(db, cid, enrolment["contact_email"], enrolment["contact_id"], tag,
                                                tagcounts, [], source, correlation, depth, automation_trigger_strict=True)
                    for tag, count in tagcounts.items():
                        db.execute("update alltags set count = count + %s where cid = %s and tag = %s", count, cid, tag)
                    if node_type == "remove_tag":
                        db.execute("delete from alltags where cid = %s and tag = any(%s) and count <= 0", cid, tags)
            except Exception:
                log.exception("Automation tag batch failed")
                raise falcon.HTTPBadRequest(title="Automation tag action failed",
                    description="No changes from this tag action were committed. The enrolment is held for review.")
            success_data.update({"action": node_type, "tags": tags, "changed_tags": list(tagcounts),
                                 "tag": tags[0] if len(tags) == 1 else None})
            if node_type == "remove_tag":
                success_data["removed"] = bool(tagcounts)
            enrolment_update = {"status": "ready" if node_index + 1 < len(nodes) else "completed", "modified": now}
            if node_index + 1 < len(nodes):
                enrolment_update["current_node_id"] = nodes[node_index + 1]["id"]
        elif node_type in ("add_to_list", "remove_from_list"):
            list_ids = _action_lists(node)
            if not list_ids:
                raise falcon.HTTPBadRequest(title="List action is missing valid list configuration",
                    description="Select at least one valid, unique contact list.")
            source = {"type": "automation", "automation_id": id, "enrolment_id": enrolment_id,
                      "node_id": current_node_id, "step_run_id": run_id,
                      "published_revision": automation.get("published_revision")}
            correlation = enrolment.get("trigger_correlation_id") or "automation:%s" % enrolment_id
            depth = _safe_int(enrolment.get("trigger_depth"), 0) + 1
            helper = _add_contact_to_list if node_type == "add_to_list" else _remove_contact_from_list
            changed_key = "added" if node_type == "add_to_list" else "removed"
            results = {}
            try:
                with db.transaction():
                    contacts.lock_exit_rule_changes(db, cid)
                    # Share the contact lock with tag batches. Lock lists in stable order
                    # before counters so overlapping batches cannot invert list locks.
                    db.execute(f'select contact_id from contacts."contacts_{cid}" where contact_id = %s for update', enrolment["contact_id"])
                    for list_id in sorted(list_ids):
                        if db.single("select id from lists where cid = %s and id = %s for update", cid, list_id) is None:
                            raise falcon.HTTPBadRequest(title="Automation list is missing",
                                description="The published list node references a contact list that was not found.")
                    for list_id in sorted(list_ids):
                        results[list_id] = helper(db, cid, enrolment["contact_id"], enrolment["contact_email"],
                            list_id, source, correlation, depth, strict_events=True)
            except falcon.HTTPBadRequest:
                raise
            except Exception:
                log.exception("Automation list batch failed")
                raise falcon.HTTPBadRequest(title="Automation list action failed",
                    description="No changes from this list action were committed. Check that all selected lists still exist in this account. The enrolment is held for review.")
            success_data.update({"action": node_type, "list_ids": list_ids,
                "changed_list_ids": [value for value in list_ids if results[value][changed_key]],
                "lists": [results[value] for value in list_ids]})
            if len(list_ids) == 1:
                success_data.update(results[list_ids[0]])
            enrolment_update = {"status": "ready" if node_index + 1 < len(nodes) else "completed", "modified": now}
            if node_index + 1 < len(nodes):
                enrolment_update["current_node_id"] = nodes[node_index + 1]["id"]
        elif node_type == "wait_duration":
            duration = node.get("duration") or {}
            deadline = _wait_deadline(node["wait_until"]) if "wait_until" in node else None
            wake_at = _iso_datetime(deadline) if deadline is not None else _wake_at(now_dt, duration)
            success_data.update(
                {
                    "status": "waiting",
                    "action": "wait_start",
                    "duration": duration,
                    "wake_at": wake_at,
                }
            )
            enrolment_update = {
                "status": "waiting",
                "current_node_id": current_node_id,
                "wake_at": wake_at,
                "wait": {
                    "node_id": current_node_id,
                    "duration": duration,
                    **({"wait_until": wake_at} if deadline is not None else {}),
                    "started_at": now,
                    "wake_at": wake_at,
                    "published_revision": automation.get("published_revision"),
                },
                "modified": now,
            }
            if deadline is not None:
                success_data["wait_until"] = wake_at
                if deadline <= now_dt:
                    success_data.update({"status": "succeeded", "action": "wait_deadline_passed"})
                    enrolment_update.update({"status": "ready" if node_index + 1 < len(nodes) else "completed", "wait": None, "wake_at": None})
                    if node_index + 1 < len(nodes):
                        enrolment_update["current_node_id"] = nodes[node_index + 1]["id"]
        elif node_type in ("if_has_tag", "if_missing_tag"):
            tag = node.get("draft_tag")
            if not tag:
                raise falcon.HTTPBadRequest(
                    title="%s node is missing tag configuration" % node_type,
                    description="The published %s node does not include a tag." % node_type,
                )

            has_tag = _contact_has_tag(db, cid, enrolment["contact_id"], tag)
            result = has_tag if node_type == "if_has_tag" else not has_tag
            branch = "yes" if result else "no"
            target_node_id = node.get("yes_node_id") if result else node.get("no_node_id")
            if _node_by_id(nodes, target_node_id) is None:
                raise falcon.HTTPBadRequest(
                    title="Automation branch target is missing",
                    description="The published %s %s target was not found in the published workflow." % (node_type, branch),
                )

            success_data.update(
                {
                    "action": "branch",
                    "condition": "has_tag" if node_type == "if_has_tag" else "missing_tag",
                    "tag": tag,
                    "has_tag": has_tag,
                    "result": result,
                    "branch": branch,
                    "target_node_id": target_node_id,
                }
            )
            enrolment_update = {
                "status": "ready",
                "current_node_id": target_node_id,
                "modified": now,
            }
        elif node_type == "if_conditions":
            group_result = _evaluate_automation_condition_group(
                db,
                cid,
                id,
                enrolment_id,
                enrolment["contact_id"],
                node.get("condition") or {},
            )
            branch = "yes" if group_result["result"] else "no"
            target_node_id = node.get("yes_node_id") if group_result["result"] else node.get("no_node_id")
            if _node_by_id(nodes, target_node_id) is None:
                raise falcon.HTTPBadRequest(
                    title="Automation branch target is missing",
                    description="The published if_conditions %s target was not found in the published workflow." % branch,
                )

            success_data.update(
                {
                    "action": "if_conditions",
                    "mode": group_result["mode"],
                    "result": group_result["result"],
                    "branch": branch,
                    "target_node_id": target_node_id,
                    "evaluated_count": group_result["evaluated_count"],
                    "conditions": group_result["conditions"],
                }
            )
            enrolment_update = {
                "status": "ready",
                "current_node_id": target_node_id,
                "modified": now,
            }
        elif node_type in ("if_opened_email", "if_clicked_email"):
            automation_email_id = node.get("automation_email_id")
            automation_email = _automation_email_obj(
                db.row(
                    """
                    select id, cid, automation_id, data
                    from automation_emails
                    where cid = %s and automation_id = %s and id = %s
                    """,
                    cid,
                    id,
                    automation_email_id,
                )
            )
            if automation_email is None:
                raise falcon.HTTPBadRequest(
                    title="Automation email is missing",
                    description="The published %s node references an automation email that was not found." % node_type,
                )

            event_type = "open" if node_type == "if_opened_email" else "click"
            raw_click_match = node.get("click_match") or "any"
            click_match = _automation_click_match_mode(raw_click_match)
            normalized_link_url = ""
            matched_link_url = ""
            if node_type == "if_clicked_email" and click_match in ("url_exact", "url_prefix"):
                normalized_link_url = _normalize_automation_click_url(node.get("link_url"))
                rows = db.execute(
                    """
                    select data->>'link_url'
                    from automation_email_events
                    where cid = %s
                        and automation_id = %s
                        and enrolment_id = %s
                        and contact_id = %s
                        and automation_email_id = %s
                        and event_type = 'click'
                    """,
                    cid,
                    id,
                    enrolment_id,
                    enrolment["contact_id"],
                    automation_email_id,
                ).fetchall()
                result = False
                for row in rows:
                    normalized_row_url = _normalize_automation_click_url(row[0])
                    if (
                        click_match == "url_exact"
                        and normalized_row_url == normalized_link_url
                    ) or (
                        click_match == "url_prefix"
                        and _automation_click_url_prefix_match(row[0], node.get("link_url"))
                    ):
                        result = True
                        matched_link_url = row[0] or ""
                        break
            else:
                result = bool(
                    db.single(
                        """
                        select true
                        from automation_email_events
                        where cid = %s
                            and automation_id = %s
                            and enrolment_id = %s
                            and contact_id = %s
                            and automation_email_id = %s
                            and event_type = %s
                        limit 1
                        """,
                        cid,
                        id,
                        enrolment_id,
                        enrolment["contact_id"],
                        automation_email_id,
                        event_type,
                    )
                )
            branch = "yes" if result else "no"
            target_node_id = node.get("yes_node_id") if result else node.get("no_node_id")
            if _node_by_id(nodes, target_node_id) is None:
                raise falcon.HTTPBadRequest(
                    title="Automation branch target is missing",
                    description="The published %s %s target was not found in the published workflow." % (node_type, branch),
                )

            success_data.update(
                {
                    "action": node_type,
                    "automation_email_id": automation_email_id,
                    "automation_email_name": automation_email.get("name"),
                    "subject": automation_email.get("subject"),
                    "result": result,
                    "branch": branch,
                    "target_node_id": target_node_id,
                    "node_label": node.get("label"),
                    "published_revision": automation.get("published_revision"),
                }
            )
            if node_type == "if_clicked_email":
                success_data["click_match"] = raw_click_match
                success_data["effective_click_match"] = click_match
                if click_match in ("url_exact", "url_prefix"):
                    success_data["link_url"] = node.get("link_url") or ""
                    success_data["normalized_link_url"] = normalized_link_url
                    if matched_link_url:
                        success_data["matched_link_url"] = matched_link_url
            enrolment_update = {
                "status": "ready",
                "current_node_id": target_node_id,
                "modified": now,
            }
        elif node_type == "go_to":
            target_node_id = node.get("target_node_id")
            if _node_by_id(nodes, target_node_id) is None:
                raise falcon.HTTPBadRequest(
                    title="Automation go to target is missing",
                    description="The published go_to target was not found in the published workflow.",
                )

            success_data.update(
                {
                    "action": "go_to",
                    "target_node_id": target_node_id,
                }
            )
            enrolment_update = {
                "status": "ready",
                "current_node_id": target_node_id,
                "modified": now,
            }
        elif node_type == "send_email":
            automation_email_id = node.get("automation_email_id")
            automation_email = _automation_email_obj(
                db.row(
                    """
                    select id, cid, automation_id, data
                    from automation_emails
                    where cid = %s and automation_id = %s and id = %s
                    """,
                    cid,
                    id,
                    automation_email_id,
                )
            )
            if automation_email is None:
                raise falcon.HTTPBadRequest(
                    title="Automation email is missing",
                    description="The published send_email node references an automation email that was not found.",
                )

            subject = remove_newlines(automation_email["subject"])
            recipient_email = enrolment["contact_email"]
            suppression_reason = _automation_send_suppression_reason(
                db, cid, enrolment["contact_id"], recipient_email
            )
            route_id = None
            sent = False
            throttled = False
            if suppression_reason is None:
                fromname, fromemail, returnpath, replyto = _automation_email_sender(automation_email)

                route = _automation_execution_route(db, cid)
                route_id = route["id"]

                imagebucket = os.environ["s3_imagebucket"]
                oldcid = db.get_cid()
                db.set_cid(None)
                try:
                    company = db.companies.get(cid)
                    parentcompany = db.companies.get(company["cid"]) if company else None
                    if parentcompany is not None:
                        imagebucket = parentcompany.get("s3_imagebucket", imagebucket)
                finally:
                    db.set_cid(oldcid)

                html, _ = generate_html(db, automation_email, run_id, imagebucket)
                fromdomain = ""
                if "@" in returnpath:
                    fromdomain = returnpath.split("@")[-1].strip().lower()
                elif "@" in fromemail:
                    fromdomain = fromemail.split("@")[-1].strip().lower()
                fromaddr = email.utils.formataddr((fromname, fromemail))

                allowed = _reserve_automation_email(db, cid, id, enrolment["contact_id"], automation_email_id, run_id)
                throttled = not allowed
                if allowed:
                    assignment = db.single("select data->'subject_assignment' from automation_step_runs where cid=%s and id=%s", cid, run_id)
                    if assignment:
                        subject = assignment["subject"]
                    try:
                        send_backend_mail(
                            db,
                            cid,
                            route,
                            html,
                            fromaddr,
                            returnpath,
                            fromdomain,
                            replyto,
                            recipient_email,
                            recipient_email,
                            subject,
                            campid=run_id,
                            source_type="automation",
                            source_id=id,
                            source_ids={
                                "automation_id": id,
                                "automation_email_id": automation_email_id,
                                "enrolment_id": enrolment_id,
                                "node_id": current_node_id,
                                "step_run_id": run_id,
                                "published_revision": automation.get("published_revision"),
                            },
                            metadata={
                                "automation_id": id,
                                "automation_email_id": automation_email_id,
                                "enrolment_id": enrolment_id,
                                "node_id": current_node_id,
                                "step_run_id": run_id,
                                "published_revision": automation.get("published_revision"),
                            },
                        )
                        sent = True
                        subject_tests.outcome(db, cid, run_id, "accepted")
                        _patch_step_run(db, cid, run_id, {"email_delivery_status": "accepted", "email_sent_at": _utc_now()})
                    except MailNotSentError as e:
                        subject_tests.outcome(db, cid, run_id, "not_sent")
                        _patch_step_run(db, cid, run_id, {"email_delivery_status": "not_sent"})
                        raise falcon.HTTPBadRequest(title="Error sending automation email", description=str(e))
                    except Exception as e:
                        subject_tests.outcome(db, cid, run_id, "uncertain")
                        _patch_step_run(db, cid, run_id, {"email_delivery_status": "uncertain"})
                        log.warning("Error sending automation email: %s", e)
                        raise falcon.HTTPBadRequest(
                            title="Automation email delivery uncertain",
                            description="The send outcome could not be confirmed. This enrolment is held to avoid a duplicate email. Review the delivery before retrying.",
                        )

            success_data.update(
                {
                    "action": "send_email",
                    "automation_email_id": automation_email_id,
                    "automation_email_name": automation_email.get("name"),
                    "subject": subject,
                    "recipient_email": recipient_email,
                    "route_id": route_id,
                    "sent": sent,
                    "throttled": throttled,
                    "throttle_reason": "same_email_sent_within_24_hours" if throttled else None,
                    "suppressed": suppression_reason is not None,
                    "suppression_reason": suppression_reason,
                }
            )

            if node_index + 1 < len(nodes):
                enrolment_update = {
                    "status": "ready",
                    "current_node_id": nodes[node_index + 1]["id"],
                    "modified": now,
                }
            else:
                enrolment_update = {
                    "status": "completed",
                    "modified": now,
                }
        else:
            enrolment_update = {
                "status": "exited",
                "modified": now,
            }
        enrolment_update["transitions_without_wait"] = transitions + 1
        # A wait's start and completion are one visit; only a real delay resets
        # local and inherited visit history, never an expired/skipped wait.
        if not elapsed_wait and current_node_id not in visited:
            visited.append(current_node_id)
        enrolment_update["visited_node_ids"] = visited
        if "cross_automation_visits" in enrolment:
            enrolment_update["cross_automation_visits"] = inherited
        if node_type == "remove_automation":
            _commit_automation_removal_action(db, cid, id, enrolment, node, claim_token,
                run_id, success_data, enrolment_update)
        elif node_type == "enrol_automation":
            _commit_automation_enrolment_action(db, cid, id, enrolment, node, claim_token,
                run_id, success_data, enrolment_update, visited, inherited)
        else:
            _patch_step_run(db, cid, run_id, success_data)
            _advance_claimed_enrolment(db, cid, id, enrolment_id, claim_token, enrolment_update)
    except subject_tests.Gate as gate:
        with _locked_automation(db, cid, id):
            current = db.single("select data from automation_subject_tests where cid=%s and id=%s", cid, gate.experiment_id)
            pending = current and current.get("status") != "selected"
            _patch_step_run(db, cid, run_id, {"status": "deferred", "action": "subject_test_gate", "experiment_id": gate.experiment_id})
            _release_run_claim(db, cid, id, enrolment_id, claim_token, "ready", _utc_now(),
                {"subject_gate": gate.experiment_id if pending else None, "retry_after": gate.deadline if pending else None})
    except falcon.HTTPError as e:
        fail_now = _utc_now()
        wait_not_elapsed = e.title == "Wait has not elapsed"
        failure_status = original_status
        failure_update: JsonObj = {}
        if not wait_not_elapsed:
            failure_status, failure_update = _automation_failure_update(
                enrolment,
                e,
                original_status,
                node,
                node_type,
                run_id if run_inserted else None,
                fail_now,
            )
        if run_inserted:
            step_failure = {
                "status": "failed",
                "error": _bounded_error_text(e.description or e.title),
                "failed_at": fail_now,
            }
            if failure_update:
                last_error = failure_update.get("last_error") or {}
                step_failure.update(
                    {
                        "retryable": last_error.get("retryable"),
                        "failure_class": last_error.get("failure_class"),
                        "retry_count": last_error.get("retry_count"),
                        "retry_after": last_error.get("retry_after"),
                        "failure_status": last_error.get("status"),
                    }
                )
            _patch_step_run(db, cid, run_id, step_failure)
        _release_run_claim(
            db,
            cid,
            id,
            enrolment_id,
            claim_token,
            failure_status,
            fail_now,
            failure_update,
        )
        raise

    return {
        "enrolment": _enrolment_obj(
            db.row(
                """
                select id, cid, automation_id, contact_id, contact_email, data
                from automation_enrolments
                where cid = %s and automation_id = %s and id = %s
                """,
                cid,
                id,
                enrolment_id,
            )
        ),
        "step_run": _step_run_obj(
            db.row(
                """
                select id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data
                from automation_step_runs
                where cid = %s and id = %s
                """,
                cid,
                run_id,
            )
        ),
    }


def _automation_process_limit(value: object) -> int:
    if value is None:
        return AUTOMATION_PROCESS_DEFAULT_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise falcon.HTTPBadRequest(
            title="Invalid automation process limit",
            description="limit must be a positive integer.",
        )
    if limit < 1:
        raise falcon.HTTPBadRequest(
            title="Invalid automation process limit",
            description="limit must be at least 1.",
        )
    return min(limit, AUTOMATION_PROCESS_MAX_LIMIT)


def _automation_processing_enabled() -> bool:
    return (os.environ.get("automation_processing_enabled") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _env_enabled(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _env_positive_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    value = os.environ.get(name)
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        log.warning("Ignoring invalid %s=%r; using default %s.", name, value, default)
        return default
    if parsed < minimum:
        return minimum
    if maximum is not None:
        return min(parsed, maximum)
    return parsed


def _customer_automation_processing_enabled(db: DB, cid: str) -> bool:
    oldcid = db.get_cid()
    db.set_cid(None)
    try:
        company = db.companies.get(cid)
        return bool(company and company.get("automation_processing_enabled") is True)
    finally:
        db.set_cid(oldcid)


def _automation_triggers_enabled() -> bool:
    return (os.environ.get("automation_triggers_enabled") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _automation_trigger_manual_events_enabled() -> bool:
    return (os.environ.get("automation_trigger_manual_events_enabled") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _automation_segment_trigger_baseline_enabled() -> bool:
    return (os.environ.get("automation_segment_trigger_baseline_enabled") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _automation_segment_trigger_diff_enabled() -> bool:
    return (os.environ.get("automation_segment_trigger_diff_enabled") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _automation_trigger_limit(value: object) -> int:
    if value is None:
        return AUTOMATION_TRIGGER_DEFAULT_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise falcon.HTTPBadRequest(
            title="Invalid automation trigger process limit",
            description="limit must be a positive integer.",
        )
    if limit < 1:
        raise falcon.HTTPBadRequest(
            title="Invalid automation trigger process limit",
            description="limit must be at least 1.",
        )
    return min(limit, AUTOMATION_TRIGGER_MAX_LIMIT)


def _automation_segment_baseline_limit(
    value: object,
    default: int,
    maximum: int,
    name: str,
) -> int:
    if value is None:
        return default
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise falcon.HTTPBadRequest(
            title="Invalid automation segment baseline limit",
            description="%s must be a positive integer." % name,
        )
    if limit < 1:
        raise falcon.HTTPBadRequest(
            title="Invalid automation segment baseline limit",
            description="%s must be at least 1." % name,
        )
    return min(limit, maximum)


def _automation_segment_diff_event_limit(value: object) -> int:
    return _automation_segment_baseline_limit(
        value,
        AUTOMATION_SEGMENT_DIFF_DEFAULT_EVENT_LIMIT,
        AUTOMATION_SEGMENT_DIFF_MAX_EVENT_LIMIT,
        "limit_events",
    )


def _automation_trigger_event_list_limit(value: object) -> int:
    if value is None:
        return AUTOMATION_TRIGGER_EVENT_LIST_DEFAULT_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise falcon.HTTPBadRequest(
            title="Invalid automation trigger event limit",
            description="limit must be a positive integer.",
        )
    if limit < 1:
        raise falcon.HTTPBadRequest(
            title="Invalid automation trigger event limit",
            description="limit must be at least 1.",
        )
    return min(limit, AUTOMATION_TRIGGER_MAX_LIMIT)


def _automation_segment_trigger_status_limit(value: object) -> int:
    if value is None:
        return AUTOMATION_SEGMENT_TRIGGER_STATUS_DEFAULT_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise falcon.HTTPBadRequest(
            title="Invalid automation segment trigger status limit",
            description="limit must be a positive integer.",
        )
    if limit < 1:
        raise falcon.HTTPBadRequest(
            title="Invalid automation segment trigger status limit",
            description="limit must be at least 1.",
        )
    return min(limit, AUTOMATION_SEGMENT_TRIGGER_STATUS_MAX_LIMIT)


def _automation_trigger_max_depth() -> int:
    try:
        return max(1, int(os.environ.get("automation_trigger_max_depth") or 3))
    except ValueError:
        return 3


def _automation_trigger_cooldown_minutes() -> int:
    try:
        return max(0, int(os.environ.get("automation_trigger_cooldown_minutes") or AUTOMATION_TRIGGER_COOLDOWN_MINUTES))
    except ValueError:
        return AUTOMATION_TRIGGER_COOLDOWN_MINUTES


def _automation_scheduler_account_limit() -> int:
    value = os.environ.get("automation_processing_account_limit")
    if value is None:
        return AUTOMATION_PROCESS_ACCOUNT_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return AUTOMATION_PROCESS_ACCOUNT_LIMIT
    return max(1, min(limit, AUTOMATION_PROCESS_ACCOUNT_LIMIT))


def _automation_scheduler_process_limit() -> int:
    try:
        return _automation_process_limit(os.environ.get("automation_processing_limit"))
    except falcon.HTTPBadRequest:
        return AUTOMATION_PROCESS_DEFAULT_LIMIT


def _automation_segment_scan_account_limit() -> int:
    value = os.environ.get("automation_segment_trigger_account_limit")
    if value is None:
        return AUTOMATION_SEGMENT_SCAN_ACCOUNT_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return AUTOMATION_SEGMENT_SCAN_ACCOUNT_LIMIT
    return max(1, min(limit, AUTOMATION_SEGMENT_SCAN_ACCOUNT_LIMIT))


def _empty_processing_counts() -> JsonObj:
    return {status: 0 for status in AUTOMATION_PROCESSING_STATUSES}


def _automation_processing_feature_flags() -> JsonObj:
    return {
        "automation_processing_enabled": _automation_processing_enabled(),
        "automation_triggers_enabled": _automation_triggers_enabled(),
        "automation_trigger_emission_enabled": contacts.automation_trigger_emission_enabled(),
        "automation_trigger_manual_events_enabled_debug": _automation_trigger_manual_events_enabled(),
    }


def _automation_processing_status(db: DB, cid: str) -> JsonObj:
    stale_before = datetime.utcnow() - CLAIM_STALE_AFTER
    summary = _empty_processing_counts()
    by_automation: Dict[str, JsonObj] = {}

    rows = db.execute(
        """
        select
            a.id,
            a.data->>'name',
            a.data->>'status',
            a.data->>'published_revision',
            e.data->>'status',
            count(*)::int,
            count(*) filter (
                where e.data->>'status' = 'running'
                    and nullif(e.data->>'claimed_at', '')::timestamptz < %s
            )::int
        from automation_enrolments e
        join automations a on a.cid = e.cid and a.id = e.automation_id
        where e.cid = %s
        group by
            a.id,
            a.data->>'name',
            a.data->>'status',
            a.data->>'published_revision',
            e.data->>'status'
        order by a.data->>'name', a.id
        """,
        stale_before,
        cid,
    ).fetchall()

    for automation_id, name, automation_status, published_revision, status, count, stale_count in rows:
        status = status or "unknown"
        if automation_id not in by_automation:
            by_automation[automation_id] = {
                "automation_id": automation_id,
                "automation_name": name or "",
                "automation_status": automation_status or "",
                "published_revision": int(published_revision) if str(published_revision or "").isdigit() else published_revision,
                "counts": _empty_processing_counts(),
            }

        if status in summary:
            summary[status] += int(count or 0)
            by_automation[automation_id]["counts"][status] += int(count or 0)
        summary["total"] += int(count or 0)
        by_automation[automation_id]["counts"]["total"] += int(count or 0)
        if stale_count:
            summary["stale_running"] += int(stale_count or 0)
            by_automation[automation_id]["counts"]["stale_running"] += int(stale_count or 0)

    failures = [
        {
            "enrolment_id": enrolment_id,
            "automation_id": automation_id,
            "automation_name": automation_name or "",
            "contact_email": contact_email,
            "current_node_id": data.get("current_node_id"),
            "failed_at": (data.get("last_error") or {}).get("at") or data.get("modified") or data.get("created"),
            "error": (data.get("last_error") or {}).get("description") or (data.get("last_error") or {}).get("title") or "",
        }
        for enrolment_id, automation_id, automation_name, contact_email, data in db.execute(
            """
            select e.id, e.automation_id, a.data->>'name', e.contact_email, e.data
            from automation_enrolments e
            join automations a on a.cid = e.cid and a.id = e.automation_id
            where e.cid = %s and e.data->>'status' = 'failed'
            order by
                coalesce(
                    nullif(e.data->'last_error'->>'at', '')::timestamptz,
                    nullif(e.data->>'modified', '')::timestamptz,
                    nullif(e.data->>'created', '')::timestamptz
                ) desc nulls last,
                e.id desc
            limit 25
            """,
            cid,
        ).fetchall()
    ]

    stale_running = [
        {
            "enrolment_id": enrolment_id,
            "automation_id": automation_id,
            "automation_name": automation_name or "",
            "contact_email": contact_email,
            "claimed_at": data.get("claimed_at"),
            "claimed_node_id": data.get("claimed_node_id"),
            "claimed_published_revision": data.get("claimed_published_revision"),
            "running_status": data.get("running_status"),
        }
        for enrolment_id, automation_id, automation_name, contact_email, data in db.execute(
            """
            select e.id, e.automation_id, a.data->>'name', e.contact_email, e.data
            from automation_enrolments e
            join automations a on a.cid = e.cid and a.id = e.automation_id
            where e.cid = %s
                and e.data->>'status' = 'running'
                and nullif(e.data->>'claimed_at', '')::timestamptz < %s
            order by nullif(e.data->>'claimed_at', '')::timestamptz, e.id
            limit 25
            """,
            cid,
            stale_before,
        ).fetchall()
    ]

    return {
        "summary": summary,
        "automations": sorted(
            by_automation.values(),
            key=lambda item: ((item.get("automation_name") or "").lower(), item.get("automation_id") or ""),
        ),
        "recent_failures": failures,
        "stale_running": stale_running,
        "flags": _automation_processing_feature_flags(),
    }


def _automation_recovery_limit(value: object) -> int:
    limit = _safe_int(value, AUTOMATION_RECOVERY_DEFAULT_LIMIT)
    return max(1, min(limit, AUTOMATION_RECOVERY_MAX_LIMIT))


def _automation_recovery_lock(db: DB, lock_id: int) -> bool:
    return bool(db.single("select pg_try_advisory_xact_lock(%s::bigint)", lock_id))


def _automation_recovery_base_result(action: str, cid: str, dry_run: bool, limit: int) -> JsonObj:
    return {
        "action": action,
        "company_id": cid,
        "dry_run": dry_run,
        "stale_after_minutes": int(CLAIM_STALE_AFTER.total_seconds() / 60),
        "matched_count": 0,
        "changed_count": 0,
        "limit": limit,
        "locked": False,
        "items": [],
        "warnings": [],
    }


def recover_stale_automation_enrolment_claims(
    db: DB,
    cid: str,
    dry_run: bool = True,
    limit: int = AUTOMATION_RECOVERY_DEFAULT_LIMIT,
    automation_id: str | None = None,
    recovered_by_uid: str | None = None,
) -> JsonObj:
    limit = _automation_recovery_limit(limit)
    action = "clear_stale_enrolment_claims"
    result = _automation_recovery_base_result(action, cid, dry_run, limit)
    stale_before = datetime.utcnow() - CLAIM_STALE_AFTER
    now = _iso_datetime(datetime.utcnow())

    with db.transaction():
        if not _automation_recovery_lock(db, AUTOMATION_RECOVERY_ENROLMENT_CLAIMS_LOCK):
            result["locked"] = True
            return result

        if dry_run:
            rows = db.execute(
                """
                select e.id, e.automation_id, a.data->>'name', e.contact_email,
                    case when jsonb_typeof(e.data->'pending_rule_exit')='object' then 'exited' else e.data->>'running_status' end, e.data->>'claimed_at', e.data->>'claimed_node_id'
                from automation_enrolments e
                join automations a on a.cid = e.cid and a.id = e.automation_id
                where e.cid = %s
                    and (%s is null or e.automation_id = %s)
                    and e.data->>'status' = 'running'
                    and e.data->>'running_status' in ('ready', 'waiting')
                    and nullif(e.data->>'claimed_at', '')::timestamptz < %s
                order by nullif(e.data->>'claimed_at', '')::timestamptz, e.id
                limit %s
                """,
                cid,
                automation_id,
                automation_id,
                stale_before,
                limit,
            ).fetchall()
        else:
            rows = db.execute(
                """
                with candidates as (
                    select e.id, e.automation_id, a.data->>'name' as automation_name, e.contact_email,
                        e.data->>'running_status' as restore_status,
                        e.data->>'claimed_at' as claimed_at,
                        e.data->>'claimed_node_id' as claimed_node_id
                    from automation_enrolments e
                    join automations a on a.cid = e.cid and a.id = e.automation_id
                    where e.cid = %s
                        and (%s is null or e.automation_id = %s)
                        and e.data->>'status' = 'running'
                        and e.data->>'running_status' in ('ready', 'waiting')
                        and nullif(e.data->>'claimed_at', '')::timestamptz < %s
                    order by nullif(e.data->>'claimed_at', '')::timestamptz, e.id
                    limit %s
                    for update skip locked
                )
                update automation_enrolments e
                set data = e.data || jsonb_build_object(
                    'status', candidates.restore_status,
                    'running_status', null,
                    'claim_token', null,
                    'claimed_at', null,
                    'claimed_node_id', null,
                    'claimed_published_revision', null,
                    'modified', %s,
                    'admin_recovered_at', %s,
                    'admin_recovered_by_uid', %s,
                    'admin_recovery_action', %s
                ) || case when jsonb_typeof(e.data->'pending_rule_exit')='object'
                    then %s::jsonb || jsonb_build_object('exit_metadata',e.data->'pending_rule_exit')
                    else '{}'::jsonb end
                from candidates
                where e.cid = %s and e.id = candidates.id
                returning e.id, e.automation_id, candidates.automation_name, candidates.contact_email,
                    e.data->>'status', candidates.claimed_at, candidates.claimed_node_id
                """,
                cid,
                automation_id,
                automation_id,
                stale_before,
                limit,
                now,
                now,
                recovered_by_uid,
                action,
                {**_retry_clear_patch(), "status": "exited", "wait": None, "wake_at": None,
                 "paused_at": None, "resumed_at": None, "pending_rule_exit": None},
                cid,
            ).fetchall()

    result["matched_count"] = len(rows)
    result["changed_count"] = 0 if dry_run else len(rows)
    result["items"] = [
        {
            "enrolment_id": enrolment_id,
            "automation_id": automation_id,
            "automation_name": automation_name or "",
            "contact_email": contact_email or "",
            "restore_status": restore_status,
            "claimed_at": claimed_at,
            "claimed_node_id": claimed_node_id,
        }
        for enrolment_id, automation_id, automation_name, contact_email, restore_status, claimed_at, claimed_node_id in rows
    ]
    return result


def recover_stale_automation_trigger_event_claims(
    db: DB,
    cid: str,
    dry_run: bool = True,
    limit: int = AUTOMATION_RECOVERY_DEFAULT_LIMIT,
    event_type: str | None = None,
    recovered_by_uid: str | None = None,
) -> JsonObj:
    limit = _automation_recovery_limit(limit)
    action = "clear_stale_trigger_event_claims"
    result = _automation_recovery_base_result(action, cid, dry_run, limit)
    stale_before = datetime.utcnow() - CLAIM_STALE_AFTER
    now = _utc_now()

    with db.transaction():
        if not _automation_recovery_lock(db, AUTOMATION_RECOVERY_TRIGGER_EVENT_CLAIMS_LOCK):
            result["locked"] = True
            return result

        if dry_run:
            rows = db.execute(
                """
                select id, event_type, contact_email, data->>'claimed_at',
                    data->>'tag', data->>'list_id', data->>'segment_id'
                from automation_trigger_events
                where cid = %s
                    and (%s is null or event_type = %s)
                    and data->>'status' = 'processing'
                    and nullif(data->>'claimed_at', '')::timestamptz < %s
                order by nullif(data->>'claimed_at', '')::timestamptz, id
                limit %s
                """,
                cid,
                event_type,
                event_type,
                stale_before,
                limit,
            ).fetchall()
        else:
            rows = db.execute(
                """
                with candidates as (
                    select id, event_type, contact_email, data->>'claimed_at' as claimed_at,
                        data->>'tag' as tag, data->>'list_id' as list_id, data->>'segment_id' as segment_id
                    from automation_trigger_events
                    where cid = %s
                        and (%s is null or event_type = %s)
                        and data->>'status' = 'processing'
                        and nullif(data->>'claimed_at', '')::timestamptz < %s
                    order by nullif(data->>'claimed_at', '')::timestamptz, id
                    limit %s
                    for update skip locked
                )
                update automation_trigger_events e
                set data = e.data || jsonb_build_object(
                    'status', 'pending',
                    'claimed_at', null,
                    'admin_recovered_at', %s,
                    'admin_recovered_by_uid', %s,
                    'admin_recovery_action', %s,
                    'recovery_count', coalesce((e.data->>'recovery_count')::int, 0) + 1
                )
                from candidates
                where e.cid = %s and e.id = candidates.id
                returning e.id, e.event_type, candidates.contact_email, candidates.claimed_at,
                    candidates.tag, candidates.list_id, candidates.segment_id
                """,
                cid,
                event_type,
                event_type,
                stale_before,
                limit,
                now,
                recovered_by_uid,
                action,
                cid,
            ).fetchall()

    result["matched_count"] = len(rows)
    result["changed_count"] = 0 if dry_run else len(rows)
    result["items"] = [
        {
            "event_id": event_id,
            "event_type": row_event_type,
            "contact_email": contact_email or "",
            "claimed_at": claimed_at,
            "tag": tag,
            "list_id": list_id,
            "segment_id": segment_id,
        }
        for event_id, row_event_type, contact_email, claimed_at, tag, list_id, segment_id in rows
    ]
    return result


def recover_stale_automation_segment_scanner_claims(
    db: DB,
    cid: str,
    dry_run: bool = True,
    limit: int = AUTOMATION_RECOVERY_DEFAULT_LIMIT,
    segment_id: str | None = None,
    recovered_by_uid: str | None = None,
) -> JsonObj:
    limit = _automation_recovery_limit(limit)
    action = "clear_stale_segment_scanner_claims"
    result = _automation_recovery_base_result(action, cid, dry_run, limit)
    stale_before = datetime.utcnow() - CLAIM_STALE_AFTER
    now = _utc_now()

    with db.transaction():
        if not _automation_recovery_lock(db, AUTOMATION_RECOVERY_SEGMENT_SCANNER_CLAIMS_LOCK):
            result["locked"] = True
            return result

        if dry_run:
            rows = db.execute(
                """
                select s.id, s.segment_id, coalesce(seg.data->>'name', ''), s.status,
                    s.claimed_at, s.hashlimit, s.last_hashval
                from automation_segment_trigger_snapshots s
                left join segments seg on seg.cid = s.cid and seg.id = s.segment_id
                where s.cid = %s
                    and (%s is null or s.segment_id = %s)
                    and s.status in ('baselining', 'diffing')
                    and s.claimed_at < %s
                order by s.claimed_at, s.id
                limit %s
                """,
                cid,
                segment_id,
                segment_id,
                stale_before,
                limit,
            ).fetchall()
        else:
            rows = db.execute(
                """
                with candidates as (
                    select s.id, s.segment_id, coalesce(seg.data->>'name', '') as segment_name,
                        s.status as previous_status, s.claimed_at, s.hashlimit, s.last_hashval
                    from automation_segment_trigger_snapshots s
                    left join segments seg on seg.cid = s.cid and seg.id = s.segment_id
                    where s.cid = %s
                        and (%s is null or s.segment_id = %s)
                        and s.status in ('baselining', 'diffing')
                        and s.claimed_at < %s
                    order by s.claimed_at, s.id
                    limit %s
                    for update of s skip locked
                )
                update automation_segment_trigger_snapshots s
                set status = 'idle',
                    claimed_at = null,
                    claim_token = null,
                    data = s.data || jsonb_build_object(
                        'admin_recovered_at', %s,
                        'admin_recovered_by_uid', %s,
                        'admin_recovery_action', %s,
                        'admin_recovered_status', candidates.previous_status
                    )
                from candidates
                where s.cid = %s and s.id = candidates.id
                returning s.id, s.segment_id, candidates.segment_name, candidates.previous_status,
                    candidates.claimed_at, candidates.hashlimit, candidates.last_hashval
                """,
                cid,
                segment_id,
                segment_id,
                stale_before,
                limit,
                now,
                recovered_by_uid,
                action,
                cid,
            ).fetchall()

    result["matched_count"] = len(rows)
    result["changed_count"] = 0 if dry_run else len(rows)
    result["items"] = [
        {
            "snapshot_id": snapshot_id,
            "segment_id": row_segment_id,
            "segment_name": segment_name or "",
            "previous_status": previous_status,
            "claimed_at": claimed_at.isoformat() if hasattr(claimed_at, "isoformat") else claimed_at,
            "hashlimit": hashlimit,
            "last_hashval": last_hashval,
        }
        for snapshot_id, row_segment_id, segment_name, previous_status, claimed_at, hashlimit, last_hashval in rows
    ]
    return result


def _automation_segment_trigger_status_flags(db: DB, cid: str) -> JsonObj:
    return {
        "automation_segment_trigger_baseline_enabled": _automation_segment_trigger_baseline_enabled(),
        "automation_segment_trigger_diff_enabled": _automation_segment_trigger_diff_enabled(),
        "automation_triggers_enabled": _automation_triggers_enabled(),
        "customer_automation_processing_enabled": _customer_automation_processing_enabled(db, cid),
    }


def _segment_trigger_ref_obj(
    automation_id: str,
    automation_name: str | None,
    automation_status: str | None,
    trigger_type: str,
) -> JsonObj:
    return {
        "automation_id": automation_id,
        "automation_name": automation_name or "",
        "automation_status": automation_status or "",
        "trigger_type": trigger_type,
    }


def _referenced_segment_trigger_status_rows(db: DB, cid: str) -> Dict[str, JsonObj]:
    referenced: Dict[str, JsonObj] = {}
    for automation in json_iter(
        db.execute(
            """
            select id, cid, data
            from automations
            where cid = %s
                and data->>'status' in ('published', 'paused')
                and data->'published' is not null
            order by data->>'name', id
            """,
            cid,
        )
    ):
        published = automation.get("published") or {}
        for trigger in _entry_triggers(published.get("entry") or {"type": "manual"}):
            trigger_type = trigger.get("type")
            if trigger_type not in SEGMENT_TRIGGER_EVENT_TYPES:
                continue
            segment_id = (trigger.get("segment_id") or "").strip()
            if not segment_id:
                continue
            if segment_id not in referenced:
                referenced[segment_id] = {
                    "segment_id": segment_id,
                    "segment_name": "",
                    "referenced_by": [],
                    "referenced_by_count": 0,
                }
            referenced[segment_id]["referenced_by_count"] += 1
            if len(referenced[segment_id]["referenced_by"]) < AUTOMATION_SEGMENT_TRIGGER_STATUS_REFERENCE_LIMIT:
                referenced[segment_id]["referenced_by"].append(
                    _segment_trigger_ref_obj(
                        automation.get("id"),
                        automation.get("name"),
                        automation.get("status"),
                        trigger_type,
                    )
                )

    if referenced:
        for segment_id, data in db.execute(
            """
            select id, data
            from segments
            where cid = %s and id = any(%s)
            """,
            cid,
            list(referenced.keys()),
        ):
            if segment_id in referenced:
                referenced[segment_id]["segment_name"] = (data or {}).get("name") or ""

    return referenced


def _bounded_snapshot_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("description") or value.get("reason") or value.get("message") or value.get("title") or ""
    return _bounded_error_text(str(value))


def _automation_segment_trigger_status(db: DB, cid: str, limit: int) -> JsonObj:
    referenced = _referenced_segment_trigger_status_rows(db, cid)
    segment_ids = sorted(
        referenced.keys(),
        key=lambda segment_id: (
            (referenced[segment_id].get("segment_name") or "").lower(),
            segment_id,
        ),
    )[:limit]

    snapshots: Dict[str, JsonObj] = {}
    member_counts: Dict[str, int] = {}
    recent_event_counts: Dict[str, JsonObj] = {}
    stale_before = datetime.now(tzutc()) - CLAIM_STALE_AFTER
    event_cutoff = datetime.now(tzutc()) - timedelta(days=AUTOMATION_SEGMENT_TRIGGER_STATUS_EVENT_DAYS)

    if segment_ids:
        for row in db.execute(
            """
            select
                segment_id,
                status,
                hashlimit,
                last_hashval,
                last_started_at,
                last_completed_at,
                claimed_at,
                data
            from automation_segment_trigger_snapshots
            where cid = %s and segment_id = any(%s)
            """,
            cid,
            segment_ids,
        ):
            segment_id, status, hashlimit, last_hashval, last_started_at, last_completed_at, claimed_at, data = row
            data = data or {}
            running = status in ("baselining", "diffing")
            stale_claim = bool(running and claimed_at and claimed_at < stale_before)
            snapshots[segment_id] = {
                "exists": True,
                "status": status or "",
                "baseline_complete": data.get("baseline_complete") is True,
                "hashlimit": hashlimit,
                "last_hashval": last_hashval,
                "last_started_at": last_started_at.isoformat() if hasattr(last_started_at, "isoformat") else last_started_at,
                "last_completed_at": last_completed_at.isoformat() if hasattr(last_completed_at, "isoformat") else last_completed_at,
                "claimed_at": claimed_at.isoformat() if hasattr(claimed_at, "isoformat") else claimed_at,
                "running": running,
                "stale_claim": stale_claim,
                "member_count": 0,
                "last_error": _bounded_snapshot_text(data.get("last_error")),
                "skipped_reason": _bounded_snapshot_text(data.get("skipped_reason") or data.get("reason")),
            }

        member_counts = {
            segment_id: int(count or 0)
            for segment_id, count in db.execute(
                """
                select segment_id, count(*)::int
                from automation_segment_trigger_members
                where cid = %s and segment_id = any(%s)
                group by segment_id
                """,
                cid,
                segment_ids,
            )
        }

        for segment_id, event_type, count in db.execute(
            """
            select data->>'segment_id', event_type, count(*)::int
            from automation_trigger_events
            where cid = %s
                and event_type in ('segment_entered', 'segment_left')
                and data->>'segment_id' = any(%s)
                and ts >= %s
            group by data->>'segment_id', event_type
            """,
            cid,
            segment_ids,
            event_cutoff,
        ):
            recent_event_counts.setdefault(segment_id, {
                "segment_entered": 0,
                "segment_left": 0,
            })[event_type] = int(count or 0)

    summary = {
        "referenced_segments": len(referenced),
        "returned_segments": len(segment_ids),
        "missing_snapshots": 0,
        "baseline_complete": 0,
        "baseline_incomplete": 0,
        "running": 0,
        "stale_claims": 0,
        "members": 0,
        "recent_events": {
            "segment_entered": 0,
            "segment_left": 0,
        },
    }
    segments = []
    for segment_id in segment_ids:
        snapshot = snapshots.get(segment_id) or {
            "exists": False,
            "status": "baseline_needed",
            "baseline_complete": False,
            "hashlimit": None,
            "last_hashval": None,
            "last_started_at": None,
            "last_completed_at": None,
            "claimed_at": None,
            "running": False,
            "stale_claim": False,
            "member_count": 0,
            "last_error": "",
            "skipped_reason": "",
        }
        snapshot["member_count"] = member_counts.get(segment_id, 0)
        events = recent_event_counts.get(segment_id) or {
            "segment_entered": 0,
            "segment_left": 0,
        }

        if not snapshot["exists"]:
            summary["missing_snapshots"] += 1
        elif snapshot["baseline_complete"]:
            summary["baseline_complete"] += 1
        else:
            summary["baseline_incomplete"] += 1
        if snapshot["running"]:
            summary["running"] += 1
        if snapshot["stale_claim"]:
            summary["stale_claims"] += 1
        summary["members"] += snapshot["member_count"]
        summary["recent_events"]["segment_entered"] += events["segment_entered"]
        summary["recent_events"]["segment_left"] += events["segment_left"]

        segments.append({
            **referenced[segment_id],
            "snapshot": snapshot,
            "recent_events": events,
        })

    return {
        "summary": summary,
        "segments": segments,
        "flags": _automation_segment_trigger_status_flags(db, cid),
        "limit": limit,
        "reference_limit": AUTOMATION_SEGMENT_TRIGGER_STATUS_REFERENCE_LIMIT,
        "event_window_days": AUTOMATION_SEGMENT_TRIGGER_STATUS_EVENT_DAYS,
    }


def _trigger_event_obj(row) -> JsonObj | None:
    if row is None:
        return None
    event_id, cid, contact_id, contact_email, event_type, ts, data = row
    ret = copy.deepcopy(data)
    ret["id"] = event_id
    ret["cid"] = cid
    ret["contact_id"] = contact_id
    ret["contact_email"] = contact_email
    ret["event_type"] = event_type
    ret["ts"] = ts.isoformat() if hasattr(ts, "isoformat") else ts
    return ret


def _bounded_trigger_result_items(items: object) -> List[JsonObj]:
    if not isinstance(items, list):
        return []

    allowed = {
        "event_id",
        "status",
        "reason",
        "description",
        "automation_id",
        "automation_name",
        "contact_id",
        "contact_email",
        "event_type",
        "tag",
        "list_id",
        "segment_id",
        "enrolment_id",
        "existing_enrolment_id",
    }
    ret = []
    for item in items[:AUTOMATION_TRIGGER_EVENT_RESPONSE_DETAIL_LIMIT]:
        if not isinstance(item, dict):
            continue
        ret.append({key: item.get(key) for key in allowed if key in item})
    return ret


def _automation_trigger_event_source_names(
    db: DB,
    cid: str,
    rows: List[object],
) -> Dict[str, str]:
    source_ids = []
    for row in rows:
        data = row[6] or {}
        if not isinstance(data, dict):
            continue
        source = data.get("source") or {}
        if not isinstance(source, dict):
            continue
        automation_id = source.get("automation_id")
        if source.get("type") == "automation" and automation_id:
            source_ids.append(automation_id)

    if not source_ids:
        return {}

    return {
        automation_id: name
        for automation_id, name in db.execute(
            """
            select id, data->>'name'
            from automations
            where cid = %s and id = any(%s)
            """,
            cid,
            list(set(source_ids)),
        )
    }


def _project_automation_trigger_event(row, source_names: Dict[str, str]) -> JsonObj:
    event = _trigger_event_obj(row)
    data = row[6] or {}
    if event is None:
        return {}
    if not isinstance(data, dict):
        data = {}

    source = data.get("source") or {}
    if not isinstance(source, dict):
        source = {}
    source_automation_id = source.get("automation_id") if source.get("type") == "automation" else None

    return {
        "id": event["id"],
        "timestamp": event["ts"],
        "event_type": event["event_type"],
        "contact_email": event["contact_email"],
        "tag": data.get("tag"),
        "list_id": data.get("list_id"),
        "segment_id": data.get("segment_id"),
        "status": data.get("status"),
        "source_type": source.get("type"),
        "source_automation_id": source_automation_id,
        "source_automation_name": source_names.get(source_automation_id) if source_automation_id else None,
        "correlation_id": data.get("correlation_id"),
        "depth": data.get("depth"),
        "processed_at": data.get("processed_at"),
        "results": _bounded_trigger_result_items(data.get("results")),
        "errors": _bounded_trigger_result_items(data.get("error") or data.get("errors")),
    }


def _automation_trigger_source(source: JsonObj | None) -> JsonObj:
    source = source or {}
    ret = {
        "type": str(source.get("type") or "manual")[:64],
    }
    for key in (
        "automation_id",
        "enrolment_id",
        "node_id",
        "step_run_id",
        "mode",
        "segment_id",
        "scan_id",
    ):
        value = source.get(key)
        if value:
            ret[key] = str(value)[:128]
    for key in ("bucket", "hashlimit"):
        value = source.get(key)
        if value is not None:
            try:
                ret[key] = int(value)
            except (TypeError, ValueError):
                pass
    return ret


def _trigger_event_selector(event: JsonObj) -> tuple[str | None, str | None]:
    event_type = event.get("event_type")
    if event_type in TAG_TRIGGER_EVENT_TYPES:
        return "tag", event.get("tag")
    if event_type in LIST_TRIGGER_EVENT_TYPES:
        return "list_id", event.get("list_id")
    if event_type in SEGMENT_TRIGGER_EVENT_TYPES:
        return "segment_id", event.get("segment_id")
    return None, None


def _create_automation_trigger_event(
    db: DB,
    cid: str,
    event_type: str,
    contact_email: str,
    tag: str | None = None,
    list_id: str | None = None,
    segment_id: str | None = None,
    source: JsonObj | None = None,
    correlation_id: str | None = None,
    depth: int = 0,
    created_by: str | None = None,
    manual_debug: bool = False,
) -> JsonObj:
    if event_type not in SUPPORTED_TRIGGER_EVENT_TYPES:
        raise falcon.HTTPBadRequest(
            title="Unsupported trigger event",
            description="Only tag_added, tag_removed, list_joined, list_left, segment_entered and segment_left trigger events are supported.",
        )

    if event_type in TAG_TRIGGER_EVENT_TYPES:
        tag = fix_tag(tag or "")
        if not tag:
            raise falcon.HTTPBadRequest(
                title="Trigger tag is required",
                description="Tag trigger events require a tag.",
            )
    elif event_type in LIST_TRIGGER_EVENT_TYPES:
        list_id = (list_id or "").strip()
        if not list_id:
            raise falcon.HTTPBadRequest(
                title="Trigger list is required",
                description="List trigger events require a contact list.",
            )
        if db.lists.get(list_id) is None:
            raise falcon.HTTPBadRequest(
                title="Trigger list not found",
                description="List trigger events require a contact list from this account.",
            )
    else:
        segment_id = (segment_id or "").strip()
        if not segment_id:
            raise falcon.HTTPBadRequest(
                title="Trigger segment is required",
                description="Segment trigger events require a segment.",
            )
        if db.segments.get(segment_id) is None:
            raise falcon.HTTPBadRequest(
                title="Trigger segment not found",
                description="Segment trigger events require a segment from this account.",
            )

    if not contact_email or len(contact_email) > 320:
        raise falcon.HTTPBadRequest(
            title="Contact email is required",
            description="Trigger events require an existing contact email.",
        )

    contact = db.row(
        f"""
        select contact_id, email
        from contacts."contacts_{cid}"
        where lower(email) = lower(%s)
        order by contact_id
        limit 1
        """,
        contact_email,
    )
    if contact is None:
        raise falcon.HTTPBadRequest(
            title="Contact not found",
            description="Trigger events require an existing contact in this account.",
        )
    contact_id, stored_email = contact

    source_data = _automation_trigger_source(source)
    source_automation_id = source_data.get("automation_id")
    if source_automation_id:
        db.set_cid(cid)
        if db.automations.get(source_automation_id) is None:
            raise falcon.HTTPBadRequest(
                title="Source automation not found",
                description="The source automation must belong to this account.",
            )

    now = datetime.utcnow()
    event_id = shortuuid.uuid()
    data = {
        "status": "pending",
        "source": source_data,
        "correlation_id": correlation_id or shortuuid.uuid(),
        "depth": depth,
        "manual_debug": manual_debug,
        "created_by": created_by,
        "created": now.isoformat() + "Z",
        "processed_at": None,
        "results": [],
    }
    if event_type in TAG_TRIGGER_EVENT_TYPES:
        data["tag"] = tag
    elif event_type in LIST_TRIGGER_EVENT_TYPES:
        data["list_id"] = list_id
    else:
        data["segment_id"] = segment_id
    db.execute(
        """
        insert into automation_trigger_events
            (id, cid, contact_id, contact_email, event_type, ts, data)
        values (%s, %s, %s, %s, %s, %s, %s)
        """,
        event_id,
        cid,
        contact_id,
        stored_email,
        event_type,
        now,
        data,
    )
    return _trigger_event_obj(
        db.row(
            """
            select id, cid, contact_id, contact_email, event_type, ts, data
            from automation_trigger_events
            where cid = %s and id = %s
            """,
            cid,
            event_id,
        )
    )


def _claim_pending_automation_trigger_events(db: DB, cid: str, limit: int) -> List[JsonObj]:
    now = _utc_now()
    stale_before = datetime.utcnow() - CLAIM_STALE_AFTER
    with db.transaction():
        rows = db.execute(
            """
            with candidates as (
                select id, data->>'status' as previous_status
                from automation_trigger_events
                where cid = %s
                    and (
                        data->>'status' = 'pending'
                        or (
                            data->>'status' = 'processing'
                            and nullif(data->>'claimed_at', '')::timestamptz < %s
                        )
                    )
                order by ts, id
                limit %s
                for update skip locked
            )
            update automation_trigger_events e
            set data = e.data || jsonb_build_object(
                'status', 'processing',
                'claimed_at', %s,
                'recovered_at',
                    case
                        when candidates.previous_status = 'processing' then to_jsonb(%s::text)
                        else coalesce(e.data->'recovered_at', 'null'::jsonb)
                    end,
                'recovery_count',
                    case
                        when candidates.previous_status = 'processing'
                            then to_jsonb(coalesce((e.data->>'recovery_count')::int, 0) + 1)
                        else coalesce(e.data->'recovery_count', '0'::jsonb)
                    end
            )
            from candidates
            where e.id = candidates.id
            returning e.id, e.cid, e.contact_id, e.contact_email, e.event_type, e.ts, e.data
            """,
            cid,
            stale_before,
            limit,
            now,
            now,
        ).fetchall()
    return [_trigger_event_obj(row) for row in rows]


def _matching_trigger_automations(db: DB, cid: str, event: JsonObj) -> List[JsonObj]:
    selector_field, selector_value = _trigger_event_selector(event)
    if event.get("event_type") not in SUPPORTED_TRIGGER_EVENT_TYPES or not selector_field or not selector_value:
        return []
    rows = db.execute(
        """
        select id, cid, data
        from automations
        where cid = %s
            and data->>'status' in ('published', 'paused')
            and data->'published' is not null
            and (
                (
                    data->'published'->'entry'->>'type' = %s
                    and data->'published'->'entry'->>%s = %s
                )
                or (
                    data->'published'->'entry'->>'type' = 'multi'
                    and exists (
                        select 1
                        from jsonb_array_elements(coalesce(data->'published'->'entry'->'triggers', '[]'::jsonb)) trigger
                        where trigger->>'type' = %s
                            and trigger->>%s = %s
                    )
                )
            )
        order by data->>'name', id
        """,
        cid,
        event.get("event_type"),
        selector_field,
        selector_value,
        event.get("event_type"),
        selector_field,
        selector_value,
    ).fetchall()
    return [automation for automation in (json_obj(row) for row in rows) if automation is not None]


def _trigger_cooldown_active(
    db: DB,
    cid: str,
    event: JsonObj,
    automation_id: str,
) -> bool:
    cooldown_minutes = _automation_trigger_cooldown_minutes()
    if cooldown_minutes <= 0:
        return False
    selector_field, selector_value = _trigger_event_selector(event)
    if not selector_field or not selector_value:
        return False
    return bool(
        db.single(
            """
            select e.id
            from automation_trigger_events e
            cross join lateral jsonb_array_elements(coalesce(e.data->'results', '[]'::jsonb)) r
            where e.cid = %s
                and e.id <> %s
                and e.contact_id = %s
                and e.event_type = %s
                and e.data->>%s = %s
                and e.ts >= (now() at time zone 'utc') - (%s::text || ' minutes')::interval
                and r->>'automation_id' = %s
                and r->>'status' = 'enrolled'
            limit 1
            """,
            cid,
            event.get("id"),
            event.get("contact_id"),
            event.get("event_type"),
            selector_field,
            selector_value,
            cooldown_minutes,
            automation_id,
        )
    )


def _trigger_detail(result: JsonObj, detail: JsonObj) -> None:
    if len(result["details"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
        result["details"].append(detail)


def _process_automation_trigger_event(db: DB, cid: str, event: JsonObj) -> JsonObj:
    result: JsonObj = {
        "processed": 1,
        "enrolled": 0,
        "suppressed": 0,
        "failed": 0,
        "no_match": 0,
        "details": [],
        "errors": [],
        "event_results": [],
    }
    selector_field, selector_value = _trigger_event_selector(event)
    depth = int(event.get("depth") or 0)
    source = event.get("source") or {}

    def record_event_result(item: JsonObj) -> None:
        if len(result["event_results"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
            result["event_results"].append(item)

    if event.get("event_type") not in SUPPORTED_TRIGGER_EVENT_TYPES or not selector_field or not selector_value:
        result["failed"] += 1
        error = {
            "event_id": event.get("id"),
            "reason": "invalid_event",
            "description": "Trigger event is missing a supported type or selector.",
        }
        result["errors"].append(error)
        record_event_result({"status": "failed", **error})
        return result

    exit_rules.process_event(db, cid, event)

    if depth >= _automation_trigger_max_depth():
        result["suppressed"] += 1
        detail = {
            "event_id": event.get("id"),
            "status": "suppressed",
            "reason": "max_depth",
            "description": "Trigger event depth exceeded the configured limit.",
        }
        _trigger_detail(result, detail)
        record_event_result(detail)
        return result

    automations = _matching_trigger_automations(db, cid, event)
    if not automations:
        result["no_match"] += 1
        detail = {
            "event_id": event.get("id"),
            "status": "no_match",
            "reason": "no_matching_trigger",
            "description": "No published automation trigger matched this event.",
        }
        _trigger_detail(result, detail)
        record_event_result(detail)
        return result

    for automation in automations:
        automation_id = automation.get("id")
        base_detail = {
            "event_id": event.get("id"),
            "automation_id": automation_id,
            "automation_name": automation.get("name"),
            "contact_id": event.get("contact_id"),
            "contact_email": event.get("contact_email"),
            "event_type": event.get("event_type"),
        }
        if selector_field:
            base_detail[selector_field] = selector_value
        try:
            if source.get("type") == "automation" and source.get("automation_id") == automation_id:
                result["suppressed"] += 1
                detail = {
                    **base_detail,
                    "status": "suppressed",
                    "reason": "same_automation_source",
                    "description": "Trigger event was caused by the same automation.",
                }
                _trigger_detail(result, detail)
                record_event_result(detail)
                continue

            if _trigger_cooldown_active(db, cid, event, automation_id):
                result["suppressed"] += 1
                detail = {
                    **base_detail,
                    "status": "suppressed",
                    "reason": "cooldown",
                    "description": "A recent matching trigger already enrolled this contact.",
                }
                _trigger_detail(result, detail)
                record_event_result(detail)
                continue

            outcome = _create_enrolment_for_contact(
                db,
                cid,
                automation_id,
                automation,
                int(event.get("contact_id")),
                event.get("contact_email"),
                "trigger:%s" % event.get("id"),
                event.get("correlation_id"),
                depth,
            )
            if outcome.get("status") == "enrolled":
                result["enrolled"] += 1
                detail = {
                    **base_detail,
                    "status": "enrolled",
                    "enrolment_id": outcome.get("enrolment_id"),
                }
                _trigger_detail(result, detail)
                record_event_result(detail)
            elif outcome.get("status") == "skipped":
                result["suppressed"] += 1
                detail = {
                    **base_detail,
                    "status": "suppressed",
                    "reason": outcome.get("reason"),
                    "description": outcome.get("description"),
                    "existing_enrolment_id": outcome.get("existing_enrolment_id"),
                }
                _trigger_detail(result, detail)
                record_event_result(detail)
            else:
                result["failed"] += 1
                detail = {
                    **base_detail,
                    "status": "failed",
                    "description": outcome.get("description") or "Trigger enrolment failed.",
                }
                if len(result["errors"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                    result["errors"].append(detail)
                record_event_result(detail)
        except Exception as e:
            result["failed"] += 1
            detail = {
                **base_detail,
                "status": "failed",
                "description": str(e),
            }
            if len(result["errors"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["errors"].append(detail)
            record_event_result(detail)

    return result


def _finish_automation_trigger_event(
    db: DB,
    cid: str,
    event_id: str,
    event_result: JsonObj,
) -> None:
    now = _utc_now()
    status = "processed"
    if event_result.get("failed") and not (
        event_result.get("enrolled") or event_result.get("suppressed") or event_result.get("no_match")
    ):
        status = "failed"
    db.execute(
        """
        update automation_trigger_events
        set data = data || jsonb_build_object(
            'status', %s,
            'processed_at', %s,
            'results', %s::jsonb->'items',
            'error', %s::jsonb->'items'
        )
        where cid = %s and id = %s and data->>'status' = 'processing'
        """,
        status,
        now,
        {"items": event_result.get("event_results") or []},
        {"items": event_result.get("errors") or []},
        cid,
        event_id,
    )


def _process_pending_automation_trigger_events(db: DB, cid: str, limit: int) -> JsonObj:
    if not _automation_triggers_enabled():
        log.info("Automation trigger processing is disabled; set automation_triggers_enabled=true to enable processing.")
        return {
            "enabled": False,
            "processed": 0,
            "enrolled": 0,
            "suppressed": 0,
            "failed": 0,
            "no_match": 0,
            "details": [],
            "errors": [],
        }

    result: JsonObj = {
        "enabled": True,
        "processed": 0,
        "enrolled": 0,
        "suppressed": 0,
        "failed": 0,
        "no_match": 0,
        "details": [],
        "errors": [],
    }

    for event in _claim_pending_automation_trigger_events(db, cid, limit):
        try:
            event_result = _process_automation_trigger_event(db, cid, event)
        except Exception as e:
            event_result = {
                "processed": 1,
                "enrolled": 0,
                "suppressed": 0,
                "failed": 1,
                "no_match": 0,
                "details": [],
                "errors": [{
                    "event_id": event.get("id"),
                    "description": str(e),
                }],
                "event_results": [{
                    "status": "failed",
                    "reason": "processor_error",
                    "description": str(e),
                }],
            }

        _finish_automation_trigger_event(db, cid, event.get("id"), event_result)
        result["processed"] += int(event_result.get("processed", 0) or 0)
        result["enrolled"] += int(event_result.get("enrolled", 0) or 0)
        result["suppressed"] += int(event_result.get("suppressed", 0) or 0)
        result["failed"] += int(event_result.get("failed", 0) or 0)
        result["no_match"] += int(event_result.get("no_match", 0) or 0)
        for detail in event_result.get("details", []):
            if len(result["details"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["details"].append(detail)
        for error in event_result.get("errors", []):
            if len(result["errors"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["errors"].append(error)

    return result


def _referenced_segment_trigger_ids(
    db: DB,
    cid: str,
    segment_id: str | None = None,
) -> List[str]:
    if segment_id:
        db.set_cid(cid)
        if db.segments.get(segment_id) is None:
            raise falcon.HTTPBadRequest(
                title="Segment not found",
                description="Segment trigger baselines require a segment from this account.",
            )

    segment_ids = set()
    for automation in json_iter(
        db.execute(
            """
            select id, cid, data
            from automations
            where cid = %s
                and data->>'status' in ('published', 'paused')
                and data->'published' is not null
            order by data->>'name', id
            """,
            cid,
        )
    ):
        published = automation.get("published") or {}
        for trigger in _entry_triggers(published.get("entry") or {"type": "manual"}):
            if trigger.get("type") not in SEGMENT_TRIGGER_EVENT_TYPES:
                continue
            trigger_segment_id = (trigger.get("segment_id") or "").strip()
            if not trigger_segment_id:
                continue
            if segment_id and trigger_segment_id != segment_id:
                continue
            segment_ids.add(trigger_segment_id)

    return sorted(segment_ids)


def _claim_segment_trigger_baseline_snapshot(
    db: DB,
    cid: str,
    segment_id: str,
    claim_token: str,
    now_dt: datetime,
    mode: str = "baseline",
) -> JsonObj | None:
    now = now_dt.isoformat() + "Z"
    stale_before = now_dt - CLAIM_STALE_AFTER
    snapshot_id = "%s:%s" % (cid, segment_id)
    claim_status = "diffing" if mode == "diff" else "baselining"
    with db.transaction():
        db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, data)
            values (%s, %s, %s, 'idle', 1, null, %s)
            on conflict (cid, segment_id) do nothing
            """,
            snapshot_id,
            cid,
            segment_id,
            {
                "baseline_complete": False,
                "hashlimit_initialized": False,
                "errors": [],
            },
        )
        row = db.row(
            """
            select id, cid, segment_id, status, hashlimit, last_hashval, claimed_at, data
            from automation_segment_trigger_snapshots
            where cid = %s and segment_id = %s
            for update
            """,
            cid,
            segment_id,
        )
        if row is None:
            return None

        _, _, _, status, _, _, claimed_at, data = row
        if claimed_at is not None and getattr(claimed_at, "tzinfo", None) is not None:
            claimed_at = claimed_at.astimezone(tzutc()).replace(tzinfo=None)
        if status in ("baselining", "diffing") and claimed_at is not None and claimed_at >= stale_before:
            return None

        data = data or {}
        reset_progress = mode == "baseline" and status != "baselining" and data.get("baseline_complete") is True
        recovered = status in ("baselining", "diffing")
        updated = db.row(
            """
            update automation_segment_trigger_snapshots
            set status = %s,
                claim_token = %s,
                claimed_at = %s,
                last_started_at = %s,
                last_hashval = case when %s then null else last_hashval end,
                data = data || jsonb_build_object(
                    'last_claimed_at', %s,
                    'recovered_claim', %s,
                    'last_claim_mode', %s
                )
            where cid = %s and segment_id = %s
            returning id, cid, segment_id, status, hashlimit, last_hashval, claimed_at, data
            """,
            claim_status,
            claim_token,
            now_dt,
            now_dt,
            reset_progress,
            now,
            recovered,
            mode,
            cid,
            segment_id,
        )
        if updated is None:
            return None

    snapshot_id, row_cid, row_segment_id, status, hashlimit, last_hashval, claimed_at, data = updated
    return {
        "id": snapshot_id,
        "cid": row_cid,
        "segment_id": row_segment_id,
        "status": status,
        "hashlimit": hashlimit,
        "last_hashval": last_hashval,
        "claimed_at": claimed_at.isoformat() if hasattr(claimed_at, "isoformat") else claimed_at,
        "data": data or {},
        "claim_token": claim_token,
    }


def _release_segment_trigger_baseline_snapshot(
    db: DB,
    cid: str,
    segment_id: str,
    claim_token: str,
    status: str,
    hashlimit: int,
    last_hashval: int | None,
    data_patch: JsonObj,
) -> bool:
    updated = db.row(
        """
        update automation_segment_trigger_snapshots
        set status = %s,
            hashlimit = %s,
            last_hashval = %s,
            last_completed_at = case when %s = 'completed' then now() at time zone 'utc' else last_completed_at end,
            claimed_at = null,
            claim_token = null,
            data = data || %s
        where cid = %s and segment_id = %s and claim_token = %s
        returning id
        """,
        status,
        hashlimit,
        last_hashval,
        status,
        data_patch,
        cid,
        segment_id,
        claim_token,
    )
    return updated is not None


def _evaluate_segment_bucket_contacts(
    db: DB,
    cid: str,
    segment: JsonObj,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
) -> List[tuple[int, str]]:
    segments: Dict[str, JsonObj | None] = {}
    segment_get_segments(db, segment["parts"], segments)
    sentrows = get_segment_sentrows(db, cid, campaignids, hashval, hashlimit)
    rows = get_segment_rows(db, cid, hashval, listfactors, hashlimit)

    cache = Cache()
    segcounts: Dict[str, int] = {}
    numrows = len(rows)
    emails = []
    for row in rows:
        if segment_eval_parts(
            segment["parts"],
            segment["operator"],
            row,
            segcounts,
            numrows,
            segments,
            sentrows,
            segment,
            hashlimit,
            cache,
        ):
            emails.append(row["Email"][0])

    if not emails:
        return []

    return [
        (contact_id, contact_email)
        for contact_id, contact_email in db.execute(
            f"""
            select contact_id, email
            from contacts."contacts_{cid}"
            where email = any(%s)
                and ({hashlimit} = 1 or mod(contact_id, {hashlimit}) = %s)
            order by contact_id
            """,
            emails,
            hashval,
        )
    ]


def _store_segment_baseline_bucket_members(
    db: DB,
    cid: str,
    segment_id: str,
    bucket: int,
    contacts_for_bucket: List[tuple[int, str]],
    scan_id: str,
) -> JsonObj:
    now_dt = datetime.utcnow()
    contact_ids = [contact_id for contact_id, _ in contacts_for_bucket]
    if contact_ids:
        deleted = db.execute(
            """
            delete from automation_segment_trigger_members
            where cid = %s and segment_id = %s and bucket = %s and not (contact_id = any(%s))
            """,
            cid,
            segment_id,
            bucket,
            contact_ids,
        ).rowcount
    else:
        deleted = db.execute(
            """
            delete from automation_segment_trigger_members
            where cid = %s and segment_id = %s and bucket = %s
            """,
            cid,
            segment_id,
            bucket,
        ).rowcount

    for contact_id, contact_email in contacts_for_bucket:
        db.execute(
            """
            insert into automation_segment_trigger_members
                (cid, segment_id, contact_id, contact_email, bucket, first_seen_at, last_seen_at, scan_id)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (cid, segment_id, contact_id)
            do update set
                contact_email = excluded.contact_email,
                bucket = excluded.bucket,
                last_seen_at = excluded.last_seen_at,
                scan_id = excluded.scan_id
            """,
            cid,
            segment_id,
            contact_id,
            contact_email,
            bucket,
            now_dt,
            now_dt,
            scan_id,
        )

    return {
        "members_seen": len(contacts_for_bucket),
        "members_removed": max(0, deleted or 0),
    }


def _segment_trigger_event_types_for_segment(db: DB, cid: str, segment_id: str) -> set[str]:
    event_types: set[str] = set()
    for automation in json_iter(
        db.execute(
            """
            select id, cid, data
            from automations
            where cid = %s
                and data->>'status' in ('published', 'paused')
                and data->'published' is not null
            """,
            cid,
        )
    ):
        published = automation.get("published") or {}
        for trigger in _entry_triggers(published.get("entry") or {"type": "manual"}):
            trigger_type = trigger.get("type")
            if trigger_type in SEGMENT_TRIGGER_EVENT_TYPES and (trigger.get("segment_id") or "").strip() == segment_id:
                event_types.add(trigger_type)
    return event_types


def _store_segment_diff_bucket(
    db: DB,
    cid: str,
    segment_id: str,
    bucket: int,
    contacts_for_bucket: List[tuple[int, str]],
    watched_event_types: set[str],
    scan_id: str,
    hashlimit: int,
    remaining_events: int,
) -> JsonObj:
    current = {contact_id: contact_email for contact_id, contact_email in contacts_for_bucket}
    previous = {
        contact_id: contact_email
        for contact_id, contact_email in db.execute(
            """
            select contact_id, contact_email
            from automation_segment_trigger_members
            where cid = %s and segment_id = %s and bucket = %s
            """,
            cid,
            segment_id,
            bucket,
        )
    }

    entered = sorted(set(current.keys()) - set(previous.keys()))
    left = sorted(set(previous.keys()) - set(current.keys()))
    entered_to_emit = entered if "segment_entered" in watched_event_types else []
    left_to_emit = left if "segment_left" in watched_event_types else []
    events_needed = len(entered_to_emit) + len(left_to_emit)
    if events_needed > remaining_events:
        return {
            "processed": False,
            "event_limit_reached": True,
            "events_needed": events_needed,
            "events_created": 0,
            "members_seen": len(current),
            "members_removed": 0,
            "entered": len(entered_to_emit),
            "left": len(left_to_emit),
        }

    now_dt = datetime.utcnow()
    source = {
        "type": "automation_segment_scanner",
        "mode": "diff",
        "segment_id": segment_id,
        "scan_id": scan_id,
        "bucket": bucket,
        "hashlimit": hashlimit,
    }
    with db.transaction():
        for contact_id in entered_to_emit:
            _create_automation_trigger_event(
                db,
                cid,
                "segment_entered",
                current[contact_id],
                segment_id=segment_id,
                source=source,
                correlation_id=shortuuid.uuid(),
                depth=0,
            )
        for contact_id in left_to_emit:
            _create_automation_trigger_event(
                db,
                cid,
                "segment_left",
                previous[contact_id],
                segment_id=segment_id,
                source=source,
                correlation_id=shortuuid.uuid(),
                depth=0,
            )

        if current:
            db.execute(
                """
                delete from automation_segment_trigger_members
                where cid = %s and segment_id = %s and bucket = %s and not (contact_id = any(%s))
                """,
                cid,
                segment_id,
                bucket,
                list(current.keys()),
            )
        else:
            db.execute(
                """
                delete from automation_segment_trigger_members
                where cid = %s and segment_id = %s and bucket = %s
                """,
                cid,
                segment_id,
                bucket,
            )

        for contact_id, contact_email in contacts_for_bucket:
            db.execute(
                """
                insert into automation_segment_trigger_members
                    (cid, segment_id, contact_id, contact_email, bucket, first_seen_at, last_seen_at, scan_id)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (cid, segment_id, contact_id)
                do update set
                    contact_email = excluded.contact_email,
                    bucket = excluded.bucket,
                    last_seen_at = excluded.last_seen_at,
                    scan_id = excluded.scan_id
                """,
                cid,
                segment_id,
                contact_id,
                contact_email,
                bucket,
                now_dt,
                now_dt,
                scan_id,
            )

    return {
        "processed": True,
        "event_limit_reached": False,
        "events_created": events_needed,
        "segment_entered_events_created": len(entered_to_emit),
        "segment_left_events_created": len(left_to_emit),
        "members_seen": len(current),
        "members_removed": len(left),
    }


def _baseline_automation_segment_triggers(
    db: DB,
    cid: str,
    segment_id: str | None = None,
    limit_segments: int = AUTOMATION_SEGMENT_BASELINE_DEFAULT_SEGMENT_LIMIT,
    limit_buckets: int = AUTOMATION_SEGMENT_BASELINE_DEFAULT_BUCKET_LIMIT,
) -> JsonObj:
    if not _automation_segment_trigger_baseline_enabled():
        return {
            "enabled": False,
            "segments_seen": 0,
            "segments_claimed": 0,
            "buckets_processed": 0,
            "members_upserted": 0,
            "members_removed": 0,
            "events_created": 0,
            "skipped": [],
            "errors": [],
        }

    result: JsonObj = {
        "enabled": True,
        "segments_seen": 0,
        "segments_claimed": 0,
        "buckets_processed": 0,
        "members_upserted": 0,
        "members_removed": 0,
        "events_created": 0,
        "skipped": [],
        "errors": [],
    }
    referenced_segment_ids = _referenced_segment_trigger_ids(db, cid, segment_id)
    result["segments_seen"] = len(referenced_segment_ids)

    for referenced_segment_id in referenced_segment_ids[:limit_segments]:
        if result["buckets_processed"] >= limit_buckets:
            break

        claim_token = shortuuid.uuid()
        snapshot = _claim_segment_trigger_baseline_snapshot(
            db,
            cid,
            referenced_segment_id,
            claim_token,
            datetime.utcnow(),
        )
        if snapshot is None:
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "already_baselining",
                })
            continue

        result["segments_claimed"] += 1
        segment = db.segments.get(referenced_segment_id)
        if segment is None:
            _release_segment_trigger_baseline_snapshot(
                db,
                cid,
                referenced_segment_id,
                claim_token,
                "skipped_invalid",
                int(snapshot.get("hashlimit") or 1),
                snapshot.get("last_hashval"),
                {
                    "baseline_complete": False,
                    "last_error": "Segment not found.",
                    "updated": _utc_now(),
                },
            )
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "segment_not_found",
                })
            continue

        try:
            if not segment.get("parts"):
                raise ValueError("No rules in segment")
            nested_segments: Dict[str, JsonObj | None] = {}
            segment_get_segments(db, segment["parts"], nested_segments)
            campaignids = segment_get_campaignids(segment, list(nested_segments.values()))
            hashlimit, listfactors = segment_get_params(db, cid, segment)
        except Exception as e:
            _release_segment_trigger_baseline_snapshot(
                db,
                cid,
                referenced_segment_id,
                claim_token,
                "skipped_invalid",
                int(snapshot.get("hashlimit") or 1),
                snapshot.get("last_hashval"),
                {
                    "baseline_complete": False,
                    "last_error": str(e)[:512],
                    "updated": _utc_now(),
                },
            )
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "invalid_segment",
                    "description": str(e)[:256],
                })
            continue

        snapshot_data = snapshot.get("data") or {}
        stored_hashlimit = int(snapshot.get("hashlimit") or 1)
        last_hashval = snapshot.get("last_hashval")
        if snapshot_data.get("hashlimit_initialized") and stored_hashlimit != hashlimit:
            db.execute(
                """
                delete from automation_segment_trigger_members
                where cid = %s and segment_id = %s
                """,
                cid,
                referenced_segment_id,
            )
            last_hashval = None
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "hashlimit_changed_rebaseline",
                    "previous_hashlimit": stored_hashlimit,
                    "hashlimit": hashlimit,
                })

        start_bucket = 0 if last_hashval is None else int(last_hashval) + 1
        scan_id = shortuuid.uuid()
        current_bucket = start_bucket
        segment_buckets_processed = 0
        try:
            while current_bucket < hashlimit and result["buckets_processed"] < limit_buckets:
                bucket_contacts = _evaluate_segment_bucket_contacts(
                    db,
                    cid,
                    segment,
                    current_bucket,
                    listfactors,
                    hashlimit,
                    campaignids,
                )
                bucket_result = _store_segment_baseline_bucket_members(
                    db,
                    cid,
                    referenced_segment_id,
                    current_bucket,
                    bucket_contacts,
                    scan_id,
                )
                result["members_upserted"] += bucket_result["members_seen"]
                result["members_removed"] += bucket_result["members_removed"]
                result["buckets_processed"] += 1
                segment_buckets_processed += 1
                last_hashval = current_bucket
                current_bucket += 1
        except Exception as e:
            _release_segment_trigger_baseline_snapshot(
                db,
                cid,
                referenced_segment_id,
                claim_token,
                "idle",
                hashlimit,
                last_hashval,
                {
                    "baseline_complete": False,
                    "hashlimit_initialized": True,
                    "last_error": str(e)[:512],
                    "updated": _utc_now(),
                },
            )
            if len(result["errors"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["errors"].append({
                    "segment_id": referenced_segment_id,
                    "description": str(e)[:256],
                })
            continue

        complete = current_bucket >= hashlimit
        _release_segment_trigger_baseline_snapshot(
            db,
            cid,
            referenced_segment_id,
            claim_token,
            "completed" if complete else "idle",
            hashlimit,
            None if complete else last_hashval,
            {
                "baseline_complete": complete,
                "hashlimit_initialized": True,
                "last_scan_id": scan_id,
                "last_bucket_processed": last_hashval,
                "buckets_processed_last_call": segment_buckets_processed,
                "updated": _utc_now(),
                "last_error": None,
            },
        )

    return result


def _diff_automation_segment_triggers(
    db: DB,
    cid: str,
    segment_id: str | None = None,
    limit_segments: int = AUTOMATION_SEGMENT_BASELINE_DEFAULT_SEGMENT_LIMIT,
    limit_buckets: int = AUTOMATION_SEGMENT_BASELINE_DEFAULT_BUCKET_LIMIT,
    limit_events: int = AUTOMATION_SEGMENT_DIFF_DEFAULT_EVENT_LIMIT,
) -> JsonObj:
    if not _automation_segment_trigger_diff_enabled():
        return {
            "enabled": False,
            "mode": "diff",
            "segments_seen": 0,
            "segments_claimed": 0,
            "buckets_processed": 0,
            "members_upserted": 0,
            "members_removed": 0,
            "events_created": 0,
            "segment_entered_events_created": 0,
            "segment_left_events_created": 0,
            "event_limit_reached": False,
            "skipped": [],
            "errors": [],
        }

    result: JsonObj = {
        "enabled": True,
        "mode": "diff",
        "segments_seen": 0,
        "segments_claimed": 0,
        "buckets_processed": 0,
        "members_upserted": 0,
        "members_removed": 0,
        "events_created": 0,
        "segment_entered_events_created": 0,
        "segment_left_events_created": 0,
        "event_limit_reached": False,
        "skipped": [],
        "errors": [],
    }
    referenced_segment_ids = _referenced_segment_trigger_ids(db, cid, segment_id)
    result["segments_seen"] = len(referenced_segment_ids)

    for referenced_segment_id in referenced_segment_ids[:limit_segments]:
        if result["buckets_processed"] >= limit_buckets or result["event_limit_reached"]:
            break

        existing_snapshot = db.row(
            """
            select status, hashlimit, last_hashval, data
            from automation_segment_trigger_snapshots
            where cid = %s and segment_id = %s
            """,
            cid,
            referenced_segment_id,
        )
        if existing_snapshot is None:
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "baseline_required",
                })
            continue
        _, _, _, existing_data = existing_snapshot
        existing_data = existing_data or {}
        if existing_data.get("baseline_complete") is not True:
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "baseline_incomplete",
                })
            continue

        watched_event_types = _segment_trigger_event_types_for_segment(db, cid, referenced_segment_id)
        if not watched_event_types:
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "no_matching_segment_trigger",
                })
            continue

        claim_token = shortuuid.uuid()
        snapshot = _claim_segment_trigger_baseline_snapshot(
            db,
            cid,
            referenced_segment_id,
            claim_token,
            datetime.utcnow(),
            mode="diff",
        )
        if snapshot is None:
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "already_diffing",
                })
            continue

        result["segments_claimed"] += 1
        segment = db.segments.get(referenced_segment_id)
        if segment is None:
            _release_segment_trigger_baseline_snapshot(
                db,
                cid,
                referenced_segment_id,
                claim_token,
                "skipped_invalid",
                int(snapshot.get("hashlimit") or 1),
                snapshot.get("last_hashval"),
                {
                    "baseline_complete": False,
                    "last_error": "Segment not found.",
                    "updated": _utc_now(),
                },
            )
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "segment_not_found",
                })
            continue

        try:
            if not segment.get("parts"):
                raise ValueError("No rules in segment")
            nested_segments: Dict[str, JsonObj | None] = {}
            segment_get_segments(db, segment["parts"], nested_segments)
            campaignids = segment_get_campaignids(segment, list(nested_segments.values()))
            hashlimit, listfactors = segment_get_params(db, cid, segment)
        except Exception as e:
            _release_segment_trigger_baseline_snapshot(
                db,
                cid,
                referenced_segment_id,
                claim_token,
                "skipped_invalid",
                int(snapshot.get("hashlimit") or 1),
                snapshot.get("last_hashval"),
                {
                    "baseline_complete": False,
                    "last_error": str(e)[:512],
                    "updated": _utc_now(),
                },
            )
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "invalid_segment",
                    "description": str(e)[:256],
                })
            continue

        snapshot_data = snapshot.get("data") or {}
        stored_hashlimit = int(snapshot.get("hashlimit") or 1)
        last_hashval = snapshot.get("last_hashval")
        if snapshot_data.get("hashlimit_initialized") and stored_hashlimit != hashlimit:
            with db.transaction():
                db.execute(
                    """
                    delete from automation_segment_trigger_members
                    where cid = %s and segment_id = %s
                    """,
                    cid,
                    referenced_segment_id,
                )
            _release_segment_trigger_baseline_snapshot(
                db,
                cid,
                referenced_segment_id,
                claim_token,
                "idle",
                hashlimit,
                None,
                {
                    "baseline_complete": False,
                    "hashlimit_initialized": True,
                    "last_error": None,
                    "updated": _utc_now(),
                    "hashlimit_changed_rebaseline_required": True,
                    "previous_hashlimit": stored_hashlimit,
                    "hashlimit": hashlimit,
                },
            )
            if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["skipped"].append({
                    "segment_id": referenced_segment_id,
                    "reason": "hashlimit_changed_rebaseline_required",
                    "previous_hashlimit": stored_hashlimit,
                    "hashlimit": hashlimit,
                })
            continue

        start_bucket = 0 if last_hashval is None else int(last_hashval) + 1
        scan_id = shortuuid.uuid()
        current_bucket = start_bucket
        segment_buckets_processed = 0
        try:
            while current_bucket < hashlimit and result["buckets_processed"] < limit_buckets:
                remaining_events = limit_events - int(result["events_created"])
                bucket_contacts = _evaluate_segment_bucket_contacts(
                    db,
                    cid,
                    segment,
                    current_bucket,
                    listfactors,
                    hashlimit,
                    campaignids,
                )
                bucket_result = _store_segment_diff_bucket(
                    db,
                    cid,
                    referenced_segment_id,
                    current_bucket,
                    bucket_contacts,
                    watched_event_types,
                    scan_id,
                    hashlimit,
                    remaining_events,
                )
                if bucket_result.get("event_limit_reached"):
                    result["event_limit_reached"] = True
                    if len(result["skipped"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                        result["skipped"].append({
                            "segment_id": referenced_segment_id,
                            "bucket": current_bucket,
                            "reason": "event_limit_reached",
                            "events_needed": bucket_result.get("events_needed"),
                            "remaining_events": remaining_events,
                        })
                    break

                result["events_created"] += bucket_result["events_created"]
                result["segment_entered_events_created"] += bucket_result.get("segment_entered_events_created", 0)
                result["segment_left_events_created"] += bucket_result.get("segment_left_events_created", 0)
                result["members_upserted"] += bucket_result["members_seen"]
                result["members_removed"] += bucket_result["members_removed"]
                result["buckets_processed"] += 1
                segment_buckets_processed += 1
                last_hashval = current_bucket
                current_bucket += 1
        except Exception as e:
            _release_segment_trigger_baseline_snapshot(
                db,
                cid,
                referenced_segment_id,
                claim_token,
                "idle",
                hashlimit,
                last_hashval,
                {
                    "baseline_complete": True,
                    "hashlimit_initialized": True,
                    "last_error": str(e)[:512],
                    "updated": _utc_now(),
                },
            )
            if len(result["errors"]) < AUTOMATION_TRIGGER_DETAIL_LIMIT:
                result["errors"].append({
                    "segment_id": referenced_segment_id,
                    "description": str(e)[:256],
                })
            continue

        complete = current_bucket >= hashlimit
        _release_segment_trigger_baseline_snapshot(
            db,
            cid,
            referenced_segment_id,
            claim_token,
            "completed" if complete else "idle",
            hashlimit,
            None if complete else last_hashval,
            {
                "baseline_complete": True,
                "hashlimit_initialized": True,
                "last_diff_scan_id": scan_id,
                "last_diff_bucket_processed": last_hashval,
                "diff_buckets_processed_last_call": segment_buckets_processed,
                "last_diff_completed": complete,
                "updated": _utc_now(),
                "last_error": None,
            },
        )

    return result


def _segment_trigger_scan_result_summary(result: JsonObj) -> JsonObj:
    return {
        key: result.get(key)
        for key in (
            "enabled",
            "mode",
            "segments_seen",
            "segments_claimed",
            "buckets_processed",
            "members_upserted",
            "members_removed",
            "events_created",
            "segment_entered_events_created",
            "segment_left_events_created",
            "event_limit_reached",
        )
        if key in result
    }


@tasks.task(priority=HIGH_PRIORITY)
def process_automation_segment_triggers_task(
    cid: str,
    mode: str = "baseline",
    segment_id: str | None = None,
    limit_segments: int | None = None,
    limit_buckets: int | None = None,
    limit_events: int | None = None,
) -> JsonObj:
    mode = (mode or "baseline").strip().lower()
    if mode not in ("baseline", "diff"):
        result = {
            "enabled": False,
            "mode": mode,
            "segments_seen": 0,
            "segments_claimed": 0,
            "buckets_processed": 0,
            "members_upserted": 0,
            "members_removed": 0,
            "events_created": 0,
            "skipped": [],
            "errors": [{
                "title": "Invalid automation segment trigger scan mode",
                "description": "mode must be baseline or diff.",
            }],
        }
        log.info("Skipped automation segment trigger scan cid=%s mode=%s result=%s", cid, mode, _segment_trigger_scan_result_summary(result))
        return result

    with open_db() as db:
        if not cid or db.single("select id from companies where id = %s", cid) is None:
            result = {
                "enabled": False,
                "mode": mode,
                "segments_seen": 0,
                "segments_claimed": 0,
                "buckets_processed": 0,
                "members_upserted": 0,
                "members_removed": 0,
                "events_created": 0,
                "skipped": [],
                "errors": [{
                    "title": "Customer account not found",
                    "description": "Automation segment trigger scans require an existing customer account.",
                }],
            }
            log.info("Skipped automation segment trigger scan cid=%s mode=%s result=%s", cid, mode, _segment_trigger_scan_result_summary(result))
            return result

        db.set_cid(cid)
        normalized_limit_segments = _automation_segment_baseline_limit(
            limit_segments,
            AUTOMATION_SEGMENT_BASELINE_DEFAULT_SEGMENT_LIMIT,
            AUTOMATION_SEGMENT_BASELINE_MAX_SEGMENT_LIMIT,
            "limit_segments",
        )
        normalized_limit_buckets = _automation_segment_baseline_limit(
            limit_buckets,
            AUTOMATION_SEGMENT_BASELINE_DEFAULT_BUCKET_LIMIT,
            AUTOMATION_SEGMENT_BASELINE_MAX_BUCKET_LIMIT,
            "limit_buckets",
        )

        if mode == "diff":
            normalized_limit_events = _automation_segment_diff_event_limit(limit_events)
            result = _diff_automation_segment_triggers(
                db,
                cid,
                segment_id,
                normalized_limit_segments,
                normalized_limit_buckets,
                normalized_limit_events,
            )
        else:
            result = _baseline_automation_segment_triggers(
                db,
                cid,
                segment_id,
                normalized_limit_segments,
                normalized_limit_buckets,
            )

        log.info(
            "Processed automation segment trigger scan cid=%s mode=%s segment_id=%s limits=%s result=%s",
            cid,
            mode,
            segment_id,
            {
                "limit_segments": normalized_limit_segments,
                "limit_buckets": normalized_limit_buckets,
                "limit_events": _automation_segment_diff_event_limit(limit_events) if mode == "diff" else None,
            },
            _segment_trigger_scan_result_summary(result),
        )
        return result


def check_automation_segment_triggers() -> JsonObj:
    baseline_enabled = _automation_segment_trigger_baseline_enabled()
    diff_enabled = _automation_segment_trigger_diff_enabled()
    if not baseline_enabled and not diff_enabled:
        log.info("Automation segment trigger scanning is disabled; enable baseline or diff flags to dispatch scans.")
        return {
            "enabled": False,
            "locked": False,
            "baseline_enabled": False,
            "diff_enabled": False,
            "accounts_seen": 0,
            "dispatched": 0,
            "baseline_dispatched": 0,
            "diff_dispatched": 0,
            "task_ids": [],
        }

    account_limit = _automation_segment_scan_account_limit()
    limit_segments = AUTOMATION_SEGMENT_BASELINE_DEFAULT_SEGMENT_LIMIT
    limit_buckets = AUTOMATION_SEGMENT_BASELINE_DEFAULT_BUCKET_LIMIT
    limit_events = AUTOMATION_SEGMENT_DIFF_DEFAULT_EVENT_LIMIT
    task_ids: List[str | None] = []
    baseline_dispatched = 0
    diff_dispatched = 0

    with open_db() as db:
        with db.transaction():
            if not db.single(f"select pg_try_advisory_xact_lock({CHECK_AUTOMATION_SEGMENT_TRIGGERS_LOCK}::bigint)"):
                log.info("Automation segment trigger scanner scheduler is already running.")
                return {
                    "enabled": True,
                    "locked": True,
                    "baseline_enabled": baseline_enabled,
                    "diff_enabled": diff_enabled,
                    "accounts_seen": 0,
                    "dispatched": 0,
                    "baseline_dispatched": 0,
                    "diff_dispatched": 0,
                    "task_ids": [],
                    "account_limit": account_limit,
                    "limit_segments": limit_segments,
                    "limit_buckets": limit_buckets,
                    "limit_events": limit_events,
                }

            account_modes = _automation_segment_trigger_account_modes(
                db,
                account_limit,
                baseline_enabled,
                diff_enabled,
            )
            log.info(
                "Dispatching automation segment trigger scans for %s account(s), account_limit=%s, limits=%s.",
                len(account_modes),
                account_limit,
                {
                    "limit_segments": limit_segments,
                    "limit_buckets": limit_buckets,
                    "limit_events": limit_events,
                },
            )
            for cid, mode in account_modes:
                if mode == "baseline":
                    baseline_dispatched += 1
                elif mode == "diff":
                    diff_dispatched += 1
                task_ids.append(
                    run_task(
                        process_automation_segment_triggers_task,
                        cid,
                        mode,
                        None,
                        limit_segments,
                        limit_buckets,
                        limit_events,
                    )
                )

    return {
        "enabled": True,
        "locked": False,
        "baseline_enabled": baseline_enabled,
        "diff_enabled": diff_enabled,
        "accounts_seen": len(task_ids),
        "dispatched": len(task_ids),
        "baseline_dispatched": baseline_dispatched,
        "diff_dispatched": diff_dispatched,
        "task_ids": task_ids,
        "account_limit": account_limit,
        "limit_segments": limit_segments,
        "limit_buckets": limit_buckets,
        "limit_events": limit_events,
    }


def _eligible_automation_enrolments(
    db: DB,
    cid: str,
    limit: int,
    automation_id: str | None = None,
) -> List[JsonObj]:
    now = datetime.utcnow()
    params: List[object] = [cid, now, limit * 5]
    automation_filter = ""
    if automation_id:
        automation_filter = "and e.automation_id = %s"
        params = [cid, automation_id, now, limit * 5]

    candidates: List[JsonObj] = []
    for automation_id, enrolment_id, contact_email, status, retry_after in db.execute(
        f"""
        select e.automation_id, e.id, e.contact_email, e.data->>'status', e.data->>'retry_after'
            from automation_enrolments e
            join automations a on a.cid = e.cid and a.id = e.automation_id
            join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
            where e.cid = %s
                {automation_filter}
                and a.data->'published' is not null
                and coalesce(a.data->>'status', '') <> 'paused'
                and (e.data->>'subject_gate' is null or coalesce(e.data->>'retry_after','') <=
                    to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
                and (
                    e.data->>'status' = 'ready'
                    or (
                        e.data->>'status' = 'waiting'
                        and nullif(e.data->>'wake_at', '')::timestamptz <= %s
                    )
                )
            order by
                coalesce(
                    nullif(e.data->>'modified', '')::timestamptz,
                    nullif(e.data->>'created', '')::timestamptz
                ),
                e.id
            limit %s
            """,
        *params,
    ):
        if _retry_after_blocks_processing(retry_after, now):
            continue
        candidates.append(
            {
                "automation_id": automation_id,
                "enrolment_id": enrolment_id,
                "contact_email": contact_email,
                "status": status,
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def _running_automation_enrolment_count(
    db: DB,
    cid: str,
    automation_id: str | None = None,
) -> int:
    params: List[object] = [cid]
    automation_filter = ""
    if automation_id:
        automation_filter = "and e.automation_id = %s"
        params.append(automation_id)

    return int(
        db.single(
            f"""
            select count(*)
            from automation_enrolments e
            join automations a on a.cid = e.cid and a.id = e.automation_id
            join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
            where e.cid = %s
                {automation_filter}
                and a.data->'published' is not null
                and coalesce(a.data->>'status', '') <> 'paused'
                and e.data->>'status' = 'running'
            """,
            *params,
        )
        or 0
    )


def _automation_processing_account_ids(
    db: DB,
    account_limit: int,
) -> List[str]:
    now = datetime.utcnow()
    cids: List[str] = []
    for cid, retry_after in db.execute(
        """
            select e.cid, e.data->>'retry_after'
            from automation_enrolments e
            join automations a on a.cid = e.cid and a.id = e.automation_id
            join companies c on c.id = e.cid
            where c.data @> %s
                and c.data->>'automation_processing_enabled' = 'true'
                and a.data->'published' is not null
                and coalesce(a.data->>'status', '') <> 'paused'
                and (e.data->>'subject_gate' is null or coalesce(e.data->>'retry_after','') <=
                    to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
                and (
                    e.data->>'status' = 'ready'
                    or (
                        e.data->>'status' = 'waiting'
                        and nullif(e.data->>'wake_at', '')::timestamptz <= %s
                    )
                )
            order by
                coalesce(
                    nullif(e.data->>'modified', '')::timestamptz,
                    nullif(e.data->>'created', '')::timestamptz
                ),
                e.cid
            limit %s
            """,
        {"admin": False},
        now,
        account_limit * 5,
    ):
        if cid in cids or _retry_after_blocks_processing(retry_after, now):
            continue
        cids.append(cid)
        if len(cids) >= account_limit:
            break
    return cids


def _automation_segment_trigger_account_modes(
    db: DB,
    account_limit: int,
    baseline_enabled: bool,
    diff_enabled: bool,
) -> List[tuple[str, str]]:
    if not baseline_enabled and not diff_enabled:
        return []

    trigger_sql = """
        select a.cid, trigger->>'segment_id' as segment_id
        from automations a
        cross join lateral (
            select data->'published'->'entry' as trigger
            where data->'published'->'entry'->>'type' in ('segment_entered', 'segment_left')
            union all
            select trigger
            from jsonb_array_elements(coalesce(data->'published'->'entry'->'triggers', '[]'::jsonb)) trigger
            where data->'published'->'entry'->>'type' = 'multi'
                and trigger->>'type' in ('segment_entered', 'segment_left')
        ) segment_triggers
        join companies c on c.id = a.cid
        where c.data @> %s
            and c.data->>'automation_processing_enabled' = 'true'
            and a.data->>'status' in ('published', 'paused')
            and a.data->'published' is not null
            and trigger->>'segment_id' is not null
            and trigger->>'segment_id' <> ''
    """

    rows = db.execute(
        """
        with referenced as (
            {trigger_sql}
        ), segment_status as (
            select
                r.cid,
                r.segment_id,
                s.data as snapshot_data
            from referenced r
            left join automation_segment_trigger_snapshots s
                on s.cid = r.cid and s.segment_id = r.segment_id
            group by r.cid, r.segment_id, s.data
        ), account_flags as (
            select
                cid,
                bool_or(snapshot_data is null or snapshot_data->>'baseline_complete' <> 'true') as baseline_needed,
                bool_or(snapshot_data->>'baseline_complete' = 'true') as diff_ready
            from segment_status
            group by cid
        )
        select cid,
            case
                when %s and baseline_needed then 'baseline'
                when %s and diff_ready then 'diff'
                else null
            end as mode
        from account_flags
        where (
            (%s and baseline_needed)
            or (%s and diff_ready)
        )
        order by cid
        limit %s
        """.format(trigger_sql=trigger_sql),
        {"admin": False},
        baseline_enabled,
        diff_enabled,
        baseline_enabled,
        diff_enabled,
        account_limit,
    )
    return [(cid, mode) for cid, mode in rows if mode in ("baseline", "diff")]


def _automation_retention_cleanup_enabled() -> bool:
    return _env_enabled("automation_retention_cleanup_enabled")


def _automation_retention_debug_cutoff() -> datetime:
    days = _env_positive_int(
        "automation_retention_debug_email_log_days",
        AUTOMATION_RETENTION_DEBUG_LOG_DAYS,
    )
    return datetime.utcnow() - timedelta(days=days)


def _automation_retention_trigger_cutoff() -> datetime:
    days = _env_positive_int(
        "automation_retention_trigger_event_days",
        AUTOMATION_RETENTION_TRIGGER_EVENT_DAYS,
    )
    return datetime.utcnow() - timedelta(days=days)


def _automation_retention_delete_limit() -> int:
    return _env_positive_int(
        "automation_retention_delete_limit",
        AUTOMATION_RETENTION_DELETE_LIMIT,
    )


def _automation_retention_account_limit() -> int:
    return _env_positive_int(
        "automation_retention_account_limit",
        AUTOMATION_RETENTION_ACCOUNT_LIMIT,
    )


def _automation_retention_account_ids(
    db: DB,
    debug_cutoff: datetime,
    trigger_cutoff: datetime,
    account_limit: int,
) -> List[str]:
    return [
        row[0]
        for row in db.execute(
            """
            select cid
            from (
                select cid, min(ts) as oldest_ts
                from debug_email_logs
                where ts < %s
                group by cid
                union all
                select cid, min(ts) as oldest_ts
                from automation_trigger_events
                where ts < %s
                    and data->>'status' = any(%s)
                group by cid
            ) candidates
            group by cid
            order by min(oldest_ts), cid
            limit %s
            """,
            debug_cutoff,
            trigger_cutoff,
            list(AUTOMATION_TRIGGER_FINISHED_STATUSES),
            account_limit,
        )
    ]


def _cleanup_debug_email_logs_for_account(
    db: DB,
    cid: str,
    cutoff: datetime,
    limit: int,
) -> int:
    return int(
        db.single(
            """
            with doomed as (
                select id
                from debug_email_logs
                where cid = %s and ts < %s
                order by ts, id
                limit %s
            ),
            deleted as (
                delete from debug_email_logs l
                using doomed
                where l.id = doomed.id and l.cid = %s
                returning l.id
            )
            select count(*) from deleted
            """,
            cid,
            cutoff,
            limit,
            cid,
        )
        or 0
    )


def _cleanup_automation_trigger_events_for_account(
    db: DB,
    cid: str,
    cutoff: datetime,
    limit: int,
) -> int:
    return int(
        db.single(
            """
            with doomed as (
                select id
                from automation_trigger_events
                where cid = %s
                    and ts < %s
                    and data->>'status' = any(%s)
                    and coalesce(data->>'exit_status', '') <> 'pending'
                order by ts, id
                limit %s
            ),
            deleted as (
                delete from automation_trigger_events e
                using doomed
                where e.id = doomed.id and e.cid = %s
                returning e.id
            )
            select count(*) from deleted
            """,
            cid,
            cutoff,
            list(AUTOMATION_TRIGGER_FINISHED_STATUSES),
            limit,
            cid,
        )
        or 0
    )


def _cleanup_automation_retention_for_account(
    db: DB,
    cid: str,
    debug_cutoff: datetime,
    trigger_cutoff: datetime,
    delete_limit: int,
) -> JsonObj:
    debug_deleted = _cleanup_debug_email_logs_for_account(db, cid, debug_cutoff, delete_limit)
    trigger_deleted = _cleanup_automation_trigger_events_for_account(db, cid, trigger_cutoff, delete_limit)
    return {
        "cid": cid,
        "debug_email_logs_deleted": debug_deleted,
        "automation_trigger_events_deleted": trigger_deleted,
        "deleted": debug_deleted + trigger_deleted,
    }


def check_automation_retention_cleanup() -> JsonObj:
    if not _automation_retention_cleanup_enabled():
        log.info("Automation retention cleanup is disabled; set automation_retention_cleanup_enabled=true to enable it.")
        return {
            "enabled": False,
            "locked": False,
            "accounts": 0,
            "debug_email_logs_deleted": 0,
            "automation_trigger_events_deleted": 0,
            "deleted": 0,
            "account_results": [],
        }

    debug_cutoff = _automation_retention_debug_cutoff()
    trigger_cutoff = _automation_retention_trigger_cutoff()
    account_limit = _automation_retention_account_limit()
    delete_limit = _automation_retention_delete_limit()
    account_results: List[JsonObj] = []

    with open_db() as db:
        with db.transaction():
            if not db.single(f"select pg_try_advisory_xact_lock({AUTOMATION_RETENTION_CLEANUP_LOCK})"):
                log.info("Automation retention cleanup is already running.")
                return {
                    "enabled": True,
                    "locked": True,
                    "accounts": 0,
                    "debug_email_logs_deleted": 0,
                    "automation_trigger_events_deleted": 0,
                    "deleted": 0,
                    "account_results": [],
                }

            cids = _automation_retention_account_ids(db, debug_cutoff, trigger_cutoff, account_limit)
            for cid in cids:
                account_results.append(
                    _cleanup_automation_retention_for_account(
                        db,
                        cid,
                        debug_cutoff,
                        trigger_cutoff,
                        delete_limit,
                    )
                )

    debug_deleted = sum(int(row["debug_email_logs_deleted"]) for row in account_results)
    trigger_deleted = sum(int(row["automation_trigger_events_deleted"]) for row in account_results)
    result = {
        "enabled": True,
        "locked": False,
        "accounts": len(account_results),
        "debug_email_logs_deleted": debug_deleted,
        "automation_trigger_events_deleted": trigger_deleted,
        "deleted": debug_deleted + trigger_deleted,
        "account_results": account_results,
    }
    log.info("Automation retention cleanup completed: %s", result)
    return result


def _process_eligible_automation_enrolments(
    db: DB,
    cid: str,
    limit: int,
    automation_id: str | None = None,
) -> JsonObj:
    result: JsonObj = {
        "processed": 0,
        "succeeded": 0,
        "waiting": 0,
        "completed": 0,
        "exited": 0,
        "failed": 0,
        "skipped_running": _running_automation_enrolment_count(db, cid, automation_id),
        "errors": [],
    }

    for candidate in _eligible_automation_enrolments(db, cid, limit, automation_id):
        result["processed"] += 1
        try:
            run_result = _run_next_automation_enrolment(
                db,
                cid,
                candidate["automation_id"],
                candidate["enrolment_id"],
                False,
            )
        except falcon.HTTPBadRequest as e:
            if e.title == "Automation enrolment is already running":
                result["skipped_running"] += 1
                continue
            result["failed"] += 1
            if len(result["errors"]) < AUTOMATION_PROCESS_ERROR_LIMIT:
                result["errors"].append(
                    {
                        "automation_id": candidate["automation_id"],
                        "enrolment_id": candidate["enrolment_id"],
                        "contact_email": candidate["contact_email"],
                        "title": e.title,
                        "description": e.description,
                    }
                )
            continue
        except falcon.HTTPError as e:
            result["failed"] += 1
            if len(result["errors"]) < AUTOMATION_PROCESS_ERROR_LIMIT:
                result["errors"].append(
                    {
                        "automation_id": candidate["automation_id"],
                        "enrolment_id": candidate["enrolment_id"],
                        "contact_email": candidate["contact_email"],
                        "title": e.title,
                        "description": e.description,
                    }
                )
            continue

        result["succeeded"] += 1
        status = (run_result.get("enrolment") or {}).get("status")
        if status == "waiting":
            result["waiting"] += 1
        elif status == "completed":
            result["completed"] += 1
        elif status == "exited":
            result["exited"] += 1

    return result


def _process_automation_budget(db: DB, cid: str, limit: int,
                               automation_id: str | None = None) -> JsonObj:
    # Opt-in throughput tuning: retain one batch by default. Never chain tasks
    # into an unbounded queue. The deadline is checked between bounded batches;
    # it must not interrupt an in-flight external action or clear its claim.
    try:
        budget = max(0, min(30, int(os.environ.get("automation_processing_budget_seconds", "0"))))
    except (TypeError, ValueError):
        budget = 0
    deadline = time.monotonic() + budget
    result = _process_eligible_automation_enrolments(db, cid, limit, automation_id)
    for _ in range(99):
        if (not budget or time.monotonic() >= deadline or not result["succeeded"]
                or result["failed"]):
            break
        if not _customer_automation_processing_enabled(db, cid):
            break
        batch = _process_eligible_automation_enrolments(db, cid, limit, automation_id)
        for key in ("processed", "succeeded", "waiting", "completed", "exited", "failed"):
            result[key] += batch[key]
        result["skipped_running"] = max(result["skipped_running"], batch["skipped_running"])
        result["errors"] = (result["errors"] + batch["errors"])[:AUTOMATION_PROCESS_ERROR_LIMIT]
        if not batch["succeeded"]:
            break
    return result


@tasks.task(priority=HIGH_PRIORITY)
def process_automation_enrolments_task(
    cid: str,
    automation_id: str | None = None,
    limit: int = AUTOMATION_PROCESS_DEFAULT_LIMIT,
) -> JsonObj:
    with open_db() as db:
        db.set_cid(cid)
        limit = _automation_process_limit(limit)
        if not _customer_automation_processing_enabled(db, cid):
            result = {
                "processed": 0,
                "succeeded": 0,
                "waiting": 0,
                "completed": 0,
                "exited": 0,
                "failed": 0,
                "skipped_running": 0,
                "errors": [
                    {
                        "title": "Automation processing is disabled",
                        "description": "Automation processing is disabled for this customer account.",
                    }
                ],
            }
            log.info(
                "Skipped automation enrolment processing because customer flag is disabled cid=%s automation_id=%s limit=%s result=%s",
                cid,
                automation_id,
                limit,
                result,
            )
            return result
        if automation_id and db.automations.get(automation_id) is None:
            raise ValueError("Automation %s was not found for cid %s" % (automation_id, cid))

        result = _process_automation_budget(
            db,
            cid,
            limit,
            automation_id,
        )
        log.info(
            "Processed automation enrolments cid=%s automation_id=%s limit=%s result=%s",
            cid,
            automation_id,
            limit,
            result,
        )
        return result


def check_automation_enrolments() -> JsonObj:
    if not _automation_processing_enabled():
        log.info("Automation processing is disabled; set automation_processing_enabled=true to enable scheduled processing.")
        return {
            "enabled": False,
            "accounts": 0,
            "dispatched": 0,
            "task_ids": [],
        }

    account_limit = _automation_scheduler_account_limit()
    process_limit = _automation_scheduler_process_limit()
    task_ids: List[str | None] = []

    with open_db() as db:
        with db.transaction():
            if not db.single(f"select pg_try_advisory_xact_lock({CHECK_AUTOMATION_ENROLMENTS_LOCK})"):
                log.info("Automation processing scheduler is already running.")
                return {
                    "enabled": True,
                    "locked": True,
                    "accounts": 0,
                    "dispatched": 0,
                    "task_ids": [],
                }

            cids = _automation_processing_account_ids(db, account_limit)
            log.info(
                "Dispatching automation processing for %s account(s), account_limit=%s, per_account_limit=%s.",
                len(cids),
                account_limit,
                process_limit,
            )
            for cid in cids:
                task_ids.append(
                    run_task(
                        process_automation_enrolments_task,
                        cid,
                        None,
                        process_limit,
                    )
                )

    return {
        "enabled": True,
        "locked": False,
        "accounts": len(task_ids),
        "dispatched": len(task_ids),
        "task_ids": task_ids,
        "limit": process_limit,
        "account_limit": account_limit,
    }


class AutomationEnrolmentProcessor(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        doc = req.context.get("doc") or {}
        if not isinstance(doc, dict):
            raise falcon.HTTPBadRequest(
                title="Not JSON",
                description="A valid JSON document is required.",
            )

        limit = _automation_process_limit(doc.get("limit"))
        automation_id = doc.get("automation_id")
        if automation_id is not None and not isinstance(automation_id, str):
            raise falcon.HTTPBadRequest(
                title="Invalid automation_id",
                description="automation_id must be a string.",
            )

        db = req.context["db"]
        cid = db.get_cid()
        if not _customer_automation_processing_enabled(db, cid):
            raise falcon.HTTPBadRequest(
                title="Automation processing is disabled",
                description="Automation processing is disabled for this customer account.",
            )
        if automation_id and db.automations.get(automation_id) is None:
            raise falcon.HTTPForbidden()

        req.context["result"] = _process_eligible_automation_enrolments(
            db,
            cid,
            limit,
            automation_id,
        )


class AutomationProcessingStatus(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)
        check_automation_diagnostics(req)

        db = req.context["db"]
        cid = db.get_cid()
        req.context["result"] = _automation_processing_status(db, cid)


class AutomationSegmentTriggerStatus(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)
        check_automation_diagnostics(req)

        db = req.context["db"]
        cid = db.get_cid()
        limit = _automation_segment_trigger_status_limit(req.get_param("limit"))
        req.context["result"] = _automation_segment_trigger_status(db, cid, limit)


class AutomationTriggerEvents(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)
        check_automation_diagnostics(req)

        db = req.context["db"]
        cid = db.get_cid()
        limit = _automation_trigger_event_list_limit(req.get_param("limit"))

        rows = db.execute(
            """
            select id, cid, contact_id, contact_email, event_type, ts, data
            from automation_trigger_events
            where cid = %s
            order by ts desc, id desc
            limit %s
            """,
            cid,
            limit,
        ).fetchall()
        source_names = _automation_trigger_event_source_names(db, cid, rows)

        req.context["result"] = {
            "events": [
                _project_automation_trigger_event(row, source_names)
                for row in rows
            ]
        }

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        if not _automation_trigger_manual_events_enabled():
            raise falcon.HTTPForbidden(
                title="Manual trigger events are disabled",
                description="Set automation_trigger_manual_events_enabled=true to create manual trigger events.",
            )

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON",
                description="A valid JSON document is required.",
            )
        _validate_doc(doc, AUTOMATION_TRIGGER_EVENT_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()
        event = _create_automation_trigger_event(
            db,
            cid,
            event_type=doc["event_type"],
            contact_email=doc["contact_email"],
            tag=doc.get("tag"),
            list_id=doc.get("list_id"),
            segment_id=doc.get("segment_id"),
            source=doc.get("source"),
            correlation_id=doc.get("correlation_id"),
            depth=int(doc.get("depth") or 0),
            created_by=req.context.get("uid"),
            manual_debug=True,
        )
        resp.status = falcon.HTTP_201
        req.context["result"] = event


class AutomationTriggerEventProcessor(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        doc = req.context.get("doc") or {}
        if not isinstance(doc, dict):
            raise falcon.HTTPBadRequest(
                title="Not JSON",
                description="A valid JSON document is required.",
            )
        _validate_doc(doc, AUTOMATION_TRIGGER_PROCESS_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()
        limit = _automation_trigger_limit(doc.get("limit"))
        req.context["result"] = _process_pending_automation_trigger_events(
            db,
            cid,
            limit,
        )


class AutomationSegmentTriggerBaselines(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        doc = req.context.get("doc") or {}
        if not isinstance(doc, dict):
            raise falcon.HTTPBadRequest(
                title="Not JSON",
                description="A valid JSON document is required.",
            )
        _validate_doc(doc, AUTOMATION_SEGMENT_TRIGGER_BASELINE_SCHEMA)

        db = req.context["db"]
        cid = db.get_cid()
        limit_segments = _automation_segment_baseline_limit(
            doc.get("limit_segments"),
            AUTOMATION_SEGMENT_BASELINE_DEFAULT_SEGMENT_LIMIT,
            AUTOMATION_SEGMENT_BASELINE_MAX_SEGMENT_LIMIT,
            "limit_segments",
        )
        limit_buckets = _automation_segment_baseline_limit(
            doc.get("limit_buckets"),
            AUTOMATION_SEGMENT_BASELINE_DEFAULT_BUCKET_LIMIT,
            AUTOMATION_SEGMENT_BASELINE_MAX_BUCKET_LIMIT,
            "limit_buckets",
        )
        mode = doc.get("mode") or "baseline"

        if mode == "diff":
            limit_events = _automation_segment_diff_event_limit(doc.get("limit_events"))
            req.context["result"] = _diff_automation_segment_triggers(
                db,
                cid,
                doc.get("segment_id"),
                limit_segments,
                limit_buckets,
                limit_events,
            )
        else:
            req.context["result"] = _baseline_automation_segment_triggers(
                db,
                cid,
                doc.get("segment_id"),
                limit_segments,
                limit_buckets,
            )


class AutomationEnrolmentRunNext(object):

    def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        enrolment_id: str,
    ) -> None:
        check_noadmin(req)

        body = req.get_media(default_when_empty={}) or {}
        skip_wait = req.get_param_as_bool("skip_wait") is True or (body or {}).get("skip_wait") is True

        db = req.context["db"]
        cid = db.get_cid()
        req.context["result"] = _run_next_automation_enrolment(
            db,
            cid,
            id,
            enrolment_id,
            skip_wait,
        )


class AutomationEnrolmentCancel(object):

    CANCELLABLE_STATUSES = {
        "ready",
        "waiting",
        "held",
        "paused_ready",
        "paused_waiting",
    }

    @_automation_state_transition
    def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        id: str,
        enrolment_id: str,
    ) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        now = _iso_datetime(datetime.utcnow())

        enrolment = _enrolment_obj(
            db.row(
                f"""
                select e.id, e.cid, e.automation_id, e.contact_id, e.contact_email, e.data
                from automation_enrolments e
                join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
                where e.cid = %s and e.automation_id = %s and e.id = %s
                """,
                cid,
                id,
                enrolment_id,
            )
        )
        if enrolment is None:
            raise falcon.HTTPForbidden()

        status = enrolment.get("status") or ""
        if status == "running":
            raise falcon.HTTPBadRequest(
                title="Automation enrolment is currently running",
                description="This enrolment is currently running and cannot be cancelled until the current execution attempt finishes.",
            )
        if status not in self.CANCELLABLE_STATUSES:
            raise falcon.HTTPBadRequest(
                title="Automation enrolment cannot be cancelled",
                description="Only ready, waiting, held, or paused enrolments can be cancelled.",
            )

        cancelled_metadata = {
            "source": "contact_edit",
            "previous_status": status,
        }
        updated = _enrolment_obj(
            db.row(
                """
                update automation_enrolments
                set data = data || jsonb_build_object(
                    'status', 'cancelled',
                    'modified', %s,
                    'cancelled_at', %s,
                    'cancelled_by_uid', %s,
                    'cancelled_metadata', %s::jsonb,
                    'retry_after', null,
                    'retry_count', 0,
                    'last_error', null
                )
                where cid = %s and automation_id = %s and id = %s
                returning id, cid, automation_id, contact_id, contact_email, data
                """,
                now,
                now,
                req.context.get("uid"),
                cancelled_metadata,
                cid,
                id,
                enrolment_id,
            )
        )
        user_log(req, "remove", "cancelled automation enrolment ", "automations", id, ".")
        req.context["result"] = updated


@tasks.task(priority=HIGH_PRIORITY)
def process_automation_exit_events_task(cid: str, limit: int = 100) -> JsonObj:
    with open_db() as db:
        db.set_cid(cid)
        return exit_rules.process_pending(db, cid, min(max(limit, 1), 500))


def check_automation_exit_events() -> JsonObj:
    # Event queue only, including paused accounts/workflows; no contact scan.
    with open_db() as db:
        cids = [row[0] for row in db.execute("""select cid from automation_trigger_events
            where data->>'exit_status'='pending'
              and (data->>'exit_retry_at' is null or (data->>'exit_retry_at')::timestamptz <= now())
            group by cid order by min(ts) limit 100""").fetchall()]
        for cid in cids:
            run_task(process_automation_exit_events_task, cid, 100)
    return {"accounts": len(cids)}


def check_automation_subject_tests():
    """Decision-only scheduler: runs even while automation is paused; never sends."""
    count = 0
    with open_db() as db:
        rows = db.execute("""select t.id,t.cid,t.automation_id from automation_subject_tests t
            join automations a on a.cid=t.cid and a.id=t.automation_id
            where t.data->>'status' in ('collecting','observing') and t.data->>'deadline' <= %s
            order by t.data->>'deadline' limit 100""", _utc_now()).fetchall()
        for eid, cid, aid in rows:
            try:
                with _locked_automation(db, cid, aid):
                    data = db.single("select data from automation_subject_tests where cid=%s and id=%s", cid, eid)
                    if data:
                        subject_tests.decide(db, cid, dict(data, id=eid))
                        count += 1
            except falcon.HTTPForbidden:
                # Deletion between the candidate query and lock is harmless.
                continue
    return {"processed": count}
