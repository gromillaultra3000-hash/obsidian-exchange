from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'lumi' / 'app' / 'static'

def test_static_files_exist():
    assert (STATIC / 'index.html').exists()
    assert (STATIC / 'app.js').exists()
    assert (STATIC / 'styles.css').exists()
    for name in ['runtime','dialog','approvals','history','integration','projects','patches','sandbox','safety']:
        assert (STATIC / 'components' / f'{name}.js').exists()

def test_no_external_cdn_or_eval():
    text = ''.join(p.read_text(encoding='utf-8') for p in [STATIC/'index.html', STATIC/'app.js'])
    assert 'https://' not in text
    assert 'http://' not in text
    assert 'cdn' not in text.lower()
    assert 'eval(' not in text
    assert 'new Function' not in text

def test_no_fake_secrets_in_static():
    text = ''.join(p.read_text(encoding='utf-8') for p in STATIC.rglob('*') if p.is_file() and p.suffix not in {'.pyc', '.pyo'})
    assert 'sk-test' not in text
    assert 'api_key=' not in text.lower()
    assert 'password=' not in text.lower()
