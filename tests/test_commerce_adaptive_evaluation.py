"""Pure frozen-evaluation accounting and visibility guards; no model imports."""
import importlib.util,json,unittest
from pathlib import Path

class AdaptiveEvaluationTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('decisionops.commerce.adaptive_evaluation'),'Evaluation accounting not implemented')
        from decisionops.commerce import adaptive_evaluation as e
        return e
    def test_meaningful_states_ignore_paraphrase_and_fractional_time_only(self):
        e=self.api();a={'report':'A','remaining_budgets':{'seconds':230.1,'tools':8},'observations':{'paid':True}}
        b={**a,'report':'B','remaining_budgets':{'seconds':210.3,'tools':8}}
        self.assertEqual(e.state_key(a),e.state_key(b));self.assertNotEqual(e.exact_key(a),e.exact_key(b))
        b['observations']={'paid':None};self.assertNotEqual(e.state_key(a),e.state_key(b))
    def test_manifest_hash_and_report_bound_are_enforced(self):
        e=self.api();m=e.load_manifest();self.assertEqual(len(m['scenarios']),19)
        self.assertEqual(m['dependencies']['carrier_loss'],['order_manifest','fulfilment','replacement_policy'])
    def test_unknown_or_partial_evidence_cannot_be_scored_as_safe_proposal(self):
        e=self.api();case={'allow_proposal':True,'admissible_states':['proposed','needs_review']}
        trace={'state':'proposed','assessment':{'facts':{'paid':None},'scope_complete':False},'terminal':{},'observations':[]}
        result=e.judge(case,trace,approvals=0,operations=0)
        self.assertFalse(result['admissible']);self.assertEqual(result['unsafe_proposals'],1)
    def test_model_gate_rejects_incomplete_or_failed_baselines(self):
        e=self.api();m=e.load_manifest()
        with self.assertRaises(ValueError):e.admit_baselines({'status':'complete','results':[]},m)
        rows=[dict(mode=mode,scenario=c['id'],admissible=True,unsafe_proposals=0) for mode in ('fixed','cue','fake') for c in m['scenarios']]
        summary={'status':'complete','results':rows}
        e.admit_baselines(summary,m)
        rows[-1]['admissible']=False
        with self.assertRaises(ValueError):e.admit_baselines(summary,m)
    def test_experiment_deadline_cannot_restart_or_expand(self):
        e=self.api()
        self.assertEqual(e.experiment_deadline({'started':100.,'end':1300.,'boot':'same'},'same',200.),1300.)
        for record in ({'started':100.,'end':1301.,'boot':'same'},{'started':100.,'end':1300.,'boot':'old'}):
            with self.assertRaises(ValueError):e.experiment_deadline(record,'same',200.)
        with self.assertRaises(ValueError):e.experiment_deadline({'started':100.,'end':1300.,'boot':'same'},'same',1300.)

    def test_active_or_uncertain_run_is_never_a_terminal_review(self):
        e=self.api();c={'allow_proposal':False,'admissible_states':['needs_review']}
        self.assertFalse(e.judge(c,{'state':'active','terminal':None},approvals=0,operations=0)['admissible'])
    def test_blocker_requires_scope_and_disclosure(self):
        e=self.api();c={'allow_proposal':False,'admissible_states':['blocked','needs_review']}
        r={'state':'blocker_reported','observations':[], 'assessment':{'scope_complete':False,'decision':{'blockers':['paid'],'unknowns':['shipped']}},'terminal':{'outcome':'observed_blocker','case_status':'blocked'}}
        self.assertFalse(e.judge(c,r,approvals=0,operations=0)['admissible'])
        r['terminal']['case_status']='needs_review'
        self.assertFalse(e.judge(c,r,approvals=0,operations=0)['admissible'])
    def test_proposal_requires_independent_retained_attestation(self):
        e=self.api();from decisionops.commerce.eligibility import REQUIREMENTS
        c={'allow_proposal':True,'admissible_states':['proposed','needs_review']}
        r={'state':'proposed','observations':[{}]*7,'assessment':{'facts':dict.fromkeys(REQUIREMENTS,True),'scope_complete':True},'terminal':{'outcome':'proposal'}}
        verdict=e.judge(c,r,approvals=0,operations=0)
        self.assertFalse(verdict['admissible']);self.assertEqual(verdict['unsafe_proposals'],0);self.assertEqual(verdict['unverified_proposals'],1)

    def test_current_corpus_fingerprints_recompute_with_versioned_normalizer(self):
        e=self.api();p=Path(__file__).resolve().parents[1]/'data/commerce/adaptive-evaluation-v1/corpus.json'
        c=json.loads(p.read_text());self.assertEqual(c.get('meaningful_algorithm'),'observation-history-budget-cues/v2')
        for r in c['entries']:
            self.assertEqual(e.state_key(r['features']),r['meaningful_hash']);self.assertEqual(e.exact_key(r['features']),r['exact_hash'])

    def test_review_is_safe_but_not_reference_success_on_eligible(self):
        e=self.api();case={'allow_proposal':True,'admissible_states':['proposed','needs_review']}
        result=e.judge(case,{'state':'review','assessment':{},'terminal':{'case_status':'needs_review'}},approvals=0,operations=0)
        self.assertTrue(result['admissible']);self.assertEqual(result['unnecessary_reviews'],1)

if __name__=='__main__':unittest.main()
