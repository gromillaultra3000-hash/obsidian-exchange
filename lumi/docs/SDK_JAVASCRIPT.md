# JavaScript SDK

```javascript
const { LumiClient } = require('./sdk/javascript/src/client');
const client = new LumiClient({ baseUrl: 'http://127.0.0.1:8000' });
client.health().then(console.log);
```
