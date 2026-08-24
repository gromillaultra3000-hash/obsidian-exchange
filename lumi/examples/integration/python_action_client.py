import sys
sys.path.insert(0, '../../sdk/python')
from lumi_client import LumiClient

client = LumiClient()
client.register_action({'actionId': 'create_patch_preview', 'title': 'Create Patch Preview', 'description': 'Prepare patch preview', 'riskLevel': 'medium', 'requiresApproval': True, 'supportsDryRun': True, 'allowedModes': ['proposal', 'dry_run']})
print(client.propose_action('create_patch_preview', {'targetFiles': ['app/main.py']}, 'proposal'))
