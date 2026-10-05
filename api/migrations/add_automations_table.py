def run(db):
    db.execute(
        """
        create table if not exists automations (
            id text primary key,
            cid text not null,
            data jsonb not null
        );
        create index if not exists automations_cid_idx on automations using btree (cid);
    """
    )
