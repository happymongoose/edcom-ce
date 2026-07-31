def run(db):
    db.execute(
        """
        create table if not exists automation_trigger_events (
            id text primary key,
            cid text not null,
            contact_id int not null,
            contact_email text not null,
            event_type text not null,
            ts timestamptz not null,
            data jsonb not null
        );

        create index if not exists automation_trigger_events_cid_status_ts_idx
            on automation_trigger_events using btree (cid, (data->>'status'), ts);
        create index if not exists automation_trigger_events_cid_contact_type_ts_idx
            on automation_trigger_events using btree (cid, contact_id, event_type, ts desc);
    """
    )
