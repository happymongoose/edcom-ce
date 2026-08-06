def run(db):
    db.execute(
        """
        create table if not exists automation_segment_trigger_snapshots (
            id text primary key,
            cid text not null,
            segment_id text not null,
            status text not null,
            hashlimit int not null default 1,
            last_hashval int,
            last_started_at timestamptz,
            last_completed_at timestamptz,
            claimed_at timestamptz,
            claim_token text,
            data jsonb not null
        );
        create unique index if not exists automation_segment_trigger_snapshots_cid_segment_idx
            on automation_segment_trigger_snapshots using btree (cid, segment_id);
        create index if not exists automation_segment_trigger_snapshots_cid_status_claimed_idx
            on automation_segment_trigger_snapshots using btree (cid, status, claimed_at);

        create table if not exists automation_segment_trigger_members (
            cid text not null,
            segment_id text not null,
            contact_id int not null,
            contact_email text not null,
            bucket int not null,
            first_seen_at timestamptz not null,
            last_seen_at timestamptz not null,
            scan_id text,
            primary key (cid, segment_id, contact_id)
        );
        create index if not exists automation_segment_trigger_members_cid_segment_bucket_idx
            on automation_segment_trigger_members using btree (cid, segment_id, bucket);
        create index if not exists automation_segment_trigger_members_cid_contact_idx
            on automation_segment_trigger_members using btree (cid, contact_id);
        """
    )
