"""Owner-side pairing, independent of the dashboard's admin credentials."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit, urlunsplit
import requests
from api_client import APIError
from resource_limits import validate_limits
from state_store import load_state, save_state, update_state


def normalize_api_url(value, allow_http=False):
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except (ValueError, AttributeError) as exc:
        raise ValueError('Enter a valid grid API address ending in /api') from exc
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path.rstrip('/') != '/api' or (port is not None and not 1 <= port <= 65535)):
        raise ValueError('Use an HTTP(S) API address ending in /api, without credentials or query parameters')
    if parsed.scheme == 'http' and not allow_http:
        raise ValueError('Use HTTPS, or explicitly allow HTTP for your trusted local demo network')
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), '/api', '', ''))


def state_directory(api_url):
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
    return base / 'EWasteGrid' / hashlib.sha256(api_url.encode()).hexdigest()[:16]


atomic_json = save_state


class PairingClient:
    def __init__(self, api_url, directory, allow_http=False):
        self.api_url = normalize_api_url(api_url, allow_http)
        self.directory = Path(directory)
        self.session_file = self.directory / 'pairing.json'
        self.credentials_file = self.directory / 'credentials.json'
        self.session = None
        if self.session_file.exists():
            saved = load_state(self.session_file)
            if saved.get('control_plane_url') != self.api_url:
                raise ValueError('Pairing session belongs to another grid')
            self._validate_session(saved)
            self.session = saved

    @staticmethod
    def _validate_session(data):
        if not isinstance(data, dict): raise ValueError('Invalid pairing response')
        uuid.UUID(data['pairing_id'])
        if not re.fullmatch(r'[A-Za-z0-9_-]{8}', data.get('pairing_code', '')):
            raise ValueError('Invalid pairing code')
        if not isinstance(data.get('pairing_secret'), str) or not 32 <= len(data['pairing_secret']) <= 200:
            raise ValueError('Invalid private pairing credential')

    def request(self, method, path, body=None, secret=None, node_id=None):
        headers = {'Authorization': 'Bearer ' + secret} if secret else {}
        if node_id: headers['x-node-id'] = node_id
        try:
            response = requests.request(method, self.api_url + path, json=body,
                headers=headers, timeout=(5, 15), allow_redirects=False)
        except requests.RequestException as exc:
            # Do not expose request objects/headers; a lost approval response can
            # be recovered by retrying this session after reconnecting.
            raise APIError('Could not reach the grid. Check the address and connection; retry the same session.') from exc
        if not 200 <= response.status_code < 300:
            try: message = response.json().get('error', 'Grid request failed')
            except ValueError: message = 'Grid request failed'
            raise APIError(message, response.status_code)
        try: return response.json()
        except ValueError as exc: raise APIError('Grid returned an invalid response') from exc

    def begin(self, hardware, resource_limits=None):
        if resource_limits is not None:
            resource_limits = validate_limits(resource_limits, hardware['cpu_cores'], hardware['ram_gb'])
        data = self.request('POST', '/pairing', hardware)
        self._validate_session(data)
        data['control_plane_url'] = self.api_url
        if resource_limits is not None: data['resource_limits'] = resource_limits
        # Never discard a session automatically after a failed decision.
        atomic_json(self.session_file, data)
        self.session = data
        return data

    def poll(self):
        if not self.session: raise ValueError('Generate a pairing code first')
        return self.request('GET', '/pairing/' + self.session['pairing_id'], secret=self.session['pairing_secret'])

    def decide(self, approve):
        if not self.session: raise ValueError('Generate a pairing code first')
        body = {'decision': 'approve' if approve else 'decline'}
        if approve and self.session.get('resource_limits') is not None:
            body['resource_limits'] = validate_limits(self.session['resource_limits'])
        data = self.request('POST', '/pairing/' + self.session['pairing_id'] + '/decision',
            body, secret=self.session['pairing_secret'])
        if approve:
            if data.get('state') != 'APPROVED': raise ValueError('Owner approval was not accepted')
            uuid.UUID(data['node_id'])
            if not isinstance(data.get('node_secret'), str) or len(data['node_secret']) < 32:
                raise ValueError('Grid returned an invalid worker credential')
            atomic_json(self.credentials_file, {'node_id': data['node_id'], 'node_secret': data['node_secret'],
                'control_plane_url': self.api_url, 'registration_key': str(uuid.uuid4()), 'enrollment_mode': 'paired',
                'resource_limits': data.get('resource_limits'), 'paused': data.get('paused', False)})
        self.session_file.unlink(missing_ok=True)
        self.session = None
        return data

    def saved_identity(self):
        if not self.credentials_file.exists(): return None
        data = load_state(self.credentials_file)
        if data.get('control_plane_url') != self.api_url: raise ValueError('Worker identity belongs to another grid')
        if not data.get('node_id') or not data.get('node_secret'): return None
        session = self.request('GET', '/nodes/session', secret=data['node_secret'], node_id=data['node_id'])
        if session.get('enrollment_mode') != 'paired':
            raise ValueError('This identity used script enrollment. Use a fresh app state directory and obtain owner approval.')
        data.update(resource_limits=session.get('resource_limits'), paused=session.get('paused', False))
        update_state(self.credentials_file, {'resource_limits': data['resource_limits'], 'paused': data['paused']})
        return session

    def set_paused(self, paused):
        if not isinstance(paused, bool): raise ValueError('paused must be boolean')
        saved = load_state(self.credentials_file)
        if saved.get('control_plane_url') != self.api_url: raise ValueError('Worker identity belongs to another grid')
        data = self.request('POST', '/nodes/' + saved['node_id'] + '/participation', {'paused': paused},
            secret=saved['node_secret'], node_id=saved['node_id'])
        update_state(self.credentials_file, {'paused': data['paused'], 'resource_limits': data.get('resource_limits')})
        return data
