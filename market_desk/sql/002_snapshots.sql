-- Screener snapshots for the cloud page (market_desk/screener_snap.py).
-- One row per part (rs, btc, patterns, liq); payload is JSON text.
create table if not exists desk.snapshots (
  name text primary key, ts bigint, payload text);
grant select, insert, update, delete on desk.snapshots to desk_writer;
grant select on desk.snapshots to desk_viewer;
