import sys
sys.path.insert(0, '../../sdk/python')
from lumi_client import LumiClient

client = LumiClient()
session = client.create_dialog_session(title='Example Dialog Session')
print(client.send_dialog_message(session['sessionId'], 'Analyze this request safely'))
