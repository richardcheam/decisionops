import tempfile
import unittest
from pathlib import Path
from scripts import browser_trace as trace

class TraceTests(unittest.TestCase):
 def test_allowlist_removes_raw_features_errors_credentials_and_ids(self):
  canary='SECRET_CANARY_CUSTOMER'
  payload={'label':'mocked offline','ledger':{'state':'stopped','source':'a'*40,'config_hash':'b'*64,'stop_type':'ValueError','calls':[{'ordinal':1,'state':'settled','case_key':canary,'reserved_usd':'0.00512','latency_seconds':0.2,'request':{'input':canary,'Authorization':canary},'response':{'error':canary},'usage':{'input_tokens':1,'output_tokens':2,'simulated':True},'validated_action':{'action':'act','reference':'c5','url':canary}}]},'browser_audit':{'audit':[{'kind':'observation','at':'now','data':{'id':canary,'text':canary,'url':'http://user:password@local/private?key='+canary}},{'kind':'tool_error','at':'now','data':{'kind':'wrong_binding','reason':canary}}]}}
  public=trace.project(payload)
  self.assertNotIn(canary,str(public));self.assertNotIn('password',str(public));self.assertEqual(public['decisions'][0]['action'],'act')
  self.assertEqual(public['decisions'][0]['resources'],'simulated')
  self.assertNotIn('estimated_usd',public['decisions'][0]);self.assertEqual(public['events'][1]['outcome'],'wrong_binding')
  self.assertFalse(public['export_enabled'])

 def test_html_is_local_escaped_and_explains_failure(self):
  public=trace.project({'state':'stopped','stop_type':'ValueError','calls':[]})
  html=trace.render(public)
  self.assertIn('ValueError',html);self.assertNotIn('<script src=',html);self.assertNotIn('https://',html)
  self.assertIn('not authorise',html)
