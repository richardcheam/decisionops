"""Offline launcher contract; no services, keys or databases accessed."""
import unittest
from unittest.mock import patch
from scripts import commerce_staff_demo as demo

class DemoLauncherTests(unittest.TestCase):
    def test_repeatable_second_instance_selects_its_port(self):
        args=demo.parse_args(['start','--port','55523','--schema','staff_demo_clean'])
        self.assertEqual(args.port,55523)
        self.assertEqual(args.schema,'staff_demo_clean')
        self.assertEqual(args.mode,'rules')
    def test_bad_or_privileged_ports_are_rejected_before_operations(self):
        for port in ('0','80','65536'):
            with self.subTest(port=port),self.assertRaises(SystemExit),patch('sys.stderr'):
                demo.parse_args(['start','--port',port])
    def test_paid_mode_is_not_a_launcher_option(self):
        with self.assertRaises(SystemExit),patch('sys.stderr'):
            demo.parse_args(['start','--mode','live'])
    def test_occupied_port_aborts_before_database_import_or_operations(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'web-dist').mkdir();(root/'web-dist/index.html').write_text('fictional build')
            with patch.object(demo,'DIRECTORY',root),patch('sys.argv',['demo','start','--port','55523']),patch('socket.socket') as sock:
                sock.return_value.__enter__.return_value.bind.side_effect=OSError('occupied')
                with self.assertRaisesRegex(SystemExit,'Selected web port unavailable'):
                    demo.main()
                import socket
                sock.return_value.__enter__.return_value.setsockopt.assert_called_once_with(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                sock.return_value.__enter__.return_value.bind.assert_called_once_with(('127.0.0.1',55523))
            self.assertFalse((root/'services.json').exists())
