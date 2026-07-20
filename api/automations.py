import falcon
import copy
import shortuuid
from datetime import datetime
from jsonschema import validate

from .shared import config as _  # noqa: F401
from .shared import contacts
from .shared.crud import (
    CRUDCollection,
    CRUDSingle,
    check_noadmin,
)
from .shared.db import DB, JsonObj
from .shared.utils import user_log
from .shared.utils import emailre


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

        reentry = published.get("reentry", automation.get("reentry", "once"))
        _validate_doc(reentry, REENTRY_SCHEMA)
        if reentry == "once" and db.single(
            """
            select id
            from automation_enrolments
            where cid = %s and automation_id = %s and contact_id = %s
            limit 1
            """,
            cid,
            id,
            contact_id,
        ):
            raise falcon.HTTPBadRequest(
                title="Contact already enrolled",
                description="This automation only allows a contact to enter once.",
            )

        now = _utc_now()
        enrolment_id = shortuuid.uuid()
        data = {
            "status": "ready",
            "source": "manual",
            "current_node_id": nodes[0]["id"],
            "published_revision": automation.get("published_revision"),
            "created": now,
            "modified": now,
        }

        db.execute(
            """
            insert into automation_enrolments
                (id, cid, automation_id, contact_id, contact_email, data)
            values (%s, %s, %s, %s, %s, %s)
            """,
            enrolment_id,
            cid,
            id,
            contact_id,
            contact_email,
            data,
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
                enrolment_id,
            )
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

        db = req.context["db"]
        cid = db.get_cid()
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()

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

        if enrolment.get("status") != "ready":
            raise falcon.HTTPBadRequest(
                title="Enrolment is not ready",
                description="Only ready enrolments can run the next automation node.",
            )

        published = automation.get("published")
        if not published:
            raise falcon.HTTPBadRequest(
                title="Automation is not published",
                description="Automation execution uses the published workflow snapshot.",
            )

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
        if node_type not in ("add_tag", "exit"):
            raise falcon.HTTPBadRequest(
                title="Unsupported automation node",
                description="Only add_tag and exit nodes can be executed manually.",
            )

        now = _utc_now()
        run_id = shortuuid.uuid()
        run_data = {
            "status": "succeeded",
            "node_label": node.get("label"),
            "published_revision": automation.get("published_revision"),
            "created": now,
        }

        if node_type == "add_tag":
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
            )
            for tagname, cnt in tagcounts.items():
                db.execute(
                    "update alltags set count = count + %s where cid = %s and tag = %s",
                    cnt,
                    cid,
                    tagname,
                )

            run_data["tag"] = tag

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

        db.execute(
            """
            insert into automation_step_runs
                (id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            run_id,
            cid,
            id,
            enrolment_id,
            enrolment["contact_id"],
            current_node_id,
            node_type,
            run_data,
        )

        db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            enrolment_update,
            cid,
            id,
            enrolment_id,
        )

        req.context["result"] = {
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
