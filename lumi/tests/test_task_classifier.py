from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def classify(payload):
    return client.post('/routing/classify', json=payload).json()

def test_explicit_task_type():
    data = classify({'taskType':'code_review','input':'any input'})
    assert data['taskClass'] == 'code_review'
    assert data['confidence'] >= 0.9

def test_code_related_input():
    assert classify({'input':'Review this code for bugs and syntax errors'})['taskClass'] == 'code_review'

def test_patch_project_input():
    assert classify({'input':'Prepare patch and improve project architecture'})['taskClass'] in ['patch_planning','project_improvement','code_review']

def test_risk_related_input():
    assert classify({'input':'Analyze security risks and vulnerabilities in the system'})['taskClass'] == 'risk_review'

def test_unknown_input_becomes_general():
    assert classify({'input':'Hello, how are you?'})['taskClass'] == 'general_question'
