"""Model-free real child-process reusable-session boundaries."""
import importlib.util
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

FEATURES={'report':'Lost parcel','observations':{},'allowed_actions':[{'kind':'read','tool':'order_manifest'},{'kind':'request_review','reason':'manual_review'}],
          'attempted_tools':[],'remaining_budgets':{'decisions':16,'tools':12},'rejections':[]}

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('decisionops.commerce.session_protocol'),'Session boundary not implemented')
        from decisionops.commerce.session_protocol import Session,Config,SessionFailure
        self.Session=Session;self.Config=Config;self.Failure=SessionFailure
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def session(self,behavior='normal',**kwargs):
        s=self.Session(self.Config('fake','fake-v1',behavior=behavior,slot_ms=300,preload_ms=500),
                       'SESSION-test',time.monotonic()+4,slot_path=Path(self.tmp.name)/'slot',**kwargs)
        self.addCleanup(s.close);return s
    def test_two_decisions_use_one_load_and_no_audit_features(self):
        s=self.session();s.start();pid=s.process.pid
        for index in range(2):
            r=s.choose('CALL-'+str(index),FEATURES,time.monotonic()+1)
            self.assertEqual(r['action_index'],0);self.assertTrue(r['simulated']);self.assertEqual(r['load_count'],1)
        self.assertEqual(s.process.pid,pid);s.close();self.assertTrue(s.diagnostics()['process_reaped'])
        self.assertLessEqual(s.diagnostics()['retained']['stderr'],1024)
    def test_malformed_truncated_wrong_session_and_request_fail(self):
        for mode in ('malformed','truncated','wrong-session','wrong-request'):
            with self.subTest(mode=mode):
                s=self.session(mode)
                with self.assertRaises(self.Failure):
                    s.start();s.choose('CALL',FEATURES,time.monotonic()+1)
                s.close();self.assertTrue(s.diagnostics()['process_reaped'])
    def test_frame_and_both_stream_overflow_are_consumption_bounded(self):
        for mode in ('frame-overflow','stderr-overflow','both-overflow'):
            with self.subTest(mode=mode):
                s=self.session(mode)
                with self.assertRaises(self.Failure):s.start()
                s.close();d=s.diagnostics()
                self.assertTrue(d['process_reaped']);self.assertLessEqual(d['consumed']['stdout'],65537)
                self.assertLessEqual(d['consumed']['stderr'],65537)
                self.assertLessEqual(sum(d['retained'].values()),2048)
    def test_cumulative_stdout_cap_is_not_reset_per_response(self):
        s=self.session('cumulative');s.start();completed=0
        with self.assertRaises(self.Failure):
            for n in range(16):s.choose(str(n),FEATURES,time.monotonic()+1);completed+=1
        self.assertGreater(completed,1);self.assertLess(completed,16)
        s.close();self.assertEqual(s.diagnostics()['consumed']['stdout'],65537)
    def test_preload_and_decision_deadlines_stop_owned_child(self):
        for mode in ('preload-timeout','decision-timeout'):
            with self.subTest(mode=mode):
                s=self.session(mode);start=time.monotonic()
                with self.assertRaises(self.Failure):
                    s.start();s.choose('CALL',FEATURES,time.monotonic()+.1)
                s.close();self.assertLess(time.monotonic()-start,1.5);self.assertTrue(s.diagnostics()['process_reaped'])
    def test_descendant_pipes_do_not_hold_cleanup_open(self):
        s=self.session('descendants');start=time.monotonic()
        with self.assertRaises(self.Failure):s.start()
        s.close();self.assertLess(time.monotonic()-start,1.5);d=s.diagnostics();self.assertTrue(d['process_reaped'])
        for line in d['diagnostics']['stderr'].splitlines():
            if line.startswith('descendant='):
                pid=int(line.split('=')[1]);p=Path('/proc')/str(pid)/'stat'
                end=time.monotonic()+1
                while p.exists() and p.read_text().split()[2]!='Z' and time.monotonic()<end:time.sleep(.01)
                self.assertTrue(not p.exists() or p.read_text().split()[2]=='Z')
    def test_shutdown_during_preload_and_idle_stops_session(self):
        stop=threading.Event();s=self.session('preload-timeout',cancel=stop)
        timer=threading.Timer(.05,stop.set);timer.start()
        try:
            with self.assertRaises(self.Failure):s.start()
        finally:timer.join();s.close()
        self.assertTrue(s.diagnostics()['process_reaped'])
        stop=threading.Event();s=self.session(cancel=stop);s.start();stop.set()
        end=time.monotonic()+1
        while s.process.poll() is None and time.monotonic()<end:time.sleep(.02)
        s.close();self.assertTrue(s.diagnostics()['process_reaped'])
    def test_host_slot_wait_is_bounded_and_no_second_child_loads(self):
        first=self.session();first.start();second=self.session();start=time.monotonic()
        with self.assertRaises(self.Failure):second.start()
        self.assertLess(time.monotonic()-start,.8);self.assertIsNone(second.process)
    def test_forced_choice_never_acquires_slot_or_loads(self):
        s=self.session();f={**FEATURES,'allowed_actions':[{'kind':'request_review','reason':'manual_review'}]}
        r=s.choose('CALL',f,time.monotonic()+1)
        self.assertTrue(r['forced']);self.assertEqual(r['inference_ms'],0);self.assertIsNone(s.process)

    def test_known_error_frames_and_lease_deadline_are_distinct_from_unknown(self):
        from decisionops.commerce.session_protocol import KnownFailure
        for mode in ('preload-error','decision-error'):
            s=self.session(mode)
            with self.assertRaises(KnownFailure):s.start();s.choose('CALL',FEATURES,time.monotonic()+1)
            s.close();self.assertTrue(s.diagnostics()['process_reaped'])
        s=self.session('preload-timeout',lease_deadline=time.monotonic()+.1)
        with self.assertRaises(self.Failure):s.start()
        s.close();self.assertTrue(s.diagnostics()['process_reaped'])

    def test_parent_loss_watchdog_closes_inherited_host_slot(self):
        import subprocess,sys,json
        marker=Path(self.tmp.name)/'pid';slot=Path(self.tmp.name)/'slot'
        code="""
import sys,time
from pathlib import Path
from decisionops.commerce.session_protocol import Config,Session
s=Session(Config('fake','fake-v1'),'s',time.monotonic()+5,slot_path=Path(sys.argv[2]))
s.start();Path(sys.argv[1]).write_text(str(s.process.pid));time.sleep(10)
"""
        parent=subprocess.Popen([sys.executable,'-B','-c',code,str(marker),str(slot)])
        try:
            end=time.monotonic()+2
            while not marker.exists() and time.monotonic()<end:time.sleep(.01)
            self.assertTrue(marker.exists());pid=int(marker.read_text());parent.kill();parent.wait(1)
            end=time.monotonic()+1
            p=Path('/proc')/str(pid)/'stat'
            while p.exists() and p.read_text().split()[2]!='Z' and time.monotonic()<end:time.sleep(.01)
            self.assertTrue(not p.exists() or p.read_text().split()[2]=='Z')
            fresh=self.session();fresh.start();fresh.close()
        finally:
            if parent.poll() is None:parent.kill();parent.wait(1)

    def test_immediate_error_exit_preserves_the_correlated_known_result(self):
        from decisionops.commerce.session_protocol import KnownFailure
        s=self.session('preload-error');original=s._check
        def wait_for_exit_before_check(end):
            if s.input_bytes_written>0 and threading.current_thread() is not s.reader:
                finish=time.monotonic()+.5
                while s.process.poll() is None and time.monotonic()<finish:time.sleep(.001)
                s.reader.join(.2)
            return original(end)
        s._check=wait_for_exit_before_check
        with self.assertRaises(KnownFailure):s.start()
        s.close();self.assertTrue(s.diagnostics()['process_reaped'])

    def test_exited_child_drains_all_buffered_stderr_before_finalizing(self):
        import socket
        from types import SimpleNamespace
        s=self.session();s.completed_response=True
        out_host,out_peer=socket.socketpair();err_host,err_peer=socket.socketpair()
        pipes=[out_host.makefile('rb',buffering=0),err_host.makefile('rb',buffering=0)]
        s.process=SimpleNamespace(stdout=pipes[0],stderr=pipes[1],poll=lambda:0)
        s._kill=lambda:None
        try:
            err_peer.sendall(b'x'*65537)
            s._drain()
            self.assertEqual(str(s.failed),'stderr_cumulative_overflow')
            self.assertEqual(s.consumed['stderr'],65537)
            self.assertEqual(len(s.retained['stderr']),1024)
        finally:
            s.process=None
            for item in pipes+[out_host,out_peer,err_host,err_peer]:item.close()

    def test_exit_cannot_hide_buffered_surplus_or_overflow_proof_byte(self):
        for mode in ('exit-surplus','exit-stderr-overflow'):
            with self.subTest(mode=mode):
                s=self.session(mode);s.start();written=s.input_bytes_written;original=s._check
                def wait_for_exit_before_check(end):
                    if s.input_bytes_written>written and threading.current_thread() is not s.reader:
                        finish=time.monotonic()+.5
                        while s.process.poll() is None and time.monotonic()<finish:time.sleep(.001)
                        s.reader.join(.3)
                    return original(end)
                s._check=wait_for_exit_before_check
                with self.assertRaises(self.Failure):s.choose('CALL',FEATURES,time.monotonic()+1)
                s.close();self.assertTrue(s.diagnostics()['process_reaped'])

if __name__=='__main__':unittest.main()
