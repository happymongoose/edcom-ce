def run(db):
    db.execute(
        """
        create table if not exists debug_email_backends (
            id text primary key,
            cid text not null,
            data jsonb not null
        );

        create index if not exists debug_email_backends_cid_idx
            on debug_email_backends using btree (cid);

        create table if not exists debug_email_logs (
            id text primary key,
            cid text not null,
            ts timestamptz not null,
            data jsonb not null
        );

        create index if not exists debug_email_logs_cid_ts_idx
            on debug_email_logs using btree (cid, ts desc);
        """
    )
