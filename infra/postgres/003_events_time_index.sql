-- agent_events is queried by TIME, not by goal.
--
-- The only index on the table was idx_events_goal(goal_id, created_at). Its
-- leading column is goal_id, so a query that filters on created_at alone can't
-- use it — and that is exactly what ingest.gather_materials does for the daily
-- summary. Every ingest was a sequential scan over a table that grows with
-- every emitted event and is never pruned; gather_recent(7) issues fourteen of
-- them for the weekly review.
--
-- This matters more now than it used to: the per-prompt vault log is gone, so
-- these time-range queries are the only way the day's activity is recovered.

create index if not exists idx_events_created_at
  on agent_events (created_at desc);

-- artifacts/costs/health are all read back the same way (event_type + time),
-- so give that pair an index too rather than filtering a full scan in memory.
create index if not exists idx_events_type_created_at
  on agent_events (event_type, created_at desc);
