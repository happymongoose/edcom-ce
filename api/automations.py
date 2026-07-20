import falcon
import copy
import shortuuid
import dateutil.parser
from datetime import datetime, timedelta
from dateutil.tz import tzutc
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
                    WAIT_DURATION_NODE_SCHEMA,
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
        if node.get("type") == "wait_duration":
            total_minutes = _duration_minutes(node.get("duration", {}))
            if total_minutes < 5:
                _validation_error("Wait duration nodes must wait at least 5 minutes.")
            if total_minutes > 365 * 24 * 60:
                _validation_error("Wait duration nodes cannot wait more than 365 days.")
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
            "status": "held" if automation.get("status") == "paused" else "ready",
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
                    "duration": step_run.get("duration"),
                    "wake_at": step_run.get("wake_at"),
                    "action": step_run.get("action"),
                    "skipped": step_run.get("skipped"),
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
        automation = db.automations.get(id)
        if automation is None:
            raise falcon.HTTPForbidden()
        if automation.get("status") == "paused":
            raise falcon.HTTPBadRequest(
                title="Automation is paused",
                description="Resume the automation before running test steps.",
            )

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
        if node_type not in ("add_tag", "wait_duration", "exit"):
            raise falcon.HTTPBadRequest(
                title="Unsupported automation node",
                description="Only add_tag, wait_duration and exit nodes can be executed manually.",
            )

        status = enrolment.get("status")
        if status in ("held", "paused_ready", "paused_waiting"):
            raise falcon.HTTPBadRequest(
                title="Enrolment is paused",
                description="Resume the automation before running this enrolment.",
            )
        if status not in ("ready", "waiting"):
            raise falcon.HTTPBadRequest(
                title="Enrolment is not ready",
                description="Only ready or elapsed waiting enrolments can run the next automation node.",
            )
        if status == "waiting" and node_type != "wait_duration":
            raise falcon.HTTPBadRequest(
                title="Enrolment wait state is invalid",
                description="Waiting enrolments must remain on a wait_duration node.",
            )

        now_dt = datetime.utcnow()
        now = now_dt.isoformat() + "Z"
        run_id = shortuuid.uuid()
        run_data = {
            "status": "succeeded",
            "node_label": node.get("label"),
            "published_revision": automation.get("published_revision"),
            "created": now,
        }

        if status == "waiting":
            wake_at = enrolment.get("wake_at")
            if not wake_at:
                raise falcon.HTTPBadRequest(
                    title="Waiting enrolment is missing wake_at",
                    description="The waiting enrolment cannot continue without wake_at metadata.",
                )
            if now_dt < _parse_datetime(wake_at) and not skip_wait:
                raise falcon.HTTPBadRequest(
                    title="Wait has not elapsed",
                    description="This enrolment is waiting until %s." % wake_at,
                )

            wait = enrolment.get("wait") or {}
            run_data.update(
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
        elif node_type == "wait_duration":
            duration = node.get("duration") or {}
            wake_at = _wake_at(now_dt, duration)
            run_data.update(
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
