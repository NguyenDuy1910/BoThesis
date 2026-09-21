-- Add optional first-party credentials. Existing Google identities remain
-- valid and keep password_hash NULL until a local credential is created.
BEGIN;

ALTER TABLE users
    ADD COLUMN username varchar(64),
    ADD COLUMN password_hash varchar(256);

CREATE UNIQUE INDEX uq_users_username
    ON users (lower(username))
    WHERE username IS NOT NULL;

ALTER TABLE access_sessions
    DROP CONSTRAINT ck_access_sessions_access_session_auth_method_is_valid,
    ADD CONSTRAINT ck_access_sessions_access_session_auth_method_is_valid
    CHECK (authentication_method IN ('anonymous', 'oidc', 'saml', 'password', 'internal'));

COMMIT;
