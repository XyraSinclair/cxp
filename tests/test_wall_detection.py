#!/usr/bin/env python3
"""Regression tests for mid-stream quota-wall detection.

The bug these lock in: ChatGPT delivers a 5h-window rate-limit as an SSE error
event *inside a 200 stream, after token output has already started* — never as
an HTTP 429. cxp's prefix scanner (scan_sse_prefix) bails at the first output
event, so it never sees that wall; the account stays flagged "allowed", sticky
affinity re-pins every retry to the exhausted account, and the pool never fails
over (observed live: 56k requests, 0 detected walls). scan_sse_for_quota scans
the whole buffer and is what the live relay uses to flag the account walled so
the NEXT turn reroutes.

Run standalone:  python3 tests/test_wall_detection.py
Or via pytest:   pytest tests/test_wall_detection.py
"""
import importlib.machinery
import importlib.util
import pathlib

_CXP = pathlib.Path(__file__).resolve().parent.parent / "cxp"
_loader = importlib.machinery.SourceFileLoader("cxp_mod", str(_CXP))
_spec = importlib.util.spec_from_loader("cxp_mod", _loader)
cxp = importlib.util.module_from_spec(_spec)
_loader.exec_module(cxp)


def _sse(*events: bytes) -> bytes:
    """Join event JSON payloads into an SSE byte buffer (each block ends \\n\\n)."""
    return b"".join(b"data: " + e + b"\n\n" for e in events)


_OUTPUT = b'{"type":"response.output_text.delta","delta":"working on it"}'
_CREATED = b'{"type":"response.created","response":{}}'
_WALL = (b'{"type":"response.failed","response":{"error":'
         b'{"code":"usage_limit_reached","message":"You have hit your usage limit."}}}')
_WALL_TOPLEVEL = (b'{"type":"error","error":'
                  b'{"code":"rate_limit_exceeded","message":"Rate limit exceeded."}}')


def test_midstream_wall_is_detected():
    # output starts, THEN the wall arrives — the real-world shape.
    buf = _sse(_CREATED, _OUTPUT, _OUTPUT, _WALL)
    reason = cxp.scan_sse_for_quota(buf)
    assert reason, "mid-stream wall must be detected after output started"
    assert "usage_limit_reached" in reason


def test_prefix_scan_provably_misses_midstream_wall():
    # This is *why* scan_sse_for_quota exists: the prefix scanner bails at the
    # first output event and returns (None, output_started=True), missing the
    # wall that comes later in the same stream.
    buf = _sse(_CREATED, _OUTPUT, _OUTPUT, _WALL)
    reason, output_started = cxp.scan_sse_prefix(buf)
    assert reason is None, "prefix scan is expected to MISS the mid-stream wall"
    assert output_started is True


def test_toplevel_error_event_detected():
    buf = _sse(_CREATED, _OUTPUT, _WALL_TOPLEVEL)
    reason = cxp.scan_sse_for_quota(buf)
    assert reason and "rate_limit_exceeded" in reason


def test_early_wall_still_caught_by_prefix_scan():
    # No output before the wall: the existing fast path must still fire so the
    # current turn can be rerouted (we did not regress it).
    buf = _sse(_CREATED, _WALL)
    reason, output_started = cxp.scan_sse_prefix(buf)
    assert reason, "wall before any output must be caught by the prefix scan"
    assert output_started is False


def test_clean_stream_no_false_positive():
    buf = _sse(_CREATED, _OUTPUT, _OUTPUT, _OUTPUT)
    assert cxp.scan_sse_for_quota(buf) is None, "clean stream must not wall"


def test_is_quota_signal_codes():
    assert cxp.is_quota_signal(200, "usage_limit_reached", None, "")
    assert cxp.is_quota_signal(200, "rate_limit_exceeded", None, "")
    assert cxp.is_quota_signal(429, None, "You have hit your usage limit", "")
    assert not cxp.is_quota_signal(200, "invalid_request_error", "bad arg", "")


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception:
            failed += 1
            print("FAIL", t.__name__)
            traceback.print_exc()
    print("\n%d passed, %d failed" % (len(tests) - failed, failed))
    raise SystemExit(1 if failed else 0)
