import falcon
import copy
import email.utils
import logging
import os
import shortuuid
import traceback
import dateutil.parser
from datetime import datetime, timedelta
from dateutil.tz import tzutc
from jsonschema import validate
from typing import Dict, List

from .shared import config as _  # noqa: F401
from .shared import contacts
from .shared.crud import (
    CRUDCollection,
    CRUDSingle,
    check_noadmin,
    get_orig,
)
from .shared.db import DB, JsonObj, json_obj, open_db
from .shared.tasks import tasks, HIGH_PRIORITY
from .shared.utils import user_log
from .shared.utils import emailre
from .shared.utils import fix_tag
from .shared.utils import generate_html, remove_newlines
from .shared.utils import gather_init, gather_complete, gather_check, run_task
from .shared.send import check_test_limit, send_backend_mail
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


NODE_ID_SCHEMA = {
    "type": "string",
    "pattern": "^[0-9a-zA-Z_-]{1,64}$",
}


ADD_TAG_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "draft_tag"],
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
        "draft_tag": {
            "type": "string",
            "maxLength": 1024,
        },
    },
    "additionalProperties": False,
}


REMOVE_TAG_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "draft_tag"],
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
        "draft_tag": {
            "type": "string",
            "maxLength": 1024,
        },
    },
    "additionalProperties": False,
}


ADD_TO_LIST_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "list_id"],
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
        "list_id": {
            "type": "string",
            "maxLength": 64,
        },
    },
    "additionalProperties": False,
}


REMOVE_FROM_LIST_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label", "list_id"],
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
        "list_id": {
            "type": "string",
            "maxLength": 64,
        },
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
    "required": ["id", "type", "label", "duration"],
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

TERMINAL_ENROLMENT_STATUSES = ("completed", "exited", "cancelled")


ENTRY_SCHEMA = {
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
    ],
}


DRAFT_SCHEMA = {
    "type": "object",
    "required": ["nodes"],
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "oneOf": [
                    ADD_TAG_NODE_SCHEMA,
                    REMOVE_TAG_NODE_SCHEMA,
                    ADD_TO_LIST_NODE_SCHEMA,
                    REMOVE_FROM_LIST_NODE_SCHEMA,
                    WAIT_DURATION_NODE_SCHEMA,
                    IF_HAS_TAG_NODE_SCHEMA,
                    GO_TO_NODE_SCHEMA,
                    SEND_EMAIL_NODE_SCHEMA,
                    EXIT_NODE_SCHEMA,
                ],
            },
        },
    },
    "additionalProperties": False,
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
        "draft": DRAFT_SCHEMA,
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
            "enum": ["tag_added", "tag_removed", "list_joined", "list_left"],
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

BULK_DETAIL_LIMIT = 100


def _validate_doc(doc: JsonObj, schema: JsonObj) -> None:
    try:
        validate(doc, schema)
    except Exception as e:
        raise falcon.HTTPBadRequest(title="Input validation error", description=str(e))


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


def _published_entry(entry: JsonObj) -> JsonObj:
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
    _validation_error("Automation entry trigger type is not supported.")


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


def _node_display(node: JsonObj, node_positions: dict[str, int]) -> str:
    node_id = node.get("id", "")
    step = node_positions.get(node_id, -1) + 1
    label = (node.get("label") or node.get("type") or node_id).strip()
    if step > 0:
        return "Step %s %s" % (step, label)
    return label


def _workflow_edges(nodes: list[JsonObj]) -> dict[str, list[str]]:
    edges = {}
    for index, node in enumerate(nodes):
        node_id = node.get("id")
        node_type = node.get("type")
        if node_type == "exit":
            edges[node_id] = []
        elif node_type == "go_to":
            edges[node_id] = [node.get("target_node_id")]
        elif node_type == "if_has_tag":
            edges[node_id] = [node.get("yes_node_id"), node.get("no_node_id")]
        elif index + 1 < len(nodes):
            edges[node_id] = [nodes[index + 1].get("id")]
        else:
            edges[node_id] = []
    return edges


def _validate_no_workflow_cycles(nodes: list[JsonObj], node_positions: dict[str, int]) -> None:
    node_map = {node.get("id"): node for node in nodes}
    edges = _workflow_edges(nodes)
    states: dict[str, str] = {}
    stack: list[str] = []

    def visit(node_id: str) -> None:
        state = states.get(node_id)
        if state == "visited":
            return
        if state == "visiting":
            start = stack.index(node_id)
            cycle_ids = stack[start:] + [node_id]
            cycle = " -> ".join(
                _node_display(node_map[cycle_id], node_positions)
                for cycle_id in cycle_ids
            )
            _validation_error("Workflow contains a cycle: %s." % cycle)

        states[node_id] = "visiting"
        stack.append(node_id)
        for target_id in edges.get(node_id, []):
            if target_id in node_map:
                visit(target_id)
        stack.pop()
        states[node_id] = "visited"

    for node in nodes:
        visit(node.get("id"))


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

    return {
        "list_id": list_id,
        "list_name": lst.get("name"),
        "removed": removed,
    }


def _published_snapshot(db: DB, automation: JsonObj) -> JsonObj:
    if not automation.get("name") or not automation.get("name").strip():
        _validation_error("Automation must have a name before publishing.")

    entry = automation.get("entry")
    if entry is None:
        _validation_error("Automation entry is required.")
    _validate_doc(entry, ENTRY_SCHEMA)
    entry = _published_entry(entry)
    if entry.get("type") in ("list_joined", "list_left"):
        if db.lists.get(entry.get("list_id")) is None:
            _validation_error("List entry trigger must reference a contact list from this account.")

    reentry = automation.get("reentry", "once")
    _validate_doc(reentry, REENTRY_SCHEMA)

    draft = automation.get("draft")
    if draft is None:
        _validation_error("Automation draft workflow is required.")
    _validate_doc(draft, DRAFT_SCHEMA)

    nodes = draft.get("nodes") or []
    if not nodes:
        _validation_error("Automation draft must contain at least one node.")
    node_positions = {node.get("id"): index for index, node in enumerate(nodes)}
    node_ids = set(node_positions.keys())
    for index, node in enumerate(nodes):
        if not node.get("id"):
            _validation_error("Every automation node must have a stable ID.")
        if not node.get("label") or not node.get("label").strip():
            _validation_error("Every automation node must have a label.")
        if node.get("type") == "add_tag" and not node.get("draft_tag"):
            _validation_error("Add tag nodes must have draft tag configuration.")
        if node.get("type") == "remove_tag" and not node.get("draft_tag"):
            _validation_error("Remove tag nodes must have draft tag configuration.")
        if node.get("type") in ("add_to_list", "remove_from_list"):
            list_id = node.get("list_id")
            if not list_id:
                _validation_error("%s nodes must select a contact list." % node.get("type"))
            if db.lists.get(list_id) is None:
                _validation_error(
                    "%s node at step %s must reference a contact list from this account."
                    % (node.get("type"), index + 1)
                )
        if node.get("type") == "if_has_tag":
            if not node.get("draft_tag"):
                _validation_error("If has tag nodes must have draft tag configuration.")
            if not node.get("yes_node_id"):
                _validation_error("If has tag nodes must have a yes target.")
            if not node.get("no_node_id"):
                _validation_error("If has tag nodes must have a no target.")
            if node.get("yes_node_id") not in node_ids:
                _validation_error("If has tag yes target must exist in the draft workflow.")
            if node.get("no_node_id") not in node_ids:
                _validation_error("If has tag no target must exist in the draft workflow.")
            if node.get("yes_node_id") == node.get("id") or node.get("no_node_id") == node.get("id"):
                _validation_error("If has tag nodes cannot target themselves.")
        if node.get("type") == "go_to":
            target_node_id = node.get("target_node_id")
            if not target_node_id:
                _validation_error("Go to nodes must have a target.")
            if target_node_id not in node_ids:
                _validation_error("Go to target must exist in the draft workflow.")
            if target_node_id == node.get("id"):
                _validation_error("Go to nodes cannot target themselves.")
            if node_positions.get(target_node_id, -1) <= index:
                _validation_error("Go to nodes must target a later node.")
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
        if node.get("type") == "wait_duration":
            total_minutes = _duration_minutes(node.get("duration", {}))
            if total_minutes < 5:
                _validation_error("Wait duration nodes must wait at least 5 minutes.")
            if total_minutes > 365 * 24 * 60:
                _validation_error("Wait duration nodes cannot wait more than 365 days.")
    _validate_no_workflow_cycles(nodes, node_positions)
    return {
        "entry": copy.deepcopy(entry),
        "reentry": reentry,
        "nodes": copy.deepcopy(nodes),
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


def _node_references_automation_email(node: JsonObj, email_id: str) -> bool:
    return (
        node.get("email_id") == email_id
        or node.get("automation_email_id") == email_id
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
    _, nodes, reentry = _published_enrolment_context(automation)

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


CLAIM_STALE_AFTER = timedelta(minutes=30)
AUTOMATION_PROCESS_DEFAULT_LIMIT = 25
AUTOMATION_PROCESS_MAX_LIMIT = 100
AUTOMATION_PROCESS_ERROR_LIMIT = 100
AUTOMATION_PROCESS_ACCOUNT_LIMIT = 50
CHECK_AUTOMATION_ENROLMENTS_LOCK = 58413921
AUTOMATION_TRIGGER_DEFAULT_LIMIT = 25
AUTOMATION_TRIGGER_MAX_LIMIT = 100
AUTOMATION_TRIGGER_DETAIL_LIMIT = 100
AUTOMATION_TRIGGER_COOLDOWN_MINUTES = 15
AUTOMATION_TRIGGER_EVENT_LIST_DEFAULT_LIMIT = 50
AUTOMATION_TRIGGER_EVENT_RESPONSE_DETAIL_LIMIT = 25
TAG_TRIGGER_EVENT_TYPES = ("tag_added", "tag_removed")
LIST_TRIGGER_EVENT_TYPES = ("list_joined", "list_left")
SUPPORTED_TRIGGER_EVENT_TYPES = TAG_TRIGGER_EVENT_TYPES + LIST_TRIGGER_EVENT_TYPES


def _claim_clear_patch() -> JsonObj:
    return {
        "running_status": None,
        "claim_token": None,
        "claimed_at": None,
        "claimed_node_id": None,
        "claimed_published_revision": None,
    }


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
    db.execute(
        """
        update automation_enrolments
        set data = data || %s
        where cid = %s and automation_id = %s and id = %s and data->>'claim_token' = %s
        """,
        patch,
        cid,
        automation_id,
        enrolment_id,
        claim_token,
    )


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
    updated = db.execute(
        """
        update automation_enrolments
        set data = data || %s
        where cid = %s and automation_id = %s and id = %s and data->>'claim_token' = %s
        """,
        update,
        cid,
        automation_id,
        enrolment_id,
        claim_token,
    ).rowcount
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

        if req.context["db"].automations.get(id) is None:
            raise falcon.HTTPForbidden()

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        _validate_doc(doc, AUTOMATION_PATCH_SCHEMA)
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


class AutomationPublish(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()

        published = _published_snapshot(db, automation)
        now = _utc_now()
        revision = int(automation.get("published_revision", 0) or 0) + 1

        doc = {
            "status": "published",
            "published": published,
            "published_at": now,
            "published_by": req.context["uid"],
            "published_revision": revision,
            "modified": now,
        }

        db.automations.patch(id, doc)
        user_log(req, "pencil", "published automation ", "automations", id, ".")

        req.context["result"] = db.automations.get(id)


class AutomationPause(object):

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
                wake_at = _iso_datetime(now_dt + timedelta(seconds=remaining))
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

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()
        if db.automations.get(id) is None:
            raise falcon.HTTPForbidden()

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
        if outcome.get("status") == "skipped" and outcome.get("reason") == "active_pass":
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

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

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
        for step_run in step_runs:
            enrolment = enrolments_by_id.get(step_run["enrolment_id"])
            if enrolment is not None:
                enrolment["step_runs"].append(step_run)

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
                    "list_id": step_run.get("list_id"),
                    "list_name": step_run.get("list_name"),
                    "added": step_run.get("added"),
                    "removed": step_run.get("removed"),
                    "duration": step_run.get("duration"),
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
                    "published_revision": step_run.get("published_revision"),
                    "status": step_run.get("status"),
                    "error": step_run.get("error"),
                }
            )

        events.sort(key=lambda event: (event.get("created") or "", event["type"]))

        req.context["result"] = {
            "automation_id": id,
            "generated_at": _utc_now(),
            "limits": {
                "enrolments": self.ENROLMENT_LIMIT,
                "step_runs": self.STEP_RUN_LIMIT,
            },
            "enrolments": enrolments,
            "events": events,
        }


def _run_next_automation_enrolment(
    db: DB,
    cid: str,
    id: str,
    enrolment_id: str,
    skip_wait: bool = False,
) -> JsonObj:
    automation = db.automations.get(id)
    if automation is None:
        raise falcon.HTTPForbidden()
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
    original_status = _running_status(enrolment)
    run_id = shortuuid.uuid()
    run_inserted = False

    try:
        nodes = published.get("nodes") or []
        current_node_id = enrolment.get("current_node_id")
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
        if node_type not in ("add_tag", "remove_tag", "add_to_list", "remove_from_list", "wait_duration", "if_has_tag", "go_to", "send_email", "exit"):
            raise falcon.HTTPBadRequest(
                title="Unsupported automation node",
                description=(
                    "%s nodes are not supported by manual execution yet. "
                    "Only add_tag, remove_tag, add_to_list, remove_from_list, wait_duration, if_has_tag, go_to, send_email and exit nodes can be executed manually."
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
        elif node_type == "add_tag":
            tag = node.get("draft_tag")
            if not tag:
                raise falcon.HTTPBadRequest(
                    title="Add tag node is missing tag configuration",
                    description="The published add_tag node does not include a tag.",
                )

            db.execute(
                """insert into alltags (cid, tag, added, count) values (%s, %s, now(), 0)
                on conflict (cid, tag) do nothing""",
                cid,
                tag,
            )
            tagcounts = {}
            trigger_correlation_id = enrolment.get("trigger_correlation_id") or "automation:%s" % enrolment_id
            try:
                trigger_depth = int(enrolment.get("trigger_depth") or 0) + 1
            except (TypeError, ValueError):
                trigger_depth = 1
            contacts.add_tag(
                db,
                cid,
                enrolment["contact_email"],
                enrolment["contact_id"],
                tag,
                None,
                {},
                tagcounts,
                [],
                {
                    "type": "automation",
                    "automation_id": id,
                    "enrolment_id": enrolment_id,
                    "node_id": node.get("id"),
                    "step_run_id": run_id,
                    "published_revision": automation.get("published_revision"),
                },
                trigger_correlation_id,
                trigger_depth,
            )
            for tagname, cnt in tagcounts.items():
                db.execute(
                    "update alltags set count = count + %s where cid = %s and tag = %s",
                    cnt,
                    cid,
                    tagname,
                )

            success_data["tag"] = tag

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
        elif node_type == "remove_tag":
            tag = node.get("draft_tag")
            if not tag:
                raise falcon.HTTPBadRequest(
                    title="Remove tag node is missing tag configuration",
                    description="The published remove_tag node does not include a tag.",
                )

            tagcounts = {}
            trigger_correlation_id = enrolment.get("trigger_correlation_id") or "automation:%s" % enrolment_id
            try:
                trigger_depth = int(enrolment.get("trigger_depth") or 0) + 1
            except (TypeError, ValueError):
                trigger_depth = 1
            contacts.remove_tag(
                db,
                cid,
                enrolment["contact_email"],
                enrolment["contact_id"],
                tag,
                tagcounts,
                [],
                {
                    "type": "automation",
                    "automation_id": id,
                    "enrolment_id": enrolment_id,
                    "node_id": node.get("id"),
                    "step_run_id": run_id,
                    "published_revision": automation.get("published_revision"),
                },
                trigger_correlation_id,
                trigger_depth,
            )
            removed = bool(tagcounts.get(tag))
            for tagname, cnt in tagcounts.items():
                db.execute(
                    "update alltags set count = count + %s where cid = %s and tag = %s",
                    cnt,
                    cid,
                    tagname,
                )
            if tagcounts:
                db.execute(
                    "delete from alltags where cid = %s and count <= 0",
                    cid,
                )

            success_data.update(
                {
                    "action": "remove_tag",
                    "tag": tag,
                    "removed": removed,
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
        elif node_type == "add_to_list":
            list_id = node.get("list_id")
            if not list_id:
                raise falcon.HTTPBadRequest(
                    title="Add to list node is missing list configuration",
                    description="The published add_to_list node does not include a contact list.",
                )

            list_result = _add_contact_to_list(
                db,
                cid,
                enrolment["contact_id"],
                enrolment["contact_email"],
                list_id,
            )
            success_data.update(
                {
                    "action": "add_to_list",
                    "list_id": list_result["list_id"],
                    "list_name": list_result.get("list_name"),
                    "added": list_result["added"],
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
        elif node_type == "remove_from_list":
            list_id = node.get("list_id")
            if not list_id:
                raise falcon.HTTPBadRequest(
                    title="Remove from list node is missing list configuration",
                    description="The published remove_from_list node does not include a contact list.",
                )

            list_result = _remove_contact_from_list(
                db,
                cid,
                enrolment["contact_id"],
                enrolment["contact_email"],
                list_id,
            )
            success_data.update(
                {
                    "action": "remove_from_list",
                    "list_id": list_result["list_id"],
                    "list_name": list_result.get("list_name"),
                    "removed": list_result["removed"],
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
        elif node_type == "wait_duration":
            duration = node.get("duration") or {}
            wake_at = _wake_at(now_dt, duration)
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
                    "started_at": now,
                    "wake_at": wake_at,
                    "published_revision": automation.get("published_revision"),
                },
                "modified": now,
            }
        elif node_type == "if_has_tag":
            tag = node.get("draft_tag")
            if not tag:
                raise falcon.HTTPBadRequest(
                    title="If has tag node is missing tag configuration",
                    description="The published if_has_tag node does not include a tag.",
                )

            result = _contact_has_tag(db, cid, enrolment["contact_id"], tag)
            branch = "yes" if result else "no"
            target_node_id = node.get("yes_node_id") if result else node.get("no_node_id")
            if _node_by_id(nodes, target_node_id) is None:
                raise falcon.HTTPBadRequest(
                    title="Automation branch target is missing",
                    description="The published if_has_tag %s target was not found in the published workflow." % branch,
                )

            success_data.update(
                {
                    "action": "branch",
                    "tag": tag,
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

            fromname, fromemail, returnpath, replyto = _automation_email_sender(automation_email)

            route = _automation_execution_route(db, cid)

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
            subject = remove_newlines(automation_email["subject"])
            fromdomain = ""
            if "@" in returnpath:
                fromdomain = returnpath.split("@")[-1].strip().lower()
            elif "@" in fromemail:
                fromdomain = fromemail.split("@")[-1].strip().lower()
            fromaddr = email.utils.formataddr((fromname, fromemail))
            recipient_email = enrolment["contact_email"]

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
            except Exception as e:
                log.warning("Error sending automation email: %s", e)
                raise falcon.HTTPBadRequest(
                    title="Error sending automation email",
                    description="Error sending automation email: %s" % e,
                )

            success_data.update(
                {
                    "action": "send_email",
                    "automation_email_id": automation_email_id,
                    "automation_email_name": automation_email.get("name"),
                    "subject": subject,
                    "recipient_email": recipient_email,
                    "route_id": route["id"],
                    "sent": True,
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
    except falcon.HTTPError as e:
        fail_now = _utc_now()
        if run_inserted:
            _patch_step_run(
                db,
                cid,
                run_id,
                {
                    "status": "failed",
                    "error": e.description or e.title,
                    "failed_at": fail_now,
                },
            )
        _release_run_claim(
            db,
            cid,
            id,
            enrolment_id,
            claim_token,
            original_status,
            fail_now,
            {
                "last_error": {
                    "title": e.title,
                    "description": e.description,
                    "at": fail_now,
                },
            },
        )
        raise

    _patch_step_run(db, cid, run_id, success_data)
    _advance_claimed_enrolment(
        db,
        cid,
        id,
        enrolment_id,
        claim_token,
        enrolment_update,
    )

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
        "type": source.get("type") or "manual",
    }
    for key in ("automation_id", "enrolment_id", "node_id", "step_run_id"):
        value = source.get(key)
        if value:
            ret[key] = value
    return ret


def _trigger_event_selector(event: JsonObj) -> tuple[str | None, str | None]:
    event_type = event.get("event_type")
    if event_type in TAG_TRIGGER_EVENT_TYPES:
        return "tag", event.get("tag")
    if event_type in LIST_TRIGGER_EVENT_TYPES:
        return "list_id", event.get("list_id")
    return None, None


def _create_automation_trigger_event(
    db: DB,
    cid: str,
    event_type: str,
    contact_email: str,
    tag: str | None = None,
    list_id: str | None = None,
    source: JsonObj | None = None,
    correlation_id: str | None = None,
    depth: int = 0,
    created_by: str | None = None,
    manual_debug: bool = False,
) -> JsonObj:
    if event_type not in SUPPORTED_TRIGGER_EVENT_TYPES:
        raise falcon.HTTPBadRequest(
            title="Unsupported trigger event",
            description="Only tag_added, tag_removed, list_joined and list_left trigger events are supported.",
        )

    if event_type in TAG_TRIGGER_EVENT_TYPES:
        tag = fix_tag(tag or "")
        if not tag:
            raise falcon.HTTPBadRequest(
                title="Trigger tag is required",
                description="Tag trigger events require a tag.",
            )
    else:
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
    else:
        data["list_id"] = list_id
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
            and data->'published'->'entry'->>'type' = %s
            and data->'published'->'entry'->>%s = %s
        order by data->>'name', id
        """,
        cid,
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


def _eligible_automation_enrolments(
    db: DB,
    cid: str,
    limit: int,
    automation_id: str | None = None,
) -> List[JsonObj]:
    now = datetime.utcnow()
    params: List[object] = [cid, now, limit]
    automation_filter = ""
    if automation_id:
        automation_filter = "and e.automation_id = %s"
        params = [cid, automation_id, now, limit]

    return [
        {
            "automation_id": automation_id,
            "enrolment_id": enrolment_id,
            "contact_email": contact_email,
            "status": status,
        }
        for automation_id, enrolment_id, contact_email, status in db.execute(
            f"""
            select e.automation_id, e.id, e.contact_email, e.data->>'status'
            from automation_enrolments e
            join automations a on a.cid = e.cid and a.id = e.automation_id
            join contacts."contacts_{cid}" c on c.contact_id = e.contact_id
            where e.cid = %s
                {automation_filter}
                and a.data->'published' is not null
                and coalesce(a.data->>'status', '') <> 'paused'
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
        )
    ]


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
    return [
        cid
        for cid, in db.execute(
            """
            select e.cid
            from automation_enrolments e
            join automations a on a.cid = e.cid and a.id = e.automation_id
            join companies c on c.id = e.cid
            where c.data @> %s
                and a.data->'published' is not null
                and coalesce(a.data->>'status', '') <> 'paused'
                and (
                    e.data->>'status' = 'ready'
                    or (
                        e.data->>'status' = 'waiting'
                        and nullif(e.data->>'wake_at', '')::timestamptz <= %s
                    )
                )
            group by e.cid
            order by min(
                coalesce(
                    nullif(e.data->>'modified', '')::timestamptz,
                    nullif(e.data->>'created', '')::timestamptz
                )
            ), e.cid
            limit %s
            """,
            {"admin": False},
            datetime.utcnow(),
            account_limit,
        )
    ]


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


@tasks.task(priority=HIGH_PRIORITY)
def process_automation_enrolments_task(
    cid: str,
    automation_id: str | None = None,
    limit: int = AUTOMATION_PROCESS_DEFAULT_LIMIT,
) -> JsonObj:
    with open_db() as db:
        db.set_cid(cid)
        limit = _automation_process_limit(limit)
        if automation_id and db.automations.get(automation_id) is None:
            raise ValueError("Automation %s was not found for cid %s" % (automation_id, cid))

        result = _process_eligible_automation_enrolments(
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
        if automation_id and db.automations.get(automation_id) is None:
            raise falcon.HTTPForbidden()

        req.context["result"] = _process_eligible_automation_enrolments(
            db,
            cid,
            limit,
            automation_id,
        )


class AutomationTriggerEvents(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

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
            doc["event_type"],
            doc["contact_email"],
            doc.get("tag"),
            doc.get("list_id"),
            doc.get("source"),
            doc.get("correlation_id"),
            int(doc.get("depth") or 0),
            req.context.get("uid"),
            True,
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
