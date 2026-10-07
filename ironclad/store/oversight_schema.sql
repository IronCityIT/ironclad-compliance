-- Ironclad Compliance — the partner and integration register, in MariaDB.
--
-- The replacement for the register's Firestore collections and their
-- history/{revision} subcollections. Applied by `ironclad store init` after
-- schema.sql; safe to re-run. What firestore.rules enforced, this keeps:
--
--   * Every row carries tenant_id and every key leads with it.
--   * oversight_history is the change log: one row per revision holding the
--     record exactly as written. Its key is (tenant, kind, record, revision),
--     so a revision can be written once — two editors working from the same
--     revision cannot both land, the second is refused as stale.
--   * The history row and the record are written in one transaction
--     (MariaDBResultStore.put_oversight), so neither exists without the other.
--   * No foreign key and no cascade on the history, on purpose, as with
--     audit_events: a change log that disappears with the record it
--     describes is not a change log. The application has no UPDATE or DELETE
--     path for it; the production account should hold only SELECT and INSERT
--     on oversight_history, which is what makes that structural (HANDOFF.md).
--     No trigger enforces it here: the NAS server runs with binary logging,
--     where creating a trigger needs SUPER, and `store init` must not.

CREATE TABLE IF NOT EXISTS oversight_records (
  tenant_id   VARCHAR(128) NOT NULL,
  kind        VARCHAR(32)  NOT NULL,
  record_id   VARCHAR(128) NOT NULL,
  revision    INT NOT NULL,
  name        VARCHAR(120) NOT NULL DEFAULT '',
  record      LONGTEXT NOT NULL,
  PRIMARY KEY (tenant_id, kind, record_id),
  KEY idx_oversight_tenant_name (tenant_id, kind, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS oversight_history (
  tenant_id   VARCHAR(128) NOT NULL,
  kind        VARCHAR(32)  NOT NULL,
  record_id   VARCHAR(128) NOT NULL,
  revision    INT NOT NULL,
  updated_by  VARCHAR(128) NOT NULL DEFAULT '',
  updated_at  VARCHAR(64)  NOT NULL DEFAULT '',
  record      LONGTEXT NOT NULL,
  stored_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tenant_id, kind, record_id, revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
