-- Temporal now owns schedules, execution state, overlap control, and history.
-- Connector checkpoints remain on plugin_bindings because they are domain state.
DROP TABLE IF EXISTS sync_runs;
DROP TABLE IF EXISTS schedules;
