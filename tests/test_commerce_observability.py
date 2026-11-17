"""Allowlisted, bounded, fail-open optional tracing; no hosted exports."""
import os
import time
import unittest
from unittest.mock import patch

class TracingTests(unittest.TestCase):
    def test_default_zero_export_and_sanitized_opt_in(self):
        from decisionops.commerce.observability import SafeTracer
        events=[]
        disabled=SafeTracer(sink=events.append)
        disabled.emit('server-investigation','node',node='order',customer_text='private')
        self.assertEqual(events,[])
        enabled=SafeTracer(enabled=True,sink=events.append)
        enabled.emit('server-investigation','node',node='order',tool='payment',status='success',attempt=2,
                     customer_text='private',order_id='DEMO-LYON',reason='SECRET-text')
        self.assertTrue(enabled.flush(1))
        self.assertEqual(len(events),1)
        event=events[0];self.assertEqual(event['investigation_id'],'server-investigation')
        self.assertEqual(event['attempt'],2);self.assertEqual(event['reason'],'other')
        self.assertNotIn('private',str(events));self.assertNotIn('DEMO-LYON',str(events));self.assertNotIn('SECRET',str(events))

    def test_failed_or_slow_export_does_not_block_caller(self):
        from decisionops.commerce.observability import SafeTracer
        def sink(_):time.sleep(.1);raise RuntimeError('private-token')
        trace=SafeTracer(enabled=True,sink=sink,max_queue=2)
        start=time.monotonic()
        for _ in range(40):trace.emit('server-run','failure',reason='worker_error')
        self.assertLess(time.monotonic()-start,.08)
        trace.flush(.3)
        self.assertGreater(trace.dropped,0);self.assertGreater(trace.errors,0)

    def test_global_sdk_flags_do_not_enable_export(self):
        from decisionops.commerce.observability import configured_tracer
        with patch.dict(os.environ, {'LANGSMITH_TRACING':'true','LANGSMITH_API_KEY':'fictional-not-used','COMMERCE_LANGSMITH_EXPORT':'0'}):
            self.assertFalse(configured_tracer().enabled)

    @unittest.skipUnless(__import__('importlib.util').util.find_spec('sqlalchemy'),'Requires Commerce SQL profile')
    def test_trace_only_database_inspection_is_off_business_thread(self):
        from decisionops.commerce.observability import SafeTracer,observe
        from unittest.mock import patch
        def slow_inspect(*_):time.sleep(.2);return {'id':'server-run','state':'active','steps':[]}
        trace=SafeTracer(enabled=True,sink=lambda _:None)
        with patch('decisionops.commerce.adaptive_investigations.inspect',side_effect=slow_inspect):
            start=time.monotonic();observe(object(),'server-run',tracer=trace)
            self.assertLess(time.monotonic()-start,.08)
            self.assertTrue(trace.flush(1))
