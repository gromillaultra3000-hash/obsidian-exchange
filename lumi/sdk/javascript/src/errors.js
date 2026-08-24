class LumiClientError extends Error {
  constructor(message, statusCode = null, errorData = {}) { super(message); this.name = 'LumiClientError'; this.statusCode = statusCode; this.errorData = errorData; }
}
module.exports = { LumiClientError };
