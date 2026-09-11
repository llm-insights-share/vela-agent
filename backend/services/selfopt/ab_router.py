"""Online round-robin A/B assignment (session sticky)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from models import Agent, SelfOptABExperiment
from services.selfopt.config import is_ab_enabled, is_enabled_for_agent, load_selfopt_config


@dataclass
class AbAssignment:
    version_id: Optional[str]
    ab_arm: Optional[str]
    ab_experiment_id: Optional[str]


def assign_for_new_session(db: Session, *, agent: Agent) -> AbAssignment:
    """Return version/arm for a new session. No-op when selfopt disabled."""
    cfg = load_selfopt_config()
    if not is_ab_enabled(cfg) or not is_enabled_for_agent(agent, cfg):
        return AbAssignment(version_id=agent.current_version_id, ab_arm=None, ab_experiment_id=None)

    exp = (
        db.query(SelfOptABExperiment)
        .filter(
            SelfOptABExperiment.agent_id == agent.agent_id,
            SelfOptABExperiment.status == "running",
        )
        .first()
    )
    if not exp:
        return AbAssignment(version_id=agent.current_version_id, ab_arm=None, ab_experiment_id=None)

    # Atomic-ish increment under SQLite (single-writer typical)
    n = int(exp.rr_counter or 0) + 1
    exp.rr_counter = n
    db.add(exp)
    db.flush()

    if n % 2 == 0:
        arm = "control"
        vid = exp.control_version_id
    else:
        arm = "treatment"
        vid = exp.treatment_version_id

    return AbAssignment(version_id=vid, ab_arm=arm, ab_experiment_id=exp.experiment_id)
