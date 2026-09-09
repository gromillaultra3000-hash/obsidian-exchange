#!/usr/bin/env python3
"""TON Connect persistent intent rollout; reuse reviewed atomic file/metadata/runtime operations."""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'docs/e4-wallet-cross-tab/rollout.py'
INVENTORY = ROOT / 'docs/e4-tonconnect-intent/ops-baseline.json'
spec = importlib.util.spec_from_file_location('e4_reviewed_rollout', HELPER)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
shared.NAMES = ('tcConnect',)
shared.SCOPE = ['tcConnectionIntent and tcConnectionPayloads declarations after tcPreparation', 'tcHandleWallet owned challenge consumption preamble', 'tcConnect connection intent installation and owned cleanup']
STATE = b'        let tcConnectionIntent = null;\n        const tcConnectionPayloads = new Set();\n'


def scoped(data):
    old = b'        let tcPreparation = null;\n'
    new = old + STATE
    shared.require(data.count(new) <= 1, 'Connection intent state ambiguous')
    data = data.replace(new, old)
    pattern = rb'(?m)^        async function tcHandleWallet\(w\) \{\n.*?(?=^            tcPending = true;)'
    data, count = re.subn(pattern, b'TC_OWNED_CONNECTION_PREAMBLE\n', data, flags=re.S)
    shared.require(count == 1, 'TC handler preamble missing/ambiguous')
    return shared.stripped(data)


def bounded(before, after):
    shared.require(before != after, 'Empty candidate')
    shared.require(scoped(before) == scoped(after), 'Changes outside authorized TON connection intent scope')
    shared.require(before.count(STATE) == 0 and after.count(STATE) == 1, 'Missing/unexpected connection intent state addition')


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
