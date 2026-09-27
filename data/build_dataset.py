"""One-time authoring helper; the checked-in JSONL is the evaluation input."""
import json
from pathlib import Path

CORE = {
"database_failure": [
("Database connections are timing out and requests fail.", "active database connection timeout"),
("The application cannot connect to PostgreSQL; connection refused.", "database connection failure"),
("Queries to the database are failing with repeated timeouts.", "current query and database timeouts"),
("The database connection pool is exhausted, so requests cannot run.", "database connection pool exhausted"),
("MySQL is unavailable and all database reads fail.", "database unavailable and reads fail"),
("The service reports SQL connection errors on every request.", "current SQL connection errors"),
("Database writes fail because the server drops connections.", "database connection loss breaks writes"),
("Connection to the database fails during application startup.", "startup database connection failure"),
],
"authentication_failure": [
("Users cannot sign in because their passwords are rejected.", "credentials are rejected"),
("The API returns 401 unauthorized for valid service requests.", "current unauthorized responses"),
("Authentication fails because the access token has expired.", "expired token prevents access"),
("The login service rejects the supplied credentials.", "login credentials rejected"),
("Requests fail with an invalid API key error.", "invalid credential blocks requests"),
("Employees are denied access after the identity provider rejects login.", "identity provider rejects authentication"),
("The application reports an authentication failure for every user.", "explicit authentication failures"),
("The session cannot be established because the password is invalid.", "invalid password prevents session"),
],
"disk_full": [
("The disk is full and the service cannot write log files.", "full disk blocks writes"),
("Writes fail with no space left on the device.", "filesystem reports no free space"),
("The data volume is full, so new uploads fail.", "full volume blocks uploads"),
("Storage is exhausted and database snapshots cannot be saved.", "exhausted storage blocks snapshots"),
("The filesystem has no free space and temporary file creation fails.", "no free filesystem space"),
("The server reports disk full errors while writing data.", "explicit disk full write errors"),
("A full storage partition prevents the application from persisting results.", "full partition blocks persistence"),
("The log volume ran out of space and writes are rejected.", "log volume space exhaustion"),
],
"healthy": [
("All health checks pass and the service is operating normally.", "all checks pass and normal operation"),
("The application is healthy with no current errors.", "explicit healthy state"),
("Requests complete successfully and the service is up.", "successful requests and service up"),
("Monitoring reports normal operation across all components.", "monitoring confirms normal operation"),
("The service is running normally and dashboards show no errors.", "normal service with no errors"),
("All endpoints respond successfully; no incidents are active.", "successful endpoints and no incident"),
("The deployment is stable and every readiness check passes.", "stable deployment and passing checks"),
("Users can access the service and current metrics are normal.", "normal metrics and user access"),
]}
CHALLENGE = [
("healthy", "negation", "Database connections are not failing; requests are succeeding.", "Negation explicitly denies a current database failure."),
("healthy", "negation", "The login service is healthy and is not rejecting credentials.", "The credential rejection is negated."),
("healthy", "negation", "There is no disk full alert and writes are completing.", "The disk-full cue is explicitly denied."),
("healthy", "negation", "The service is not healthy: database connections time out.", "A current database failure is explicit despite the negated health claim."),
("healthy", "historical", "Database timeouts occurred yesterday, but connections work now.", "The failure is historical and explicitly resolved; no current issue is labeled."),
("healthy", "historical", "The disk was full last week; it has been cleared and writes now succeed.", "The past fault is resolved and current writes succeed."),
("healthy", "historical", "An invalid token caused errors earlier; current logins succeed.", "Only historical authentication errors are reported; current state is successful."),
("database_failure", "ambiguous_evidence", "Some requests are slow, but there are no connection errors.", "Slowness alone does not identify a database failure; needs review."),
("disk_full", "ambiguous_evidence", "Storage usage is high, though writes still work and no alert fired.", "High utilization does not establish exhausted storage."),
("authentication_failure", "ambiguous_evidence", "A few users report trouble accessing the page.", "Access trouble has no credential-specific evidence; needs review."),
("database_failure", "multiple_faults", "Database connections time out, and writes fail because the disk is full.", "Two simultaneous categories are explicit; needs review."),
("authentication_failure", "multiple_faults", "Login credentials are rejected while the database is unavailable.", "Two simultaneous categories are explicit; needs review."),
(None, "unrelated", "Please schedule a team lunch for Friday.", "Unrelated request provides no service condition; needs review."),
(None, "unrelated", "The office printer needs a new toner cartridge.", "Non-incident input is outside the four labels; needs review."),
(None, "insufficient_evidence", "We saw an issue earlier, but no details were recorded.", "No category or current state can be inferred."),
(None, "insufficient_evidence", "Users say the app feels odd, with no error or symptom details.", "Subjective vague report lacks classifiable evidence."),
]

rows = []
for label, examples in CORE.items():
    for index, (text, rationale) in enumerate(examples, 1):
        rows.append({"id": f"core-{label}-{index:02d}", "text": text, "tags": ["unambiguous", label], "expected_label": label, "needs_review": False, "rationale": rationale})
for index, (label, tag, text, rationale) in enumerate(CHALLENGE, 1):
    rows.append({"id": f"challenge-{index:02d}", "text": text, "tags": ["challenge", tag], "expected_label": None if tag in {"unrelated", "insufficient_evidence", "ambiguous_evidence", "multiple_faults"} else label, "needs_review": tag in {"unrelated", "insufficient_evidence", "ambiguous_evidence", "multiple_faults"}, "rationale": rationale})
path = Path(__file__).with_name("incidents.jsonl")
path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
