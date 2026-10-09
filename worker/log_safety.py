"""Bounded diagnostic text with private credentials and URL queries removed."""
import logging
import re


def safe_text(value, secrets=()):
    text = str(value)
    for secret in secrets:
        if secret and len(str(secret)) >= 8: text = text.replace(str(secret), '[redacted]')
    text = re.sub(r'(?i)(Bearer\s+)[\w._~+/=-]+', r'\1[redacted]', text)
    text = re.sub(r'(https?://[^\s?"\']+)\?[^\s"\']+', r'\1?[redacted]', text)
    text = re.sub(r'(?i)(["\']?(?:node_secret|pairing_secret|admin_token|enrollment_token|storage_secret)["\']?\s*[:=]\s*)(["\']?)[^\s,"\'}]+', r'\1[redacted]', text)
    return text


class SafeFormatter(logging.Formatter):
    def __init__(self, secrets=lambda: ()):
        super().__init__('%(asctime)s %(levelname)s %(message)s')
        self.secrets = secrets

    def format(self, record):
        return safe_text(super().format(record), self.secrets())
