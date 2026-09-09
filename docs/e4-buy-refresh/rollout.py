#!/usr/bin/env python3
"""BUY recipient refresh rollout; reuse reviewed atomic file/metadata/runtime operations."""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'docs/e4-wallet-cross-tab/rollout.py'
INVENTORY = ROOT / 'docs/e4-buy-refresh/ops-baseline.json'
spec = importlib.util.spec_from_file_location('e4_reviewed_rollout', HELPER)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
shared.NAMES = ('applyOfferings', 'onCurrencyChange', 'updateAddressPlaceholder', 'beginBuyOrder')
shared.SCOPE = ['buyReviewRoute state and validBuyOfferings/renderBuyNetworks/buyRouteSignature helpers', 'applyOfferings and onCurrencyChange refresh preservation', 'updateAddressPlaceholder explicit route changes', 'beginBuyOrder current route guard']


def scoped(data):
    data, count = re.subn(rb'(?m)^        let buyReviewRoute = null;\n', b'', data)
    shared.require(count <= 1, 'Review route state ambiguous')
    for name in ('validBuyOfferings', 'renderBuyNetworks', 'buyRouteSignature'):
        pattern = rb'(?m)^        function ' + name.encode() + rb'\([^\n]*\) \{\n.*?^        \}\n'
        data, count = re.subn(pattern, b'', data, flags=re.S)
        shared.require(count <= 1, 'Helper boundary ambiguous')
    return shared.stripped(data)


def bounded(before, after):
    shared.require(before != after, 'Empty candidate')
    shared.require(scoped(before) == scoped(after), 'Changes outside authorized recipient refresh scope')


shared.bounded = bounded
original_execute = shared.execute


def prepare(args):
    baseline = json.loads(INVENTORY.read_text())
    live = Path(shared.TARGET).read_bytes()
    candidate = args.candidate.resolve().read_bytes()
    shared.require(shared.sha(candidate) == args.candidate_sha, 'Candidate digest mismatch')
    bounded(live, candidate)
    plan = dict(target=shared.TARGET, candidate=str(args.candidate.resolve()),
                candidate_sha=shared.sha(candidate), baseline_sha=shared.sha(live),
                inventory_sha=shared.sha(INVENTORY.read_bytes()),
                helper_sha=shared.sha(HELPER.read_bytes()),
                rollout_sha=shared.sha(Path(__file__).read_bytes()),
                metadata=shared.metadata(Path(shared.TARGET)), bot_username=args.bot_username,
                url='https://obsidian-exchange.org/webapp',
                inputs=[entry for file in baseline['files'] for entry in file['liveInputs']],
                units=baseline['units'], scope=shared.SCOPE)
    shared.check_files(plan, plan['baseline_sha'])
    expected = next(x['sha256'] for x in plan['inputs'] if x['path'] == shared.TARGET)
    shared.require(expected == plan['baseline_sha'], 'Inventory baseline mismatch')
    shared.runtime(plan)
    plan['baseline_public_sha'] = shared.public(plan, live)
    shared.require(not args.plan.exists(), 'Plan already exists; regenerate under a new name')
    shared.write_json(args.plan, plan)
    return {'result': 'PREPARED', 'candidate_sha': plan['candidate_sha']}


def execute(plan, action, backup):
    shared.require(plan['target'] == shared.TARGET, 'Invalid rollout target')
    shared.require(shared.sha(INVENTORY.read_bytes()) == plan['inventory_sha'], 'Inventory digest mismatch')
    shared.require(shared.sha(HELPER.read_bytes()) == plan['helper_sha'], 'Shared helper digest mismatch')
    shared.require(shared.sha(Path(__file__).read_bytes()) == plan['rollout_sha'], 'Rollout digest mismatch')
    baseline = json.loads(INVENTORY.read_text())
    shared.require(plan['inputs'] == [entry for file in baseline['files'] for entry in file['liveInputs']], 'Inventory input mismatch')
    shared.require(plan['units'] == baseline['units'], 'Inventory unit mismatch')
    shared.require(plan['url'] == 'https://obsidian-exchange.org/webapp', 'Invalid public URL')
    return original_execute(plan, action, backup)


shared.prepare = prepare
shared.execute = execute
if __name__ == '__main__':
    shared.main()
