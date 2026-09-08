"""Build integrity, extraction fidelity and inert boundaries for the device page."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / 'scripts/build_e4_wallet_device_check.py'
SOURCE = ROOT / 'relay/webapp.html'
OUTPUT = ROOT / 'preview/e4-wallet-device-check'
spec = importlib.util.spec_from_file_location('device_builder', GENERATOR)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_committed_build_matches_source_and_generator_byte_exact():
    expected = builder.build(SOURCE)
    assert {p.name for p in OUTPUT.iterdir()} == set(expected)
    for name, content in expected.items():
        assert (OUTPUT / name).read_text() == content
    manifest = json.loads(expected['manifest.json'])
    assert manifest['build']['sourceSHA256'] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    for name, digest in manifest['artifacts'].items():
        assert hashlib.sha256(expected[name].encode()).hexdigest() == digest


def test_extracted_logical_code_is_exact_after_reversing_declared_transforms():
    files = builder.build(SOURCE)
    original, _ = builder.extract(SOURCE.read_text())
    manifest = json.loads(files['manifest.json'])
    extracted = files['device-check.js'].split('// BEGIN EXTRACTED PRODUCTION\n')[1].split('\n// END EXTRACTED PRODUCTION')[0]
    for old, new in manifest['namespaces'].items():
        assert old not in files['device-check.js']
        extracted = extracted.replace("'" + new + "'", "'" + old + "'")
    changed_styles = 0
    for style, classname in manifest['styleExternalization'].items():
        token = 'class="' + classname + '"'
        changed_styles += extracted.count(token)
        extracted = extracted.replace(token, 'style="' + style + '"')
    assert changed_styles == 3
    assert extracted == original


def test_static_page_has_no_active_remote_or_authentication_surface():
    files = builder.build(SOURCE)
    html, script = files['index.html'], files['device-check.js']
    assert 'style=' not in html and 'style=' not in script
    assert not re.search(r'\son\w+\s*=|<form\b|<iframe\b', html, re.I)
    assert re.findall(r'<script\b[^>]*src="([^"]+)"', html) == ['device-check.js']
    assert "connect-src 'none'" in html and "script-src 'self'" in html and "style-src 'self'" in html
    for forbidden in ['fetch(', 'XMLHttpRequest', 'sendBeacon', 'initData', 'userAgent', 'TonConnectUI', 'https://', 'http://']:
        assert forbidden not in script
    assert 'environment: {userChoice:' in script and 'verified: false' in script
    assert 'realWalletConnected: false, realTransferPerformed: false' in script
    assert 'navigator.clipboard.writeText(report.value)' in script
    assert 'report.focus(); report.select();' in script
    # Report excludes the synthetic sender too; users need only the behavior evidence.
    report = script.split('function deviceReport() {')[1].split('function deviceUpdate()')[0]
    assert 'deviceAddress' not in report and 'walletAttempt.wallet' not in report


@pytest.mark.parametrize('injected', ["fetch ('/api/wallet/send-request');", 'localStorage.clear();', 'new XMLHttpRequest();'])
def test_future_active_dependency_is_rejected(tmp_path, injected):
    source = SOURCE.read_text().replace('        function walletAttemptCapabilities() {', '        function unexpected() { ' + injected + ' }\n        function walletAttemptCapabilities() {')
    path = tmp_path / 'webapp.html'
    path.write_text(source)
    with pytest.raises(ValueError):
        builder.build(path)


def test_namespace_declaration_drift_is_rejected(tmp_path):
    path = tmp_path / 'webapp.html'
    path.write_text(SOURCE.read_text().replace("'oe.wallet-handoff.v1'", "'changed-lock'"))
    with pytest.raises(ValueError, match='declaration drift'):
        builder.build(path)


def test_check_mode_refuses_tampered_or_extra_artifact(tmp_path):
    files = builder.build(SOURCE)
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    command = ['python3', str(GENERATOR), '--check', '--output', str(tmp_path)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    (tmp_path / 'device-check.js').write_text('throw Error("tampered");')
    assert subprocess.run(command, capture_output=True).returncode != 0
    (tmp_path / 'device-check.js').write_text(files['device-check.js'])
    (tmp_path / 'unexpected.js').write_text('')
    assert subprocess.run(command, capture_output=True).returncode != 0
