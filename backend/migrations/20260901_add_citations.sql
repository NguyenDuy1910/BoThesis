-- Persist canonical citation geometry in PostgreSQL while keeping retrieval
-- text and lightweight citation locators in the vector index.
BEGIN;

CREATE TABLE citations (
    id uuid NOT NULL,
    item_id uuid NOT NULL,
    chunk_id text NOT NULL,
    section_path text[] DEFAULT '{}'::text[] NOT NULL,
    anchor text,
    page_start integer,
    page_end integer,
    spans jsonb DEFAULT '[]'::jsonb NOT NULL,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_citations PRIMARY KEY (id),
    CONSTRAINT fk_citations_item_id_items
        FOREIGN KEY(item_id) REFERENCES items (id),
    CONSTRAINT uq_citations_item_id_chunk_id UNIQUE (item_id, chunk_id),
    CONSTRAINT ck_citations_page_start_is_valid
        CHECK (page_start IS NULL OR page_start >= 1),
    CONSTRAINT ck_citations_page_end_is_valid
        CHECK (page_end IS NULL OR page_end >= 1),
    CONSTRAINT ck_citations_page_range_is_valid
        CHECK (page_start IS NULL OR page_end IS NULL OR page_end >= page_start),
    CONSTRAINT ck_citations_spans_is_array CHECK (jsonb_typeof(spans) = 'array')
);

CREATE INDEX ix_citations_item_id_deleted_at
    ON citations (item_id, deleted_at);

COMMIT;
