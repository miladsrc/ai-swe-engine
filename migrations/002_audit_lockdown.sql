-- 002_audit_lockdown.sql — DB-level enforcement of audit_log append-only (B4).
--
-- The "append-only" property of the audit log was previously enforced only by
-- convention (see api/audit.py header comment). These triggers make UPDATE and
-- DELETE on audit_log fail at the database level, so even a compromised or
-- buggy application process cannot rewrite governance history.
--
-- NOTE 1: also apply role-level revocation in production, e.g.:
--     REVOKE UPDATE, DELETE ON audit_log FROM sase_app;
--     GRANT INSERT, SELECT ON audit_log TO sase_app;
-- Triggers defend the table; role grants defend against a future code path
-- that drops or replaces the triggers.
--
-- NOTE 2: docker-entrypoint-initdb.d only runs scripts on FIRST boot of an
-- empty volume. For an EXISTING volume, apply this file manually, e.g.:
--     docker exec -i <pg-container> psql -U sase -d sase < migrations/002_audit_lockdown.sql

CREATE FUNCTION audit_log_no_rewrite() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_no_rewrite();

CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_no_rewrite();
