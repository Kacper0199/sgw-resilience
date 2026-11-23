from __future__ import annotations

from services.llm_gateway.sse import SSEAccumulator, synthesize_events

RICH_MESSAGE = {
    "id": "msg_x",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "EqQBCkYI"},
        {
            "type": "text",
            "text": "Lock out the feeder first.",
            "citations": [
                {
                    "type": "search_result_location",
                    "source": "sop://LK-4",
                    "title": "Feeder lockout",
                    "cited_text": "Lock out the feeder before patrol.",
                    "search_result_index": 0,
                    "start_block_index": 0,
                    "end_block_index": 1,
                }
            ],
        },
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "get_asset",
            "input": {"asset_id": "PS-17", "depth": 2},
        },
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 1200,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 900,
        "output_tokens": 210,
    },
}


def test_synthesised_stream_round_trips_through_accumulator():
    acc = SSEAccumulator()
    payload = b"".join(synthesize_events(RICH_MESSAGE))
    for i in range(0, len(payload), 11):
        acc.feed(payload[i : i + 11])
    assert acc.message == RICH_MESSAGE


def test_accumulator_records_stream_error():
    acc = SSEAccumulator()
    acc.feed(b'event: error\ndata: {"type":"error","error":{"type":"overloaded_error","message":"x"}}\n\n')
    assert acc.error == {"type": "overloaded_error", "message": "x"}
    assert acc.message is None
