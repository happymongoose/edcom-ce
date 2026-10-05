def run(db):
    db.execute(
        """
        create table if not exists automation_emails (
            id text primary key,
            cid text not null,
            automation_id text not null,
            data jsonb not null
        );
        create index if not exists automation_emails_cid_automation_idx
            on automation_emails using btree (cid, automation_id);
    """
    )
