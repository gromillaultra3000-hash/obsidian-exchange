class LumiClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None, error_data: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_data = error_data or {}
