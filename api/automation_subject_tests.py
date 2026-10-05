"""Email-owned subject experiments. Call mutations under the automation lock.

No locks or transactions span external delivery. Assignment is the commitment
boundary: overrides affect only subsequently assigned sends.
"""

from datetime import datetime, timedelta
import random
import shortuuid
import falcon
from .shared.crud import check_noadmin


class Gate(Exception):
    def __init__(self, experiment_id, deadline):
        self.experiment_id, self.deadline = experiment_id, deadline


def stamp():
    return datetime.utcnow().isoformat() + "Z"


def error(message):
    raise falcon.HTTPBadRequest(title="Invalid subject experiment", description=message)


def active(db, cid, automation_id, email_id):
    row = db.row(
        """select id, data from automation_subject_tests where cid=%s
        and automation_id=%s and email_id=%s and data->>'status'<>'archived'""",
        cid,
        automation_id,
        email_id,
    )
    return dict(row[1], id=row[0]) if row else None


def save(db, cid, experiment):
    data = {k: v for k, v in experiment.items() if k != "id"}
    db.execute(
        "update automation_subject_tests set data=%s where cid=%s and id=%s",
        data,
        cid,
        experiment["id"],
    )


def statistics(db, cid, experiment):
    rows = db.execute(
        """select data->>'variant_id', count(*), count(distinct contact_id),
        count(*) filter(where data->>'status'='accepted'),
        count(*) filter(where data->>'status'='uncertain'),
        count(*) filter(where data ? 'delivered_at'),
        count(*) filter(where data ? 'delivered_at' and data ? 'opened_at'),
        count(*) filter(where data ? 'delivered_at' and data ? 'clicked_at')
        from automation_subject_sends where cid=%s and experiment_id=%s and data->>'sample'='true'
        group by data->>'variant_id'""",
        cid,
        experiment["id"],
    ).fetchall()
    counts = {row[0]: row[1:] for row in rows}
    result = []
    for variant in experiment["variants"]:
        assigned, recipients, accepted, uncertain, delivered, opened, clicked = (
            counts.get(variant["id"], (0,) * 7)
        )
        result.append(
            dict(
                variant,
                assigned=assigned,
                recipients=recipients,
                accepted=accepted,
                uncertain=uncertain,
                deliveries=delivered,
                opens=opened,
                clicks=clicked,
                or_rate=opened / delivered if delivered else None,
                ctr=clicked / delivered if delivered else None,
                ctor=clicked / opened if opened else None,
            )
        )
    return result


def release_gates(db, cid, experiment_id):
    # Preserve pauses, claims and all unrelated wait/retry state.
    db.execute(
        """update automation_enrolments set data=data||%s
        where cid=%s and data->>'subject_gate'=%s and data->>'claim_token' is null
        and data->>'status' in ('ready','paused_ready','held')""",
        {"retry_after": None, "subject_gate": None},
        cid,
        experiment_id,
    )


def decide(db, cid, experiment, now=None):
    now = now or stamp()
    if (
        experiment["status"] not in ("collecting", "observing")
        or not experiment.get("deadline")
        or now < experiment["deadline"]
    ):
        return experiment
    stats = statistics(db, cid, experiment)
    field = "or_rate" if experiment["metric"] == "or" else "ctr"
    best = max((v[field] or 0 for v in stats), default=0)
    leaders = [v["id"] for v in stats if (v[field] or 0) == best]
    clear = best > 0 and len(leaders) == 1
    winner = leaders[0] if clear else experiment["control_id"]
    experiment.update(
        status="selected",
        version=experiment["version"] + 1,
        winner_id=winner,
        decision={
            "at": now,
            "winner_id": winner,
            "reason": "highest_observed_rate" if clear else "no_clear_winner_control",
            "metric": experiment["metric"],
            "statistics": stats,
        },
    )
    save(db, cid, experiment)
    release_gates(db, cid, experiment["id"])
    return experiment


def reserve(
    db, cid, automation_id, email_id, enrolment_id, node_id, contact_id, run_id
):
    # Definite failure retries keep their original subject, even across winner selection.
    row = db.row(
        """select s.id,s.data from automation_subject_sends s
        join automation_enrolments e on e.cid=s.cid and e.id=s.enrolment_id
        join automation_step_runs r on r.cid=e.cid and r.id=e.data->>'last_failed_step_run_id'
        where s.cid=%s and s.enrolment_id=%s and s.node_id=%s and s.email_id=%s
        and s.data->>'status'='not_sent'
        and s.id=r.data->'subject_assignment'->>'assignment_id' """,
        cid,
        enrolment_id,
        node_id,
        email_id,
    )
    if row:
        assignment_id, data = row
        data["status"] = "reserved"
        db.execute(
            "update automation_subject_sends set data=%s where cid=%s and id=%s",
            data,
            cid,
            assignment_id,
        )
        return dict(data, assignment_id=assignment_id)
    experiment = active(db, cid, automation_id, email_id)
    if not experiment:
        return None
    decide(db, cid, experiment)
    sample = experiment["status"] != "selected"
    now = stamp()
    if sample:
        count = db.single(
            """select count(*) from automation_subject_sends where cid=%s and experiment_id=%s
            and data->>'sample'='true'""",
            cid,
            experiment["id"],
        )
        if count >= experiment["maximum_sends"]:
            raise Gate(experiment["id"], experiment["deadline"])
        options = [v for v in experiment["variants"] if v["weight"] > 0]
        variant = random.SystemRandom().choices(
            options, weights=[v["weight"] for v in options]
        )[0]
        if not experiment.get("deadline"):
            experiment.update(
                started_at=now,
                deadline=(
                    datetime.utcnow() + timedelta(hours=experiment["hours"])
                ).isoformat()
                + "Z",
            )
        if count + 1 >= experiment["maximum_sends"]:
            experiment["status"] = "observing"
        save(db, cid, experiment)
    else:
        variant = next(
            v for v in experiment["variants"] if v["id"] == experiment["winner_id"]
        )
    assignment_id = shortuuid.uuid()
    data = {
        "experiment_id": experiment["id"],
        "variant_id": variant["id"],
        "subject": variant["subject"],
        "sample": sample,
        "status": "reserved",
        "created": now,
    }
    db.execute(
        """insert into automation_subject_sends(id,cid,automation_id,email_id,experiment_id,enrolment_id,node_id,contact_id,data)
        values(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        assignment_id,
        cid,
        automation_id,
        email_id,
        experiment["id"],
        enrolment_id,
        node_id,
        contact_id,
        data,
    )
    return dict(data, assignment_id=assignment_id)


def outcome(db, cid, run_id, status):
    db.execute(
        """update automation_subject_sends s set data=s.data||%s from automation_step_runs r
        where r.cid=%s and r.id=%s and s.cid=r.cid and s.id=r.data->'subject_assignment'->>'assignment_id'""",
        {"status": status},
        cid,
        run_id,
    )


def record_event(db, cid, run_id, email, kind):
    field = {"send": "delivered_at", "open": "opened_at", "click": "clicked_at"}.get(
        kind
    )
    if not field:
        return False
    # Match the original send recipient, not an arbitrary account/contact input.
    row = db.row(
        """select r.data from automation_step_runs r join automation_enrolments e
        on e.cid=r.cid and e.id=r.enrolment_id where r.cid=%s and r.id=%s and r.node_type='send_email'
        and lower(e.contact_email)=lower(%s)""",
        cid,
        run_id,
        email,
    )
    if not row or not row[0].get("subject_assignment"):
        return False
    assignment_id = row[0]["subject_assignment"]["assignment_id"]
    db.execute(
        """update automation_subject_sends set data=%s||data where cid=%s and id=%s
        and not data ? %s""",
        {field: stamp(), **({"opened_at": stamp()} if kind == "click" else {})},
        cid,
        assignment_id,
        field,
    )
    return True


def variants(raw):
    if not isinstance(raw, list) or not 2 <= len(raw) <= 10:
        error("Choose 2–10 subjects.")
    out = []
    for v in raw:
        if not isinstance(v, dict) or set(v) != {"subject", "weight"}:
            error("Each variant requires only subject and weight.")
        if (
            not isinstance(v["subject"], str)
            or not v["subject"].strip()
            or len(v["subject"]) > 1024
            or any(c in v["subject"] for c in "\r\n")
        ):
            error("Subjects must be nonempty single lines, at most 1024 characters.")
        if type(v["weight"]) is not int or not 0 <= v["weight"] <= 100:
            error("Weights must be integers from 0 to 100; zero pauses a variant.")
        out.append(dict(v, id=shortuuid.uuid(), subject=v["subject"].strip()))
    if not any(v["weight"] for v in out):
        error("At least one variant must receive traffic.")
    if len({v["subject"] for v in out}) != len(out):
        error("Subjects must be distinct.")
    return out


class SubjectTests:
    def on_get(self, req, resp, id, email_id):
        from . import automations as a

        check_noadmin(req)
        db = req.context["db"]
        cid = db.get_cid()
        a._automation_for_email_route(db, id)
        a._get_automation_email(db, cid, id, email_id)
        rows = db.execute(
            "select id,data from automation_subject_tests where cid=%s and automation_id=%s and email_id=%s order by data->>'created' desc",
            cid,
            id,
            email_id,
        ).fetchall()
        req.context["result"] = [
            dict(data, id=eid, statistics=statistics(db, cid, dict(data, id=eid)))
            for eid, data in rows
        ]

    def on_post(self, req, resp, id, email_id):
        from . import automations as a

        check_noadmin(req)
        db = req.context["db"]
        cid = db.get_cid()
        doc = req.context.get("doc")
        if not isinstance(doc, dict):
            error("A JSON object is required.")
        action = doc.get("action")
        with a._locked_automation(db, cid, id) as automation:
            if not automation:
                raise falcon.HTTPForbidden()
            a._get_automation_email(db, cid, id, email_id)
            current = active(db, cid, id, email_id)
            uid = req.context.get("uid")
            if action == "start":
                if set(doc) != {
                    "action",
                    "variants",
                    "maximum_sends",
                    "hours",
                    "metric",
                    "previous_id",
                }:
                    error("Unexpected or missing experiment fields.")
                if (current or {}).get("id") != doc["previous_id"]:
                    raise falcon.HTTPConflict(
                        title="Experiment changed",
                        description="Reload before starting another test.",
                    )
                if current and current["status"] != "selected":
                    error("Choose a winner before starting another experiment.")
                if (
                    type(doc["maximum_sends"]) is not int
                    or not 1 <= doc["maximum_sends"] <= 10000000
                ):
                    error("Maximum sends must be between 1 and 10000000.")
                if (
                    type(doc["hours"]) not in (int, float)
                    or not 1 <= doc["hours"] <= 8760
                ):
                    error("Duration must be between 1 and 8760 hours.")
                if doc["metric"] not in ("or", "ctr"):
                    error("Choose OR or CTR.")
                vv = variants(doc["variants"])
                if current:
                    current["status"] = "archived"
                    save(db, cid, current)
                data = {
                    "created": stamp(),
                    "created_by": uid,
                    "status": "collecting",
                    "version": 1,
                    "variants": vv,
                    "control_id": vv[0]["id"],
                    "maximum_sends": doc["maximum_sends"],
                    "hours": doc["hours"],
                    "metric": doc["metric"],
                    "changes": [],
                }
                eid = shortuuid.uuid()
                db.execute(
                    "insert into automation_subject_tests(id,cid,automation_id,email_id,data) values(%s,%s,%s,%s,%s)",
                    eid,
                    cid,
                    id,
                    email_id,
                    data,
                )
                req.context["result"] = dict(data, id=eid)
                return
            if (
                not current
                or doc.get("experiment_id") != current["id"]
                or doc.get("version") != current["version"]
            ):
                raise falcon.HTTPConflict(
                    title="Experiment changed",
                    description="Reload the experiment before applying changes.",
                )
            if (
                current["status"] in ("collecting", "observing")
                and current.get("deadline")
                and current["deadline"] <= stamp()
                and action != "winner"
            ):
                error(
                    "The deadline has passed. Wait for automatic selection or choose a subject manually."
                )
            fields = {"action", "experiment_id", "version"}
            if action == "winner":
                if set(doc) != fields | {"variant_id"} or doc["variant_id"] not in [
                    v["id"] for v in current["variants"]
                ]:
                    error("Choose an existing subject.")
                if not current.get("decision"):
                    current["decision"] = {
                        "at": stamp(),
                        "reason": "manual_selection",
                        "statistics": statistics(db, cid, current),
                        "winner_id": doc["variant_id"],
                    }
                current.update(status="selected", winner_id=doc["variant_id"])
                release_gates(db, cid, current["id"])
            elif action == "allocation":
                if (
                    set(doc) != fields | {"weights"}
                    or not isinstance(doc["weights"], dict)
                    or set(doc["weights"]) != {v["id"] for v in current["variants"]}
                ):
                    error("Provide every variant weight.")
                if current["status"] != "collecting":
                    error("Allocation can only change while collecting the sample.")
                weights = list(doc["weights"].values())
                if any(
                    type(w) is not int or not 0 <= w <= 100 for w in weights
                ) or not any(weights):
                    error("Use integer weights 0–100 with at least one active subject.")
                for v in current["variants"]:
                    v["weight"] = doc["weights"][v["id"]]
            elif action == "challenger":
                if (
                    set(doc) != fields | {"subject", "weight"}
                    or current["status"] != "collecting"
                    or len(current["variants"]) >= 10
                ):
                    error(
                        "Challengers require a collecting test with fewer than 10 variants."
                    )
                vv = variants(
                    [
                        {"subject": v["subject"], "weight": v["weight"]}
                        for v in current["variants"]
                    ]
                    + [{"subject": doc["subject"], "weight": doc["weight"]}]
                )
                current["variants"].append(vv[-1])
            else:
                error("Unknown experiment action.")
            current["changes"].append({"at": stamp(), "user_id": uid, "request": doc})
            current["version"] += 1
            save(db, cid, current)
            req.context["result"] = current


def delivery(db, run_id, recipient, sender_cid, allow_parent=False):
    row = db.row(
        "select cid from automation_step_runs where id=%s and node_type='send_email'",
        run_id,
    )
    if not row:
        return False
    cid = row[0]
    if cid != sender_cid and not (
        allow_parent
        and db.single("select 1 from companies where id=%s and cid=%s", cid, sender_cid)
    ):
        return False
    return record_event(db, cid, run_id, recipient, "send")
