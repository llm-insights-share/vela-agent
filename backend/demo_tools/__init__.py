"""Importable wrappers for demo local_python tools (demos/*/tools)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str, file_path: Path) -> ModuleType:
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_audit = _load_module(
    "vela_demo_audit_tools",
    _REPO_ROOT / "demos" / "audit" / "tools" / "audit_tools.py",
)
_hr = _load_module(
    "vela_demo_hr_tools",
    _REPO_ROOT / "demos" / "hr" / "tools" / "hr_tools.py",
)
_office = _load_module(
    "vela_demo_office_tools",
    _REPO_ROOT / "demos" / "office" / "tools" / "office_tools.py",
)
_pm = _load_module(
    "vela_demo_pm_tools",
    _REPO_ROOT / "demos" / "pm" / "tools" / "pm_tools.py",
)

# Audit exports
audit_lookup_employee = _audit.audit_lookup_employee
audit_list_oa_docs = _audit.audit_list_oa_docs
audit_query_gl = _audit.audit_query_gl
audit_query_related_party = _audit.audit_query_related_party
audit_list_contracts = _audit.audit_list_contracts
audit_list_capex = _audit.audit_list_capex
audit_submit_engagement_draft = _audit.audit_submit_engagement_draft

# HR exports
hr_search_employees = _hr.hr_search_employees
hr_get_employee = _hr.hr_get_employee
hr_get_leave_balance = _hr.hr_get_leave_balance
hr_list_open_requisitions = _hr.hr_list_open_requisitions
hr_get_candidate = _hr.hr_get_candidate
hr_create_interview_note = _hr.hr_create_interview_note

# Office exports
office_search_employees = _office.office_search_employees
office_list_rooms = _office.office_list_rooms
office_list_meetings = _office.office_list_meetings
office_get_meeting = _office.office_get_meeting
office_list_action_items = _office.office_list_action_items
office_list_travel = _office.office_list_travel
office_get_expense_claim = _office.office_get_expense_claim
office_list_seal_requests = _office.office_list_seal_requests
office_list_supplies = _office.office_list_supplies
office_submit_minutes_draft = _office.office_submit_minutes_draft
office_submit_expense_review_note = _office.office_submit_expense_review_note

# PM exports
pm_list_products = _pm.pm_list_products
pm_list_roadmap = _pm.pm_list_roadmap
pm_list_backlog = _pm.pm_list_backlog
pm_list_competitors = _pm.pm_list_competitors
pm_get_competitor_matrix = _pm.pm_get_competitor_matrix
pm_list_feedback = _pm.pm_list_feedback
pm_list_interviews = _pm.pm_list_interviews
pm_query_metrics = _pm.pm_query_metrics
pm_query_funnel = _pm.pm_query_funnel
pm_list_events = _pm.pm_list_events
pm_list_experiments = _pm.pm_list_experiments
pm_list_prds = _pm.pm_list_prds
pm_submit_prd_draft = _pm.pm_submit_prd_draft
