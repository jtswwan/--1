import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from tracker.source import FetchError, _extract_json_object


def test_extracts_object_with_braces_inside_strings():
    html = 'x = {"desc": "有 { 跟 } 在字串裡", "Price": 2190.0};'
    assert _extract_json_object(html, "x = ")["Price"] == 2190.0


def test_extracts_object_with_escaped_quotes():
    html = r'x = {"desc": "他說 \"便宜\"", "Price": 1}'
    assert _extract_json_object(html, "x = ")["desc"] == '他說 "便宜"'


def test_extracts_nested_objects():
    html = 'x = {"a": {"b": {"c": 1}}, "Price": 2}'
    assert _extract_json_object(html, "x = ")["a"]["b"]["c"] == 1


def test_missing_anchor_raises():
    with pytest.raises(FetchError):
        _extract_json_object("<html></html>", "x = ")


def test_unterminated_object_raises():
    with pytest.raises(FetchError):
        _extract_json_object('x = {"a": 1', "x = ")
