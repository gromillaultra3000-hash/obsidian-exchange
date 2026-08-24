# Python SDK

```python
from lumi_client import LumiClient
client = LumiClient('http://127.0.0.1:8000')
print(client.health())
print(client.resolve('Analyze this request safely'))
```
