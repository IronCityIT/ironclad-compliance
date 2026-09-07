-- Ironclad Compliance — MariaDB schema.
--
-- The store of record for assessment results once Firestore is retired.
-- Applied by `ironclad store init`; safe to re-run.
--
-- Three properties are structural here rather than enforced by the application,
-- because an application is one bug away from forgetting them and a schema is
-- not:
--
--   * Every table carries tenant_id, and every index leads with it. A query
--     that forgets the tenant is a full scan rather than a quiet leak of one
--     client's data into another's report.
--   * Child rows cascade from their assessment. Re-storing an assessment
--     replaces exactly its own rows and cannot orphan detail.
--   * audit_events is unique on (tenant_id, assessment_id, event_id) so an
--     event can be inserted twice and stored once. The chain's integrity comes
--     from prev_hash/hash, which are stored verbatim and never recomputed here.
--
-- Character set is utf8mb4 throughout: a client name, a control rationale and a
-- justification are free text written by people.

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id       VARCHAR(128) NOT NULL,
  name            VARCHAR(255) NOT NULL DEFAULT '',
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assessments (
  assessment_id     VARCHAR(255) NOT NULL,
  tenant_id         VARCHAR(128) NOT NULL,
  framework_id      VARCHAR(64)  NOT NULL DEFAULT '',
  framework_name    VARCHAR(255) NOT NULL DEFAULT '',
  framework_version VARCHAR(64)  NOT NULL DEFAULT '',
  assessment_type   VARCHAR(32)  NOT NULL DEFAULT 'full',
  status            VARCHAR(32)  NOT NULL DEFAULT 'completed',
  engine_version    VARCHAR(32)  NOT NULL DEFAULT '',
  contract_version  VARCHAR(32)  NOT NULL DEFAULT '',
  started_at        VARCHAR(64)  NOT NULL DEFAULT '',
  completed_at      VARCHAR(64)  NOT NULL DEFAULT '',
  readiness_score   DECIMAL(5,2) NOT NULL DEFAULT 0.00,
  total_controls    INT NOT NULL DEFAULT 0,
  compliant         INT NOT NULL DEFAULT 0,
  partial           INT NOT NULL DEFAULT 0,
  gap               INT NOT NULL DEFAULT 0,
  accepted_risk     INT NOT NULL DEFAULT 0,
  not_applicable    INT NOT NULL DEFAULT 0,
  pending           INT NOT NULL DEFAULT 0,
  evidence_artifacts INT NOT NULL DEFAULT 0,
  stale_artifacts   INT NOT NULL DEFAULT 0,
  modules_run       LONGTEXT NOT NULL,
  warnings          LONGTEXT NOT NULL,
  failed_modules    LONGTEXT NOT NULL,
  consensus         LONGTEXT NOT NULL,
  method            LONGTEXT NOT NULL,
  module_output     LONGTEXT NOT NULL,
  audit_chain_head  VARCHAR(128) NOT NULL DEFAULT '',
  report_url        VARCHAR(512) NOT NULL DEFAULT '',
  stored_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (assessment_id),
  KEY idx_assessments_tenant (tenant_id, started_at),
  CONSTRAINT fk_assessments_tenant FOREIGN KEY (tenant_id)
    REFERENCES tenants (tenant_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assessment_controls (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  assessment_id   VARCHAR(255) NOT NULL,
  tenant_id       VARCHAR(128) NOT NULL,
  control_id      VARCHAR(128) NOT NULL,
  control_name    VARCHAR(255) NOT NULL DEFAULT '',
  status          VARCHAR(32)  NOT NULL DEFAULT '',
  rationale       TEXT NOT NULL,
  points_covered  INT NOT NULL DEFAULT 0,
  points_total    INT NOT NULL DEFAULT 0,
  coverage        DECIMAL(6,4) NOT NULL DEFAULT 0.0000,
  confidence      DECIMAL(6,4) NOT NULL DEFAULT 0.0000,
  weight          DECIMAL(6,3) NOT NULL DEFAULT 1.000,
  evidence_count  INT NOT NULL DEFAULT 0,
  exception_id    VARCHAR(64) NOT NULL DEFAULT '',
  assessed_at     VARCHAR(64) NOT NULL DEFAULT '',
  assessed_by     VARCHAR(128) NOT NULL DEFAULT '',
  notes           LONGTEXT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_control_per_assessment (assessment_id, control_id),
  KEY idx_controls_tenant_status (tenant_id, status),
  CONSTRAINT fk_controls_assessment FOREIGN KEY (assessment_id)
    REFERENCES assessments (assessment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- References and checksums. The evidence itself never enters the database:
-- artifacts stay in the client's own storage and this is the index that proves
-- which artifact supported which control at what time.
CREATE TABLE IF NOT EXISTS control_evidence (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  assessment_id  VARCHAR(255) NOT NULL,
  tenant_id      VARCHAR(128) NOT NULL,
  control_id     VARCHAR(128) NOT NULL,
  artifact_id    VARCHAR(128) NOT NULL,
  method         VARCHAR(32)  NOT NULL DEFAULT '',
  relevance      DECIMAL(6,4) NOT NULL DEFAULT 0.0000,
  linked_by      VARCHAR(128) NOT NULL DEFAULT '',
  linked_at      VARCHAR(64)  NOT NULL DEFAULT '',
  matched_terms  LONGTEXT NOT NULL,
  note           TEXT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_link (assessment_id, control_id, artifact_id),
  KEY idx_evidence_tenant_artifact (tenant_id, artifact_id),
  CONSTRAINT fk_evidence_assessment FOREIGN KEY (assessment_id)
    REFERENCES assessments (assessment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- item_id is deterministic on (tenant, control), so the same control produces
-- the same id in every assessment of that tenant. It is therefore NOT a global
-- primary key: a second assessment for the same client would collide with the
-- first. An item belongs to the assessment that raised it.
CREATE TABLE IF NOT EXISTS remediation_items (
  item_id        VARCHAR(128) NOT NULL,
  assessment_id  VARCHAR(255) NOT NULL,
  tenant_id      VARCHAR(128) NOT NULL,
  control_id     VARCHAR(128) NOT NULL DEFAULT '',
  control_name   VARCHAR(255) NOT NULL DEFAULT '',
  title          VARCHAR(255) NOT NULL DEFAULT '',
  severity       VARCHAR(32)  NOT NULL DEFAULT '',
  priority       INT NOT NULL DEFAULT 0,
  status         VARCHAR(32)  NOT NULL DEFAULT '',
  owner          VARCHAR(128) NOT NULL DEFAULT '',
  due_date       VARCHAR(64)  NOT NULL DEFAULT '',
  guidance       TEXT NOT NULL,
  evidence_gap   LONGTEXT NOT NULL,
  exception_id   VARCHAR(64) NOT NULL DEFAULT '',
  source         VARCHAR(64) NOT NULL DEFAULT '',
  created_at     VARCHAR(64) NOT NULL DEFAULT '',
  PRIMARY KEY (assessment_id, item_id),
  KEY idx_remediation_tenant (tenant_id, priority, due_date),
  KEY idx_remediation_item (item_id),
  CONSTRAINT fk_remediation_assessment FOREIGN KEY (assessment_id)
    REFERENCES assessments (assessment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS findings (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  assessment_id  VARCHAR(255) NOT NULL,
  tenant_id      VARCHAR(128) NOT NULL,
  ordinal        INT NOT NULL DEFAULT 0,
  module         VARCHAR(64)  NOT NULL DEFAULT '',
  severity       VARCHAR(32)  NOT NULL DEFAULT '',
  title          VARCHAR(255) NOT NULL DEFAULT '',
  target         VARCHAR(255) NOT NULL DEFAULT '',
  detail         TEXT NOT NULL,
  evidence       LONGTEXT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_finding (assessment_id, ordinal),
  KEY idx_findings_tenant_severity (tenant_id, severity),
  CONSTRAINT fk_findings_assessment FOREIGN KEY (assessment_id)
    REFERENCES assessments (assessment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Append-only. No ON DELETE CASCADE and no foreign key to assessments on
-- purpose: an audit trail that disappears when the thing it describes is
-- deleted is not an audit trail. The unique key is what makes an insert
-- idempotent; prev_hash and hash are stored exactly as recorded so the chain
-- verifies out of the database as it verified going in.
CREATE TABLE IF NOT EXISTS audit_events (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id      VARCHAR(128) NOT NULL,
  assessment_id  VARCHAR(255) NOT NULL DEFAULT '',
  event_id       VARCHAR(64)  NOT NULL,
  ordinal        INT NOT NULL DEFAULT 0,
  actor          VARCHAR(128) NOT NULL DEFAULT '',
  action         VARCHAR(128) NOT NULL DEFAULT '',
  object_type    VARCHAR(64)  NOT NULL DEFAULT '',
  object_id      VARCHAR(255) NOT NULL DEFAULT '',
  at             VARCHAR(64)  NOT NULL DEFAULT '',
  metadata       LONGTEXT NOT NULL,
  prev_hash      VARCHAR(128) NOT NULL DEFAULT '',
  hash           VARCHAR(128) NOT NULL DEFAULT '',
  stored_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_audit_event (tenant_id, assessment_id, event_id),
  KEY idx_audit_tenant (tenant_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
