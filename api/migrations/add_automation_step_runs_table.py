def run(db):
    db.execute(
        """
        create table if not exists automation_step_runs (
            id text primary key,
            cid text not null,
            automation_id text not null,
            enrolment_id text not null,
            contact_id int not null,
            node_id text not null,
            node_type text not null,
            data jsonb not null
        );
        create index if not exists automation_step_runs_cid_automation_enrolment_idx
            on automation_step_runs using btree (cid, automation_id, enrolment_id);
        create index if not exists automation_step_runs_cid_contact_idx
            on automation_step_runs using btree (cid, contact_id);
    """
    )
