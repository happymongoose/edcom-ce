import falcon
import copy
from datetime import datetime
from jsonschema import validate

from .shared import config as _  # noqa: F401
from .shared.crud import (
    CRUDCollection,
    CRUDSingle,
    check_noadmin,
)
from .shared.db import DB, JsonObj
from .shared.utils import user_log


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


ENTRY_SCHEMA = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "type": {
            "type": "string",
            "enum": ["manual"],
        },
    },
    "additionalProperties": False,
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


def _validate_doc(doc: JsonObj, schema: JsonObj) -> None:
    try:
        validate(doc, schema)
    except Exception as e:
        raise falcon.HTTPBadRequest(title="Input validation error", description=str(e))


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


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


def _published_snapshot(automation: JsonObj) -> JsonObj:
    if not automation.get("name") or not automation.get("name").strip():
        _validation_error("Automation must have a name before publishing.")

    entry = automation.get("entry")
    if entry is None:
        _validation_error("Automation entry is required.")
    _validate_doc(entry, ENTRY_SCHEMA)
    if entry.get("type") != "manual":
        _validation_error("Automation entry must be manual.")

    reentry = automation.get("reentry", "once")
    _validate_doc(reentry, REENTRY_SCHEMA)

    draft = automation.get("draft")
    if draft is None:
        _validation_error("Automation draft workflow is required.")
    _validate_doc(draft, DRAFT_SCHEMA)

    nodes = draft.get("nodes") or []
    if not nodes:
        _validation_error("Automation draft must contain at least one node.")
    for node in nodes:
        if not node.get("id"):
            _validation_error("Every automation node must have a stable ID.")
        if not node.get("label") or not node.get("label").strip():
            _validation_error("Every automation node must have a label.")
        if node.get("type") == "add_tag" and not node.get("draft_tag"):
            _validation_error("Add tag nodes must have draft tag configuration.")
    if not any(node.get("type") == "exit" for node in nodes):
        _validation_error("Automation draft must contain an exit node.")

    return {
        "entry": copy.deepcopy(entry),
        "reentry": reentry,
        "nodes": copy.deepcopy(nodes),
    }


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


class AutomationPublish(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()

        published = _published_snapshot(automation)
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
