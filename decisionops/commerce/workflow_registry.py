"""Workflow-specific read authority, separated from durable controller mechanics.

A future returns implementation supplies projected read adapters, deterministic
policy/outcomes and case transitions. The paper registration proves dependency
and scope contracts only; it cannot run or authorize a return/refund.
"""
from dataclasses import dataclass

SCOPE_FIELDS = ('case_id', 'order_id', 'shipment_id', 'items', 'generation', 'case_revision')


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    prerequisites: tuple[str, ...]
    coordinator_tools: tuple[str, ...]
    branches: tuple[tuple[str, tuple[str, ...]], ...]
    dependencies: tuple[tuple[str, tuple[str, ...]], ...]
    outcomes: tuple[str, ...]
    paper_only: bool = False
    scope_fields: tuple[str, ...] = SCOPE_FIELDS

    def __post_init__(self):
        dependencies = dict(self.dependencies)
        owners = [*self.coordinator_tools, *(t for _, tools in self.branches for t in tools)]
        if (not self.name or len(dependencies) != len(self.dependencies)
                or set(owners) != set(dependencies) or len(owners) != len(set(owners))
                or not set(self.prerequisites) <= set(self.coordinator_tools)
                or len(dict(self.branches)) != len(self.branches)
                or self.scope_fields != SCOPE_FIELDS or 'needs_review' not in self.outcomes
                or any(t in {'approve', 'execute', 'refund'} for t in owners)):
            raise ValueError('Workflow requires unique read ownership, scope and review outcome')
        resolved = set()
        while len(resolved) < len(dependencies):
            useful = {t for t, deps in dependencies.items() if set(deps) <= resolved} - resolved
            if not useful: raise ValueError('Workflow dependencies contain a cycle or unknown tool')
            resolved.update(useful)
        committed = set()
        for tool in self.prerequisites:
            if not set(dependencies[tool]) <= committed:
                raise ValueError('Prerequisites must be committed in dependency order')
            committed.add(tool)

    def allowed_tools(self, owner):
        if owner == 'coordinator': return self.coordinator_tools
        try: return dict(self.branches)[owner]
        except KeyError: raise ValueError('Unknown workflow read owner') from None


# Pure registration stays importable in the dependency-free policy profile.
# SQL adapter parity is checked by the commerce-profile registry test.
LOST_DEPENDENCIES = (
    ('order_manifest', ()), ('replacement_policy', ('order_manifest',)),
    ('payment', ('order_manifest',)), ('fulfilment', ('order_manifest',)),
    ('carrier_loss', ('order_manifest', 'fulfilment', 'replacement_policy')),
    ('compensation_history', ('order_manifest',)), ('inventory', ('order_manifest',)))

LOST_SHIPMENT = WorkflowDefinition(
    'lost_shipment', ('order_manifest', 'replacement_policy'),
    ('order_manifest', 'replacement_policy', 'inventory'),
    (('order', ('payment', 'compensation_history')), ('shipment', ('fulfilment', 'carrier_loss'))),
    LOST_DEPENDENCIES, ('proposed', 'blocked', 'needs_review'))
RETURNS_PAPER = WorkflowDefinition(
    'returns', ('order_manifest', 'return_policy'), ('order_manifest', 'return_policy'),
    (('order', ('payment', 'compensation_history')), ('shipment', ('return_receipt',))),
    (('order_manifest', ()), ('return_policy', ('order_manifest',)),
     ('payment', ('order_manifest',)), ('compensation_history', ('order_manifest',)),
     ('return_receipt', ('order_manifest', 'return_policy'))),
    ('return_proposal', 'blocked', 'needs_review'), paper_only=True)


def workflow(name, *, executable=True):
    definition = {'lost_shipment': LOST_SHIPMENT, 'returns': RETURNS_PAPER}.get(name)
    if definition is None: raise ValueError('Unknown workflow')
    if executable and definition.paper_only: raise ValueError('Workflow is paper-only')
    return definition
