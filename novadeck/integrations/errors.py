"""Stable message keys for integrations; never expose launch arguments in errors."""


class IntegrationError(Exception):
    def __init__(self, key: str):
        self.key = key
        super().__init__(key)
