-- BaseStatGuessr database. Run once:  npx wrangler d1 execute basestatguessr --remote --file=schema.sql
CREATE TABLE IF NOT EXISTS runs (
  id        TEXT PRIMARY KEY,
  mode      TEXT NOT NULL,
  seed      INTEGER NOT NULL,
  idx       INTEGER NOT NULL,
  misses    INTEGER NOT NULL,
  lives     INTEGER NOT NULL,
  score     INTEGER NOT NULL,
  rounds    INTEGER NOT NULL,
  perfect   INTEGER NOT NULL,
  status    TEXT NOT NULL,
  created   INTEGER NOT NULL,
  updated   INTEGER NOT NULL,
  submitted INTEGER NOT NULL DEFAULT 0,
  round_started INTEGER
);
CREATE TABLE IF NOT EXISTS scores (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  mode    TEXT NOT NULL,
  name    TEXT NOT NULL,
  score   INTEGER NOT NULL,
  rounds  INTEGER NOT NULL,
  perfect INTEGER NOT NULL,
  created INTEGER NOT NULL,
  run_id  TEXT UNIQUE,
  removed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS scores_board ON scores (mode, score DESC, created ASC);
