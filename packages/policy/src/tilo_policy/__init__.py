"""tilo_policy — the deterministic policy engine (PRD 10.4). A model never decides authorisation;
T3 always needs a person. Public API: packages/policy/tests/API.md."""

from .crossref import check_entry as check_entry
from .decide import Decision as Decision
from .decide import Proposal as Proposal
from .decide import decide as decide
from .gate import open_gate as open_gate
from .tiers import Assessment as Assessment
from .tiers import PolicyConfigError as PolicyConfigError
from .tiers import RiskTable as RiskTable
from .tiers import SideEffectFacts as SideEffectFacts
from .tiers import load_risk_table as load_risk_table
