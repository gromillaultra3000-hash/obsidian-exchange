from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def req(taskType, input='x'):
    return client.post('/routing/requirements', json={'taskType':taskType,'input':input}).json()

def test_code_review_requirements():
    data = req('code_review')
    assert 'code_analysis' in data['requiredCapabilities']
    assert 'code_reviewer' in data['requiredRoles']

def test_project_improvement_requirements():
    data = req('project_improvement')
    assert 'project_review' in data['requiredCapabilities']
    assert 'planning' in data['requiredCapabilities']
    assert 'error_analysis' in data['requiredCapabilities']

def test_general_question_requirements():
    data = client.post('/routing/requirements', json={'input':'General question'}).json()
    assert 'text_reasoning' in data['requiredCapabilities']

def test_decision_request_requirements():
    data = req('decision_request')
    assert 'decision_support' in data['requiredCapabilities']
    assert 'risk_review' in data['requiredCapabilities']
