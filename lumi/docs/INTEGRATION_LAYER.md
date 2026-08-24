# Integration Layer

Lumi v0.7 provides a neutral host application integration layer. A host application can register a manifest, complete a handshake, send events, call `/resolve`, use dialog sessions, register actions, and receive approval prompt data.

The integration layer does not execute host actions directly. All action requests pass through the Action Gateway and Policy Engine.
