-- Replace the binary User lifecycle string with a typed boolean flag.
BEGIN;

ALTER TABLE users ALTER COLUMN status DROP DEFAULT;
ALTER TABLE users
    ALTER COLUMN status TYPE boolean USING (status = 'active');
ALTER TABLE users ALTER COLUMN status SET DEFAULT true;

COMMIT;
