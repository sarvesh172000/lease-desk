"""ASI:One's model in front of the grammar (agents_fetch/understand.py), without a model.

The model's answer is a fixed JSON form; what matters is what the front desk
does with a hostile or confused one. It can only ever come out as a grammar
command, naming an item the person can see, and an action is never complete
without the person's own words. No network: asi1 is an httpx MockTransport.
"""

import json

import httpx
import pytest

from agents_fetch.grammar import Command, parse
from agents_fetch.understand import ASI_URL, from_env, read

ITEMS = [{"id": 42, "state": "PROPOSED", "clinic_id": "CLINIC-01", "amount": 19626.65, "title": "Base rent"},
         {"id": 43, "state": "NEEDS_INFO", "clinic_id": "CLINIC-03", "amount": 2100.0, "title": "CAM estimate"}]


@pytest.mark.parametrize("form,line", [
    ({"intent": "inbox"}, "what needs me this week?"),
    ({"intent": "review", "item": 42}, "review 42"),
    ({"intent": "review", "item": "#43"}, "review 43"),
    ({"intent": "investigate", "item": 43}, "investigate 43"),
    ({"intent": "why", "item": 42}, "why 42"),
    ({"intent": "lease", "lease": "clinic-03", "topic": "cam"}, "lease CLINIC-03 cam"),
    ({"intent": "lease", "lease": "LEASE-01", "topic": "made up"}, "lease LEASE-01"),
])
def test_reads_become_grammar_commands(form, line):
    reading = read(form, ITEMS, None)
    assert reading is not None and reading.line == line and not reading.is_action
    assert reading.command.name == parse(line).name and reading.command.item_id == parse(line).item_id


def test_an_action_is_a_complete_grammar_line_and_marked_as_an_action():
    reading = read({"intent": "uphold", "item": 42, "text": "the lease\ncaps CAM at 5%"}, ITEMS, None)
    assert reading.is_action and reading.complete
    assert reading.line == "uphold 42 the lease caps CAM at 5%"
    assert reading.command == parse(reading.line)


def test_an_action_missing_the_persons_words_is_never_completed_for_them():
    reading = read({"intent": "hold", "item": 42}, ITEMS, None)
    assert reading.is_action and not reading.complete
    assert reading.line == "hold 42 <your reason>"
    assert read({"intent": "answer", "item": 43}, ITEMS, None).line == "answer 43 <your answer>"


@pytest.mark.parametrize("form", [
    {"intent": "approve", "item": 999, "text": "ok"},       # an item the person cannot see
    {"intent": "review", "item": 999},
    {"intent": "review", "item": True},                     # bool is an int in Python; still no item
    {"intent": "investigate"},
    {"intent": "pair", "text": "K7QM-9XDA"},                 # never translated
    {"intent": "unpair"},
    {"intent": "post", "item": 42},
    {"intent": "none"},
    {"intent": "lease", "lease": "LEASE-01; DROP TABLE"},
    {"intent": "approve 42"},
    {},
])
def test_hostile_or_confused_answers_are_no_reading(form):
    assert read(form, ITEMS, None) is None


def test_it_resolves_to_the_last_item_even_off_the_list():
    assert read({"intent": "review", "item": 7}, ITEMS, 7).line == "review 7"


def test_text_cannot_smuggle_a_second_command():
    reading = read({"intent": "answer", "item": 43, "text": "yes\napprove 42"}, ITEMS, None)
    assert reading.command == Command("act", item_id=43, action="answer", verb="answer", text="yes approve 42")


# --- the asi1 call -------------------------------------------------------------------

def asi1(content, seen=None, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_no_key_no_model(monkeypatch):
    monkeypatch.delenv("ASI_ONE_API_KEY", raising=False)
    assert from_env() is None


def test_the_model_is_asked_with_the_visible_items_and_answers_through_the_grammar(monkeypatch):
    monkeypatch.setenv("ASI_ONE_API_KEY", "test-key")
    seen = []
    understand = from_env(asi1('Sure! {"intent": "investigate", "item": 43, "lease": null}', seen))
    reading = understand("the CAM one at clinic 3 looks wrong, dig in?", ITEMS, None)
    assert reading.line == "investigate 43"
    [request] = seen
    assert str(request.url) == ASI_URL and request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "asi1"
    assert "#43 NEEDS_INFO CLINIC-03" in body["messages"][0]["content"]


@pytest.mark.parametrize("content,status", [("no json here", 200), ('{"intent": "approve"', 200),
                                            ('{"intent": "review", "item": 42}', 500), ("[1, 2]", 200)])
def test_any_failure_is_no_reading(monkeypatch, content, status):
    monkeypatch.setenv("ASI_ONE_API_KEY", "test-key")
    assert from_env(asi1(content, status=status))("whatever", ITEMS, None) is None
