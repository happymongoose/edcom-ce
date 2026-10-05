"""Persistent automation exclusions and exit bookkeeping; no external actions."""

def matching_rule(db, cid, contact_id, published):
    from . import automations as a
    raw_rules = (published or {}).get("exit_rules", [])
    if raw_rules == []:
        return None
    rules = a._prepare_exit_rules(raw_rules)
    # A removed contact is not a match for an absence rule.
    if not db.single(f'select contact_id from contacts."contacts_{cid}" where contact_id=%s', contact_id):
        return None
    for index, rule in enumerate(rules):
        if "tags" in rule:
            present = bool(db.single(f'''select 1 from contacts."contact_values_{cid}"
                where contact_id=%s and type='tag' and value=any(%s) limit 1''', contact_id, rule["tags"]))
        else:
            # A deleted/foreign list must not become an accidental absence match.
            if any(db.lists.get(lid) is None for lid in rule["list_ids"]):
                a._validation_error("A published exit rule references a missing contact list. Review the automation.")
            present = bool(db.single(f'''select 1 from contacts."contact_lists_{cid}"
                where contact_id=%s and list_id=any(%s) limit 1''', contact_id, rule["list_ids"]))
        if present == (rule["type"] in ("has_tag", "in_list")):
            return {"rule_index": index, "rule_type": rule["type"]}
    return None


def reason(automation, previous, match, source, **extra):
    from . import automations as a
    return {"created": a._utc_now(), "source": source, **match,
        "published_revision": automation.get("published_revision"),
        "previous_status": previous.get("running_status") if previous.get("status") == "running" else previous.get("status"),
        "node_id": previous.get("current_node_id"), **extra}


def exit_patch(previous, metadata):
    from . import automations as a
    return {**a._claim_clear_patch(), **a._retry_clear_patch(),
        "status": "exited", "modified": a._utc_now(), "wake_at": None, "wait": None,
        "paused_at": None, "resumed_at": None, "pending_rule_exit": None, "subject_gate": None,
        "current_node_id": previous.get("current_node_id"), "exit_metadata": metadata}


def apply(db, cid, automation, enrolment_id, source, published=None, **extra):
    """Caller holds automation lock. A claim is never cleared by an observer."""
    from . import automations as a
    row = db.row("select contact_id,data from automation_enrolments where cid=%s and automation_id=%s and id=%s for update",
        cid, automation["id"], enrolment_id)
    if row is None:
        return None
    contact_id, previous = row
    rules_snapshot = published if published is not None else automation.get("published")
    if not previous.get("pending_rule_exit") and not (rules_snapshot or {}).get("exit_rules"):
        return None
    if previous.get("status") in a.TERMINAL_ENROLMENT_STATUSES:
        return None
    if previous.get("status") not in a.ACTIVE_ENROLMENT_STATUSES:
        a._validation_error("Exit rules cannot repair a malformed enrolment state.")
    metadata = previous.get("pending_rule_exit")
    if not metadata:
        match = matching_rule(db, cid, contact_id, published if published is not None else automation.get("published"))
        if match is None:
            return None
        metadata = reason(automation, previous, match, source, **extra)
    claimed = previous.get("claim_token") or previous.get("status") == "running"
    patch = {"pending_rule_exit": metadata} if claimed else exit_patch(previous, metadata)
    db.execute("update automation_enrolments set data=data||%s where cid=%s and id=%s", patch, cid, enrolment_id)
    return "pending" if claimed else "exited"


def finish_claim(db, cid, automation_id, enrolment_id, token, update):
    """Merge under the same lock as exit observation; no lost pending decision."""
    from . import automations as a
    with a._locked_automation(db, cid, automation_id) as automation:
        row = db.row("select contact_id,data from automation_enrolments where cid=%s and automation_id=%s and id=%s for update",
            cid, automation_id, enrolment_id)
        if row is None or row[1].get("claim_token") != token:
            return 0
        contact_id, previous = row
        metadata = previous.get("pending_rule_exit")
        if not metadata:
            try:
                match = matching_rule(db, cid, contact_id, automation.get("published"))
            except a.falcon.HTTPBadRequest as error:
                # A referenced list can disappear during an action. Release the
                # claim into a hold rather than strand it or run another step.
                match = None
                update = {**update, "status": "held", "current_node_id": previous.get("current_node_id"),
                    "last_error": {"title": error.title, "description": error.description}}
            if match:
                metadata = reason(automation, previous, match, "action_finished")
        if metadata:
            update = {**update, **exit_patch(previous, metadata)}
        return db.execute("update automation_enrolments set data=data||%s where cid=%s and id=%s and data->>'claim_token'=%s",
            update, cid, enrolment_id, token).rowcount


def cohort(db, cid, automation, published):
    from . import automations as a
    if not published.get("exit_rules"):
        # Pending decisions are still binding after rules are removed.
        condition = "and data->'pending_rule_exit' is not null and data->'pending_rule_exit' <> 'null'::jsonb"
    else:
        condition = ""
    matches = []
    for eid, contact_id, previous in db.execute("""select id,contact_id,data from automation_enrolments
        where cid=%s and automation_id=%s and data->>'status'=any(%s) """ + condition + " order by id",
        cid, automation["id"], list(a.ACTIVE_ENROLMENT_STATUSES)).fetchall():
        match = previous.get("pending_rule_exit") or matching_rule(db, cid, contact_id, published)
        if match:
            matches.append((eid, previous, match))
    return matches


def process_event(db, cid, event):
    """Exit processing is independent of entry depth/cooldown/self-origin rules."""
    from . import automations as a
    field = "tags" if event.get("event_type") in ("tag_added", "tag_removed") else "list_ids" if event.get("event_type") in ("list_joined", "list_left") else None
    if not field:
        return 0
    value = event.get("tag") if field == "tags" else event.get("list_id")
    ids = [row[0] for row in db.execute("""select id from automations where cid=%s
        and data->>'status' in ('published','paused') and exists
        (select 1 from jsonb_array_elements(coalesce(data->'published'->'exit_rules','[]'::jsonb)) r
         where r->%s ? %s) order by id""", cid, field, value).fetchall()]
    changed = 0
    for aid in ids:
        with a._locked_automation(db, cid, aid) as automation:
            if not automation:
                continue
            rows = db.execute("""select id from automation_enrolments where cid=%s and automation_id=%s
                and contact_id=%s and data->>'status'=any(%s) order by id""",
                cid, aid, event["contact_id"], list(a.ACTIVE_ENROLMENT_STATUSES)).fetchall()
            for (eid,) in rows:
                if apply(db, cid, automation, eid, "contact_change", event_id=event.get("id")):
                    changed += 1
    return changed


def process_pending(db, cid, limit=100):
    from . import automations as a
    done = failed = 0
    # Each event and its exits commit together. Failures stay pending with a
    # bounded retry delay; duplicate workers use SKIP LOCKED.
    for _ in range(limit):
        eid = None
        try:
            with db.transaction():
                row = db.row("""select id,contact_id,event_type,data from automation_trigger_events
                    where cid=%s and data->>'exit_status'='pending'
                      and (data->>'exit_retry_at' is null or (data->>'exit_retry_at')::timestamptz <= now())
                    order by ts,id limit 1 for update skip locked""", cid)
                if row is None:
                    break
                eid, contact_id, event_type, data = row
                count = process_event(db, cid, {**data, "id": eid, "contact_id": contact_id, "event_type": event_type})
                db.execute("""update automation_trigger_events set data=data||jsonb_build_object(
                    'exit_status','processed','exit_processed_at',%s::text,'exit_count',%s) where cid=%s and id=%s""",
                    a._utc_now(), count, cid, eid)
            done += 1
        except Exception:
            a.log.exception("Automation exit event failed cid=%s event_id=%s", cid, eid)
            failed += 1
            if eid:
                db.execute("""update automation_trigger_events set data=data||jsonb_build_object(
                    'exit_retry_at',now()+interval '1 minute') where cid=%s and id=%s and data->>'exit_status'='pending'""", cid, eid)
            else:
                break
    return {"processed": done, "failed": failed}
