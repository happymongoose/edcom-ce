def run(db):
    db.execute(
        """
        create table if not exists automation_email_events (
            id text primary key,
            cid text not null,
            contact_id int not null,
            contact_email text not null,
            automation_id text not null,
            automation_email_id text not null,
            enrolment_id text not null,
            send_node_id text not null,
            send_step_run_id text not null,
            event_type text not null,
            ts timestamptz not null,
            data jsonb not null
        );

        create unique index if not exists automation_email_events_open_unique_idx
            on automation_email_events using btree (cid, contact_id, send_step_run_id)
            where event_type = 'open';

        create unique index if not exists automation_email_events_click_unique_idx
            on automation_email_events using btree (
                cid,
                contact_id,
                send_step_run_id,
                coalesce(data->>'link_id', ''),
                coalesce(data->>'link_index', ''),
                coalesce(data->>'updated_ts', '')
            )
            where event_type = 'click';

        create index if not exists automation_email_events_cid_contact_idx
            on automation_email_events using btree (cid, contact_id, ts desc);

        create index if not exists automation_email_events_cid_automation_email_idx
            on automation_email_events using btree (cid, automation_id, automation_email_id, event_type, ts desc);
        """
    )
