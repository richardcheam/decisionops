import json
from pathlib import Path
from decimal import Decimal
from decisionops.commerce.openai_decisions import DecisionsConfig
from decisionops.commerce.proposals import document_hash
cfg=DecisionsConfig(**json.loads(Path(__file__).with_name('api-decisions-proposed.json').read_text()))
assert document_hash(cfg.record())=='b318cc81100b474bf1cad6815bd9ed8f39a064db9f1cdf55debff8eb2a54da09'
assert cfg.max_requests==12 and cfg.max_cost_usd=='0.03' and cfg.execution=='live'
assert cfg.maximum()*12==Decimal('0.02949120')
print('Exact Decisions configuration verified; no live call')
