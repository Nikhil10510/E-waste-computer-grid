import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from log_safety import safe_text, SafeFormatter
from desktop_runtime import DesktopRuntime
from state_store import save_state


class DiagnosticsTests(unittest.TestCase):
    def test_log_and_traceback_redact_credentials_and_signed_urls(self):
        message = 'Bearer auth-secret node_secret="node-private" https://grid/api/storage?signature=private&expires=1 exact-secret'
        record = logging.LogRecord('worker', logging.ERROR, '', 0, message, (), None)
        text = SafeFormatter(lambda: ('exact-secret',)).format(record)
        for private in ('auth-secret', 'node-private', 'signature=private', 'exact-secret'):
            self.assertNotIn(private, text)
        self.assertIn('[redacted]', text)

    def test_diagnostics_tail_is_bounded_and_hides_saved_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = DesktopRuntime('https://grid.example/api', temp, 'Laptop')
            save_state(Path(temp)/'credentials.json', {'node_secret': 'private-credential'})
            runtime.log_file.write_text('a'*100000 + '\nprivate-credential')
            text = runtime.diagnostics()
            self.assertLess(len(text), 17000)
            self.assertNotIn('private-credential', text)

    def test_preflight_failure_explains_actual_runtime_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = DesktopRuntime('https://grid.example/api', temp, 'Laptop')
            response = MagicMock(returncode=1, stdout='{"error":"Docker daemon unavailable"}', stderr='')
            with patch('desktop_runtime.subprocess.run', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'Docker daemon unavailable'): runtime.preflight()
            self.assertIn('Docker daemon unavailable', runtime.diagnostics())


if __name__ == '__main__': unittest.main()
