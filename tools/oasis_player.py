"""Opt-in part playback on our Oasis firmware. This module never starts a background job.

The caller validates the complete ordered file list, persists dispatch intent for each unique
part, calls play once, and advances only on inspect returning 'complete'. After restart or
an ambiguous response, inspect is the read-only recovery operation. Unknown or staged needs
operator recovery. Camera verification remains independent of the controller's counters.
"""
import hashlib
import http.client
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib import parse, request


class PlaybackError(Exception):
    """The part could not be verified, or the table is unavailable."""


NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?'
ROW = re.compile(rf'[ \t]*({NUMBER})[ \t]+({NUMBER})[ \t]*', re.ASCII)


def points(part):
    if not isinstance(part, dict) or not isinstance(part.get('name'), str) or not re.fullmatch(
            r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.thr', part['name']):
        raise PlaybackError('Invalid part name.')
    text = part.get('text')
    if not isinstance(text, str) or not text.isascii() or len(text) > 1_000_000:
        raise PlaybackError('Invalid motion text.')
    return _geometry(text)


@lru_cache(maxsize=4)
def _geometry(text):
    rows = text.split('\n')
    if rows[-1] == '':
        rows.pop()
    if not 2 <= len(rows) <= 12000:
        raise PlaybackError('The Mini needs 2 to 12,000 points per part.')
    first = None
    for row in rows:
        row = row.removesuffix('\r')
        match = ROW.fullmatch(row) if len(row) <= 47 else None  # firmware lineBuf is 48 bytes
        if not match:
            raise PlaybackError('Invalid motion row.')
        position = theta, radius = tuple(map(float, match.groups()))
        if not math.isfinite(theta) or not 0 <= radius <= 1:
            raise PlaybackError('Invalid polar point.')
        if first is None:
            first = position
    return first, position, len(rows)


def near(a, b, theta_tolerance=.002, radius_tolerance=.001):
    return abs(math.remainder(a[0] - b[0], math.tau)) <= theta_tolerance and abs(a[1] - b[1]) <= radius_tolerance


def validate_parts(files):
    if not isinstance(files, (list,tuple)) or not 1 <= len(files) <= 24:
        raise PlaybackError('Expected 1 to 24 ordered motion files.')
    previous = None
    names = set()
    for part in files:
        first, last, _ = points(part)
        if part['name'] in names or previous is not None and not near(previous, first, .000015, .000015):
            raise PlaybackError('Duplicate part name or disconnected part boundary.')
        previous = last
        names.add(part['name'])


def tag(run_id, part):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
        raise PlaybackError('Invalid part run ID.')
    return _signature(run_id, part['text'])


@dataclass(frozen=True)
class RecordedPart:
    """The receipt and submitted file saved together by another drawing client."""
    receipt: str
    part: dict


@lru_cache(maxsize=4)
def _signature(run_id, text):
    return hashlib.sha256((run_id + '\0' + text).encode('ascii')).hexdigest()


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OasisPlayer:
    def __init__(self, base_url, timeout=12):
        url = parse.urlsplit(base_url)
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.path not in ('','/') or url.query or url.fragment:
            raise ValueError('Supply an explicit controller origin.')
        self.origin = base_url.rstrip('/')
        self.timeout = timeout
        self.identity = None
        self.device_id = None
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
        # A caller restarting this process must use its durable dispatch journal.
        self.attempted = set()

    def _request(self, path, body=None, headers=None, as_json=True):
        req = request.Request(self.origin + path, data=body, headers=headers or {})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(32769)
                if len(raw) > 32768:
                    raise PlaybackError('Unexpected controller response size.')
                return json.loads(raw) if as_json else raw
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise PlaybackError(f'Controller {path} did not confirm the request: {exc}') from exc

    def _observe(self):
        guest = self._request('/guest-state')
        status = self._request('/status')
        if (not isinstance(status,dict) or not isinstance(guest,dict) or
                not {'rev','evolving','pending'} <= guest.keys() or
                not {'state','homed','fault','paused','queue','auto','boot_pending','receipt','theta','rho','device_id',
                     'cal','steps_rev','home_steps'} <= status.keys() or
                not isinstance(status['receipt'],dict) or not {'id','state'} <= status['receipt'].keys()):
            raise PlaybackError('The controller does not support tagged physical playback.')
        device = status['device_id']
        if not isinstance(device, str) or not re.fullmatch(r'[0-9a-f]{24}', device) or not isinstance(status['cal'], dict):
            raise PlaybackError('The controller did not identify its board and calibration.')
        calibration = [status['cal'], status['steps_rev'], status['home_steps']]
        try:
            encoded = json.dumps(calibration, sort_keys=True, allow_nan=False, separators=(',',':')).encode()
        except (TypeError, ValueError) as exc:
            raise PlaybackError('Invalid controller calibration.') from exc
        identity = device + ':' + hashlib.sha256(encoded).hexdigest()
        if self.identity not in (None, identity):
            raise PlaybackError('The controller or its calibration differs from the bound Oasis.')
        self.identity, self.device_id = identity, device
        return status, guest

    def bind_identity(self, expected=None):
        if expected is not None:
            if self.identity not in (None, expected):
                raise PlaybackError('A different Oasis is already bound.')
            self.identity = expected
        self._observe()
        return self.identity

    @staticmethod
    def _healthy(s, g):
        return (s['homed'] == 1 and s['fault'] == 0 and s['paused'] == 0 and s['queue'] == [] and
                s['auto'] == 0 and s['boot_pending'] == 0 and g['evolving'] is False and g['pending'] is False)

    @staticmethod
    def _at(status, point):
        position = status['theta'], status['rho']
        return all(type(x) in (int,float) and math.isfinite(x) for x in position) and near(position, point)

    def _available(self, status, guest, first):
        if status['state'] != 'idle' or not self._healthy(status, guest):
            raise PlaybackError('The table must be idle, homed and clear of other scheduled drawings.')
        if not self._at(status, first):
            raise PlaybackError('The ball is away from the first point of this part.')

    def check(self, part):
        first, _, _ = points(part)
        status, guest = self._observe()
        self._available(status, guest, first)
        if status['receipt']['state'] in ('staged','running'):
            raise PlaybackError('Another part is waiting on the controller.')

    def _result(self, expected, end, status, guest):
        receipt = status['receipt']
        if receipt['id'] != expected:
            return 'unknown'
        state = receipt['state']
        if state == 'running' and status['paused'] and not status['fault']:
            return 'paused'
        if not self._healthy(status, guest):
            return 'failed'
        if state == 'complete':
            return 'complete' if status['state'] == 'idle' and self._at(status, end) else 'failed'
        if state == 'running':
            return 'running' if status['state'] in ('moving','drawing') else 'unknown'
        return state if state in ('staged','failed') else 'unknown'

    def inspect(self, run_id, part):
        _, end, _ = points(part)
        return self._result(tag(run_id, part), end, *self._observe())

    def play(self, part, run_id, predecessor=None):
        first, end, count = points(part)
        expected = tag(run_id, part)
        status, guest = self._observe()
        existing = self._result(expected, end, status, guest)
        if existing != 'unknown' or run_id in self.attempted:
            return existing
        self._available(status, guest, first)
        if status['receipt']['state'] in ('staged','running'):
            raise PlaybackError('Another part is waiting on the controller.')
        headers = {'X-Oasis-Run':expected, 'X-Guest-Rev':str(guest['rev']), 'X-Oasis-Device':self.device_id,
                   'Content-Type':'application/octet-stream'}
        if predecessor is not None:
            if isinstance(predecessor, RecordedPart):
                previous = predecessor.receipt
                if not isinstance(previous, str) or not re.fullmatch(r'[0-9a-f]{64}', previous):
                    raise PlaybackError('Invalid receipt for the preceding drawing.')
                _, previous_end, previous_count = points(predecessor.part)
                if status.get('index') != previous_count or status.get('total') != previous_count:
                    raise PlaybackError('The controller did not finish the recorded number of points.')
            else:
                previous_id, previous_part = predecessor
                _, previous_end, _ = points(previous_part)
                previous = tag(previous_id, previous_part)
            if self._result(previous, previous_end, status, guest) != 'complete':
                raise PlaybackError('The preceding part is no longer the last completed drawing.')
            headers['X-Oasis-Previous'] = previous
        self.attempted.add(run_id)
        try:
            uploaded = self._request('/thr', part['text'].encode('ascii'), headers)
            if not isinstance(uploaded,dict) or uploaded.get('points') != count or uploaded.get('skipped') != 0:
                raise PlaybackError('The controller did not accept every point in the part.')
            status, guest = self._observe()
            proof = self._result(expected, end, status, guest)
            if proof != 'staged':
                return proof
            self._available(status, guest, first)
            self._request('/play', b'', {'X-Oasis-Run':expected, 'X-Oasis-Device':self.device_id}, as_json=False)
        except PlaybackError as exc:
            # A reply may have been lost after the controller accepted the command.
            # Never resend: read the controller's receipt for these exact bytes.
            proof = self.inspect(run_id, part)
            if proof != 'unknown':
                return proof
            raise PlaybackError('No matching receipt after dispatch. Inspect the table before recovery.') from exc
        return self.inspect(run_id, part)
