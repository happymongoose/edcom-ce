def run(db):
    db.execute("""
        create table if not exists automation_subject_tests (
            id text primary key, cid text not null, automation_id text not null,
            email_id text not null, data jsonb not null
        );
        create index if not exists automation_subject_tests_email_idx
            on automation_subject_tests(cid, automation_id, email_id);
        create unique index if not exists automation_subject_tests_active_idx
            on automation_subject_tests(cid, automation_id, email_id)
            where data->>'status' in ('collecting', 'observing', 'selected');
        create table if not exists automation_subject_sends (
            id text primary key, cid text not null, automation_id text not null,
            email_id text not null, experiment_id text not null, enrolment_id text not null,
            node_id text not null, contact_id bigint not null, data jsonb not null
        );
        create index if not exists automation_subject_sends_experiment_idx
            on automation_subject_sends(cid, experiment_id);
        create index if not exists automation_subject_sends_retry_idx
            on automation_subject_sends(cid, enrolment_id, node_id);
    """)

    for table, column, target, name in (
        (
            "automation_subject_tests",
            "automation_id",
            "automations",
            "subject_tests_automation_fk",
        ),
        (
            "automation_subject_tests",
            "email_id",
            "automation_emails",
            "subject_tests_email_fk",
        ),
        (
            "automation_subject_sends",
            "experiment_id",
            "automation_subject_tests",
            "subject_sends_test_fk",
        ),
    ):
        if not db.single("select 1 from pg_constraint where conname=%s", name):
            db.execute(
                "alter table "
                + table
                + " add constraint "
                + name
                + " foreign key ("
                + column
                + ") references "
                + target
                + "(id) on delete cascade"
            )
