"""Retained-version label enforcement (v4 §5.3, theorem 5).

A retained version is contaminated. It survives only because it cannot reach a
protected sink *right now*, so it must carry a label that keeps it out of
effectful authority for as long as it exists. Retention without this record would
be theorem 5 applied outside its own preconditions.
"""

from __future__ import annotations

from uuid import uuid4

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import LabelEnforcementRecord

BLOCKED_EFFECTS: tuple[str, ...] = ("E2", "E3")


def enforce(
    ledger: ProvenanceLedger,
    run_id: str,
    version_ids: set[str],
    certificate_hash: str,
    *,
    blocked_effects: tuple[str, ...] = BLOCKED_EFFECTS,
) -> list[LabelEnforcementRecord]:
    """Write one enforcement record per retained version, in one transaction.

    Binding each record to ``certificate_hash`` is what makes the label auditable:
    the reason a version is restricted is the certificate that retained it, and if
    that certificate is later invalidated the restriction is still on record.
    """
    records: list[LabelEnforcementRecord] = []
    with ledger.atomic():
        for version_id in sorted(version_ids):
            artifact = ledger.get_artifact(version_id)
            records.append(ledger.append_label_enforcement(LabelEnforcementRecord(
                enforcement_id=f"label_{uuid4().hex[:16]}",
                run_id=run_id,
                version_id=version_id,
                certificate_hash=certificate_hash,
                confidentiality=artifact.confidentiality if artifact else "restricted",
                blocked_effects=blocked_effects,
            )))
    return records
