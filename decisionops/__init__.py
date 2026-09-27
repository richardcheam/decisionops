"""Small local incident evaluation harness."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateSpec:
    id: str
    name: str
    description: str


CANDIDATES = (
    CandidateSpec("database_failure", "Database failure", "Database connections fail or time out."),
    CandidateSpec("authentication_failure", "Authentication failure", "Access fails because credentials are invalid."),
    CandidateSpec("disk_full", "Disk full", "Storage is exhausted and writes fail."),
    CandidateSpec("healthy", "Healthy", "The service operates normally without errors."),
)
LABELS = tuple(candidate.id for candidate in CANDIDATES)
DESCRIPTIONS = {candidate.id: candidate.description for candidate in CANDIDATES}
