"""Read the source's explicit schema contract without optional runtime imports."""
import ast
from pathlib import Path


def source_revision():
    path=Path(__file__).resolve().parents[1]/'decisionops/commerce/schema_readiness.py'
    nodes=ast.parse(path.read_text()).body
    values=[ast.literal_eval(n.value) for n in nodes if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='SUPPORTED_REVISION' for t in n.targets)]
    if len(values)!=1 or not isinstance(values[0],str) or len(values[0])!=4 or not values[0].isdigit():
        raise RuntimeError('Missing or invalid explicit source schema contract')
    return values[0]


def validate_restored_revisions(original,restored):
    expected=source_revision()
    if original!=expected or restored!=expected:
        raise RuntimeError(f'Schema revision mismatch: source={expected}, original={original}, restored={restored}')
