const { LumiClient } = require('../../sdk/javascript/src/client');
(async () => { const client = new LumiClient(); const session = await client.createDialogSession({ title: 'Example JS Dialog' }); console.log(await client.sendDialogMessage(session.sessionId, 'Analyze this request safely')); })();
