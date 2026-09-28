CREATE TABLE tasks (
    id             uuid                        NOT NULL,
    repository_url text                        NOT NULL,
    prompt         text                        NOT NULL,
    status         varchar(20)                 NOT NULL,
    worker_id      varchar(100),
    result         text,
    error          text,
    created_at     timestamp without time zone NOT NULL,
    started_at     timestamp without time zone,
    completed_at   timestamp without time zone,
    CONSTRAINT tasks_pkey PRIMARY KEY (id)
);
