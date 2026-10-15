"""Public error types returned by the runner."""


class RequestError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
