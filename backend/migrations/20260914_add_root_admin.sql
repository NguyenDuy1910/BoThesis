-- Root administration is a durable global capability, not a tenant role.
BEGIN;

ALTER TABLE users
    ADD COLUMN is_root_admin boolean NOT NULL DEFAULT false;

COMMIT;
