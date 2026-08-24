const { LumiClient } = require('../../sdk/javascript/src/client');

async function main() {
  const client = new LumiClient({ baseUrl: 'http://127.0.0.1:8000' });
  console.log(await client.health());
  console.log(await client.version());
  const manifest = {
    hostAppId: 'example_js_app',
    displayName: 'Example JS App',
    appType: 'web',
    allowedModes: ['rest'],
    capabilitiesRequested: ['resolve'],
    actionsAllowed: [],
    eventsSupported: ['user_message'],
    callbacks: { mode: 'mock' },
    metadata: { source: 'example' }
  };
  console.log(await client.handshake(manifest));
}

main().catch(err => console.error(err.message));
