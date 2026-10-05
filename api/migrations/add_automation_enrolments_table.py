def run(db):
    db.execute(
        """
        create table if not exists automation_enrolments (
            id text primary key,
            cid text not null,
            automation_id text not null,
            contact_id int not null,
            contact_email text not null,
            data jsonb not null
        );
        create index if not exists automation_enrolments_cid_automation_idx
            on automation_enrolments using btree (cid, automation_id);
        create index if not exists automation_enrolments_cid_automation_contact_idx
            on automation_enrolments using btree (cid, automation_id, contact_id);
    """
    )
