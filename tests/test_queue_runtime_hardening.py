from __future__ import annotations

import pytest

from voicelink.queue import Queue


class _ExplodingSequence:
    def __getitem__(self, _index):
        raise RuntimeError("boom")


def _msg(key: str) -> str:
    return key


def test_queue_is_empty_only_treats_missing_items_as_empty() -> None:
    queue = Queue(10, True, _msg)
    queue._queue = _ExplodingSequence()

    with pytest.raises(RuntimeError, match="boom"):
        _ = queue.is_empty


def test_queue_get_does_not_swallow_unexpected_runtime_errors() -> None:
    queue = Queue(10, True, _msg)
    queue._queue = _ExplodingSequence()

    with pytest.raises(RuntimeError, match="boom"):
        queue.get()
