"""A stand-in for the Anthropic client, so the LLM layer is testable and the
whole suite runs with no API key and no network."""

from dataclasses import dataclass
from typing import List


@dataclass
class FakeUsage:
    input_tokens: int = 1200
    output_tokens: int = 300


class FakeResponse:
    def __init__(self, parsed, stop_reason="end_turn", stop_details=None):
        self.parsed_output = parsed
        self.usage = FakeUsage()
        self.stop_reason = stop_reason
        self.stop_details = stop_details


@dataclass
class FakeStopDetails:
    type: str = "refusal"
    category: str = "cyber"
    explanation: str = "declined"


class FakeMessages:
    def __init__(self, response_factory):
        self._factory = response_factory
        self.calls: List[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._factory(kwargs)


class FakeClient:
    """Returns whatever `response_factory(kwargs)` produces, and records every
    call so tests can assert on what was actually sent."""

    def __init__(self, response_factory):
        self.messages = FakeMessages(response_factory)
