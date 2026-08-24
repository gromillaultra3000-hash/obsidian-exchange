from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def register(pid):
    return client.post('/providers', json={'providerId':pid,'displayName':pid,'providerType':'mock','apiFormat':'json','enabled':True,'roles':[],'capabilities':[],'costProfile':{},'latencyProfile':{},'reliabilityScore':1.0})


def test_validation_normalize_works():
    register('api-norm')
    response = client.post('/validation/normalize', json={'providerId':'api-norm','rawOutput':{'status':'success','answer':'Test answer','confidence':0.8}})
    assert response.status_code == 200
    assert response.json()['output']['answer'] == 'Test answer'


def test_validation_validate_output_works():
    register('api-validate')
    response = client.post('/validation/validate-output', json={'providerId':'api-validate','rawOutput':{'status':'success','answer':'Valid answer','confidence':0.85,'suggestedStatus':'APPROVE','assumptions':['Good'],'evidenceRefs':['ev1']}})
    assert response.status_code == 200
    assert response.json()['validationStatus'] == 'valid'


def test_validation_validate_batch_works():
    register('api-batch')
    response = client.post('/validation/validate-batch', json={'task':{'input':'test'},'outputs':[{'providerId':'api-batch','rawOutput':{'status':'success','answer':'Answer 1','confidence':0.8,'assumptions':['OK'],'evidenceRefs':['ev1']}}]})
    assert response.status_code == 200
    assert response.json()['totalOutputs'] == 1
