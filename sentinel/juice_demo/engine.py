"""Run bounded, real HTTP tests against a pinned, workspace-local Juice Shop.

Red probes and Blue's patch are scripted. Test outcomes are never pre-recorded.
The only targets are loopback ports 3001 and 3002; no user-supplied target URLs.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local'
SOURCE = LOCAL / 'juice-shop'
CANDIDATE = LOCAL / 'juice-shop-candidate'
RUNTIME = LOCAL / 'runtime/node_modules/node/bin/node'
VERSION = '19.2.1'
COMMIT = '8d112d69a4c927579bc5e9ce0b4f2b3894bb4382'
PORTS = {'baseline': 3001, 'candidate': 3002}
OLD_QUERY = "`SELECT * FROM Users WHERE email = '${req.body.email || ''}' AND password = '${security.hash(req.body.password || '')}' AND deletedAt IS NULL`, { model: UserModel, plain: true }"
NEW_QUERY = "'SELECT * FROM Users WHERE email = :email AND password = :password AND deletedAt IS NULL', { replacements: { email: req.body.email || '', password: security.hash(req.body.password || '') }, model: UserModel, plain: true }"
PASSWORD = 'Sentinel-demo-only-42!'


class DemoError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def request(target, path, body=None, token=None):
    """Only fixed loopback origins. Return sanitized evidence, never store session tokens."""
    if target not in PORTS or not path.startswith('/') or path.startswith('//'):
        raise ValueError('Unsupported local target')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(f'http://127.0.0.1:{PORTS[target]}{path}',
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            status, raw = response.status, response.read(2_000_000)
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read(2_000_000)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DemoError(f'Local Juice Shop on port {PORTS[target]} is unavailable. Start or reset the demo.', 503) from error
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        data = {}
    return status, data, round((time.monotonic() - start) * 1000)


def probe(target, label, email, expected_blocked=False):
    status, data, elapsed = request(target, '/rest/user/login', {'email': email, 'password': 'deliberately-wrong'})
    auth = data.get('authentication') or {}
    authenticated = status == 200 and bool(auth.get('token'))
    return {'label': label, 'method': 'POST', 'path': '/rest/user/login', 'email': email,
            'password': 'deliberately-wrong', 'status': status, 'authenticated': authenticated,
            'identity': auth.get('umail'), 'elapsed_ms': elapsed,
            'passed': (status == 401 and not authenticated) if expected_blocked else authenticated}


class DemoEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.processes = {}
        self.state = {'phase': 'idle', 'active_version': 1, 'events': []}
        self.work = LOCAL / 'juice-demo'
        self.work.mkdir(parents=True, exist_ok=True)

    def event(self, actor, action, **details):
        event = {'seq': len(self.state['events']) + 1, 'timestamp': time.time(),
                 'actor': actor, 'action': action, **details}
        self.state['events'].append(event)
        with (self.work / 'audit.jsonl').open('a') as output:
            output.write(json.dumps({'run_id': self.state.get('run_id'), **event}) + '\n')

    def snapshot(self):
        return {**self.state, 'target': {'name': 'OWASP Juice Shop', 'version': VERSION, 'commit': COMMIT,
                'baseline_url': 'http://127.0.0.1:3001', 'candidate_url': 'http://127.0.0.1:3002',
                'active_url': f"http://127.0.0.1:{3002 if self.state['active_version'] == 2 else 3001}"},
                'mode': 'Scripted Red/Blue · live HTTP evidence',
                'setup_ready': (SOURCE / 'build/app.js').exists() and RUNTIME.exists()}

    def require(self, phase):
        if self.state['phase'] != phase:
            raise DemoError(f"Expected {phase}; this run is {self.state['phase']}. Follow the steps in order.")

    def stop(self, name):
        process = self.processes.pop(name, None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def close(self):
        for name in list(self.processes):
            self.stop(name)

    def start(self, name, directory):
        # Refuse to adopt or kill an unrelated process on a demo port.
        import socket
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', PORTS[name]))
            except OSError as error:
                raise DemoError(f'Port {PORTS[name]} is busy. Stop the other app using that port and retry.', 503) from error
        server_file = directory / 'build/server.js'
        code = server_file.read_text()
        code = code.replace('server.listen(port, () => {', "server.listen(port, '127.0.0.1', () => {")
        if "server.listen(port, '127.0.0.1', () => {" not in code:
            raise DemoError('Pinned Juice Shop listener changed; cannot enforce loopback binding.', 503)
        server_file.write_text(code)
        env = {**os.environ, 'PORT': str(PORTS[name]), 'NODE_ENV': 'production',
               'NODE_OPTIONS': '', 'NODE_CONFIG': json.dumps({'server': {'port': PORTS[name]}})}
        with (self.work / f'{name}.log').open('w') as log:
            process = subprocess.Popen([str(RUNTIME), 'build/app.js'], cwd=directory, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
        self.processes[name] = process
        for _ in range(150):
            if process.poll() is not None:
                raise DemoError(f'Juice Shop stopped during startup. See .local/juice-demo/{name}.log.', 503)
            try:
                status, data, _ = request(name, '/rest/products/search?q=apple')
                if status == 200 and isinstance(data.get('data'), list) and data['data']:
                    return
            except DemoError:
                pass
            time.sleep(.2)
        self.stop(name)
        raise DemoError('Juice Shop startup timed out; inspect the local log and retry.', 503)

    def reset(self):
        if not (SOURCE / 'build/app.js').exists() or not RUNTIME.exists():
            raise DemoError('Run make juice-setup first to install the pinned local app.', 503)
        installed = json.loads((SOURCE / 'package.json').read_text())['version']
        if installed != VERSION:
            raise DemoError('Unexpected Juice Shop version. Run make juice-setup.', 503)
        self.close()
        self.state = {'phase': 'idle', 'active_version': 1, 'events': [], 'run_id': str(uuid.uuid4())}
        self.start('baseline', SOURCE)
        self.state['phase'] = 'ready'
        self.event('simulator', 'start_local_app', version=VERSION, commit=COMMIT, port=3001)
        return self.snapshot()

    def red(self):
        self.require('ready')
        probes = []
        for label, email in [('Wrong password control', 'admin@juice-sh.op'),
                             ('Quote syntax probe', "'"),
                             ('SQL condition bypass', "' OR 1=1--")]:
            probes.append(probe('baseline', label, email))
            self.event('red:scripted', 'login_probe', result=probes[-1])
        found = probes[-1]['authenticated'] and not probes[0]['authenticated']
        self.state['red'] = {'probes': probes, 'vulnerability_confirmed': found,
                             'finding': 'SQL injection in login: email input is interpolated into a database query.'}
        if not found:
            raise DemoError('The expected bypass was not reproduced. Evidence is retained; reset before retrying.', 422)
        self.state['phase'] = 'attacked'
        return self.snapshot()

    def blue(self):
        self.require('attacked')
        source_file = SOURCE / 'routes/login.ts'
        before = source_file.read_text()
        if before.count(OLD_QUERY) != 1:
            raise DemoError('Login source does not match the pinned patch; no files were changed.', 422)
        after = before.replace(OLD_QUERY, NEW_QUERY)
        diff = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                          fromfile='a/routes/login.ts', tofile='b/routes/login.ts'))
        # The candidate is an isolated copy; the baseline continues running unchanged.
        self.stop('candidate')
        if CANDIDATE.exists():
            shutil.rmtree(CANDIDATE)
        shutil.copytree(SOURCE, CANDIDATE, ignore=shutil.ignore_patterns('.git', 'node_modules', 'frontend', 'test', 'cypress'))
        (CANDIDATE / 'node_modules').symlink_to(SOURCE / 'node_modules', target_is_directory=True)
        (CANDIDATE / 'frontend').symlink_to(SOURCE / 'frontend', target_is_directory=True)
        (CANDIDATE / 'routes/login.ts').write_text(after)
        patch_path = self.work / 'login.patch'
        patch_path.write_text(diff)
        # Compile the real patched TypeScript handler with Juice Shop's own compiler.
        compile_code = """const ts=require('typescript'),fs=require('fs');const input=fs.readFileSync('routes/login.ts','utf8');const out=ts.transpileModule(input,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,esModuleInterop:true},reportDiagnostics:true});if(out.diagnostics.some(d=>d.category===ts.DiagnosticCategory.Error))process.exit(1);fs.writeFileSync('build/routes/login.js',out.outputText);"""
        result = subprocess.run([str(RUNTIME), '-e', compile_code], cwd=CANDIDATE, capture_output=True, timeout=30)
        if result.returncode:
            raise DemoError('The proposed handler failed compilation. Candidate not activated.', 422)
        self.start('candidate', CANDIDATE)
        self.state['patch'] = {'file': 'routes/login.ts', 'diff': diff, 'sha256': hashlib.sha256(after.encode()).hexdigest(),
                               'summary': 'Bind email and password as SQL values instead of interpolating user input.',
                               'runtime_sha256': hashlib.sha256((CANDIDATE / 'build/routes/login.js').read_bytes()).hexdigest()}
        self.state['phase'] = 'proposed'
        self.event('blue:scripted', 'candidate_patch_built', sha256=self.state['patch']['sha256'])
        return self.snapshot()

    def normal_checks(self, target):
        checks = []
        def check(label, passed, status):
            checks.append({'label': label, 'passed': bool(passed), 'status': status})
        status, products, _ = request(target, '/rest/products/search?q=apple')
        check('Search returns products', status == 200 and bool(products.get('data')), status)
        email = f"sentinel-{uuid.uuid4().hex[:12]}@example.test"
        status, _, _ = request(target, '/api/Users/', {'email': email, 'password': PASSWORD, 'passwordRepeat': PASSWORD})
        check('Register a normal customer', status == 201, status)
        status, auth, _ = request(target, '/rest/user/login', {'email': email, 'password': PASSWORD})
        token = (auth.get('authentication') or {}).get('token')
        check('Correct password logs in', status == 200 and bool(token), status)
        bid = (auth.get('authentication') or {}).get('bid')
        status, basket, _ = request(target, f'/rest/basket/{bid}', token=token) if token and bid else (0, {}, 0)
        check('Customer can open their basket', status == 200 and basket.get('status') == 'success', status)
        wrong = probe(target, 'Wrong password stays rejected', email, expected_blocked=True)
        check(wrong['label'], wrong['passed'], wrong['status'])
        return checks

    def evaluate(self):
        self.require('proposed')
        heldout = [("Alternate equality", "' OR 'x'='x'--"), ("Numeric condition", "' OR 2>1--"),
                   ("Comment spacing", "' OR 1=1 -- ")]
        attacks = {target: [probe(target, label, email, expected_blocked=target == 'candidate')
                            for label, email in heldout] for target in PORTS}
        normal = {target: self.normal_checks(target) for target in PORTS}
        gates = [
            {'name': 'Original exploit blocked', 'passed': probe('candidate', 'Original Red exploit', "' OR 1=1--", True)['passed']},
            {'name': 'Unseen probe variants blocked', 'passed': all(p['passed'] for p in attacks['candidate'])},
            {'name': 'Baseline reproduces all variants', 'passed': all(p['authenticated'] for p in attacks['baseline'])},
            {'name': 'Normal flows pass before and after', 'passed': all(c['passed'] for checks in normal.values() for c in checks)},
            {'name': 'Candidate matches evaluated patch', 'passed': self.patch_matches()},
        ]
        self.state['evaluation'] = {'attacks': attacks, 'normal': normal, 'gates': gates,
                                    'eligible': all(g['passed'] for g in gates), 'patch_sha256': self.state['patch']['sha256']}
        self.state['phase'] = 'evaluated'
        self.event('evaluator', 'evaluate_real_http', report=self.state['evaluation'])
        return self.snapshot()

    def patch_matches(self):
        patch = self.state.get('patch')
        if not patch or not (CANDIDATE / 'build/routes/login.js').exists():
            return False
        return (hashlib.sha256((CANDIDATE / 'routes/login.ts').read_bytes()).hexdigest() == patch['sha256'] and
                hashlib.sha256((CANDIDATE / 'build/routes/login.js').read_bytes()).hexdigest() == patch['runtime_sha256'])

    def decide(self, decision):
        self.require('evaluated')
        if decision not in ('approve', 'reject'):
            raise DemoError('Choose approve or reject.', 422)
        if decision == 'approve':
            if not self.state['evaluation']['eligible'] or not self.patch_matches():
                raise DemoError('Approval blocked: safety gates failed or the evaluated patch changed.')
            process = self.processes.get('candidate')
            if process is None or process.poll() is not None:
                raise DemoError('Candidate is no longer running. Reset and evaluate a fresh round.')
            self.state['active_version'] = 2
        self.state['decision'] = decision
        self.state['phase'] = 'decided'
        self.event('human', decision, active_version=self.state['active_version'])
        return self.snapshot()

    def rechallenge(self):
        self.require('decided')
        target = 'candidate' if self.state['active_version'] == 2 else 'baseline'
        fresh = probe(target, 'Fresh SQL expression', "' OR (3*3)=9--", expected_blocked=True)
        self.state['rechallenge'] = fresh
        self.state['phase'] = 'complete'
        self.event('evaluator', 'fresh_rechallenge', active_version=self.state['active_version'], result=fresh)
        return self.snapshot()
