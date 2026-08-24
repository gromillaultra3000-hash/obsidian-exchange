import os, sys

def main():
    print('Python version:', sys.version)
    ok=True
    try:
        import fastapi
        print('[OK] FastAPI', getattr(fastapi,'__version__',''))
    except Exception:
        print('[FAIL] FastAPI not installed'); ok=False
    try:
        import uvicorn
        print('[OK] Uvicorn available')
    except Exception:
        print('[FAIL] Uvicorn not installed'); ok=False
    for d in ['data','logs']:
        os.makedirs(d, exist_ok=True)
        print('[OK]' if os.access(d, os.W_OK) else '[WARN]', d)
    if os.path.exists(os.path.join('lumi','app','static','index.html')): print('[OK] UI static assets found')
    else: print('[WARN] UI static assets not found')
    return 0 if ok else 1
if __name__ == '__main__': raise SystemExit(main())
