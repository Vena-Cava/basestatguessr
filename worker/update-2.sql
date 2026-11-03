-- Update for databases created before the timer and admin features. Run once:
--   npx wrangler d1 execute basestatguessr --remote --file=update-2.sql
ALTER TABLE runs ADD COLUMN round_started INTEGER;
ALTER TABLE scores ADD COLUMN removed INTEGER NOT NULL DEFAULT 0;
