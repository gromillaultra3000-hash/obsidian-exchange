# Local Sidecar Mode

Run Lumi next to a host application with:

```bash
python run_lumi.py
```

The host app calls Lumi via localhost REST API. First call `/health`, then `/integration/handshake`.
