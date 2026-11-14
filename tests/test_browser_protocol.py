"""One decision per provider response; no API or browser dependency."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts import browser_evaluation as e

ACTION={'action':'act','url':None,'observation':'observed','reference':'c5','value':None,'result':None}
def function_response(action=ACTION):
 return {'model':'gpt-6-luna','status':'completed','usage':{'input_tokens':100,'output_tokens':20},'output':[{'type':'function_call','id':'fc_test','call_id':'call_test','name':'browser_action','status':'completed','arguments':json.dumps(action)}]}

def observed_shape():
 # Synthetic identifiers, same three-message/phase/action structure as live001.
 return {'model':'gpt-6-luna','status':'completed','usage':{'input_tokens':100,'output_tokens':20},'output':[{'type':'message','role':'assistant','status':'completed','phase':phase,'content':[{'type':'output_text','text':json.dumps(action)}]} for phase,action in [('commentary',ACTION),('commentary',dict(ACTION,action='observe',observation=None,reference=None)),('final_answer',dict(ACTION,action='finish',observation=None,reference=None,result={'outcome':'missing_evidence','reason':'incomplete','findings':None,'citations':[],'unknowns':['event']}))]]}

class ProtocolTests(unittest.TestCase):
 def test_single_forced_function_contract_and_valid_decision(self):
  body=e.request_body(e.load_config(),{'goal':'fictional'})
  self.assertEqual(body['tool_choice'],{'type':'function','name':'browser_action'})
  self.assertFalse(body['parallel_tool_calls'])
  self.assertTrue(body['tools'][0]['strict'])
  self.assertEqual(body['tools'][0]['parameters'],e.SCHEMA)
  self.assertNotIn('text',body)
  self.assertEqual(e.parse_action(function_response(),e.load_config()),ACTION)

 def test_historical_multi_message_shape_is_unapplied(self):
  class Bridge:
   def __init__(self):self.messages=[]
   def call(self,message,timeout):
    self.messages.append(message)
    return {'ok':True,'features':{},'observation':{'id':'observed','url':'http://127.0.0.1:8096/shop','text':'visible','blocks':[],'controls':[],'truncated':False}}
  bridge=Bridge()
  with tempfile.TemporaryDirectory() as t:
   ledger=e.Ledger(Path(t)/'run',e.load_config(),'test')
   with self.assertRaisesRegex(ValueError,'one|Ambiguous'):
    e.investigate(bridge,{},'http://127.0.0.1:8096/shop',e.load_config(),ledger,'A1',lambda *_:observed_shape())
   self.assertEqual([m['op'] for m in bridge.messages],['start'])
   self.assertEqual(len(ledger.value['calls']),1)
   self.assertEqual(ledger.value['calls'][0]['dispatch_count'],1)
   self.assertEqual(ledger.value['calls'][0]['state'],'settled')
   self.assertEqual(ledger.value['current_case']['choices'],[])

 def test_missing_multiple_mixed_wrong_or_malformed_calls_rejected(self):
  base=function_response();output=base['output'][0]
  bad=[[],[output,output],[output,*observed_shape()['output']],
       [dict(output,name='execute_replacement')],[dict(output,arguments='not JSON')],
       [dict(output,arguments=json.dumps([ACTION,ACTION]))],
       [dict(output,arguments='{"action":"act","action":"observe"}')],
       [dict(output,arguments=json.dumps(dict(ACTION,value=[])))],
       [dict(output,status='in_progress')],[dict(output,call_id='')],
       [{'type':'message','content':[{'type':'refusal','refusal':'no'}]}]]
  for outputs in bad:
   with self.subTest(outputs=outputs),self.assertRaises(ValueError):
    e.parse_action(dict(base,output=outputs),e.load_config())
