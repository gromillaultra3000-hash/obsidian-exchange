from pathlib import Path

APP_JS = (Path(__file__).resolve().parents[1] / 'lumi/app/static/app.js').read_text(encoding='utf-8')

def test_dialog_contract():
    assert '/dialog/sessions' in APP_JS
    assert '/dialog/sessions/${activeSessionId}/message' in APP_JS

def test_approval_contract_only_records_decisions():
    assert '/actions/approvals' in APP_JS
    assert '/decision' in APP_JS
    assert '/actions/propose' not in APP_JS or 'execute' not in APP_JS.lower()

def test_ui_no_dangerous_local_actions():
    lower = APP_JS.lower()
    assert 'shell' not in lower
    assert 'subprocess' not in lower
    assert 'canapplytohost = true' not in lower
    assert 'canapply = true' not in lower
    assert 'fetch("http://' not in lower
    assert "fetch('http://" not in lower
