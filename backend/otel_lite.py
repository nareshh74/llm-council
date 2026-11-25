"""Zero-dependency OTLP/HTTP JSON trace emitter (stdlib only, fail-open, never writes stdout)."""
import contextlib
import contextvars
import json
import logging
import os
import queue
import re
import secrets
import threading
import time
import urllib.request
from typing import Optional

SERVICE = os.environ.get("OTEL_SERVICE_NAME", "unknown")
_URL = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318").rstrip("/") + "/v1/traces"
_TP = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_REQ_LOG = logging.getLogger("llm_council.request")
_REQ_LOG.setLevel(logging.INFO)
_REQ_LOG.propagate = False
_h = logging.StreamHandler()  # stderr
_h.setFormatter(logging.Formatter("%(message)s"))
_REQ_LOG.addHandler(_h)
_ctx: contextvars.ContextVar = contextvars.ContextVar("otel_lite_ctx", default=None)
_q: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
_started = threading.Lock()
_worker: Optional[threading.Thread] = None


def init(service: str) -> None:
    global SERVICE
    SERVICE = service


def parse_traceparent(value: Optional[str]):
    m = _TP.match((value or "").strip().lower())
    if not m or m.group(1) == "0" * 32 or m.group(2) == "0" * 16:
        return None
    return m.group(1), m.group(2)


def current_trace_context() -> Optional[dict]:
    c = _ctx.get()
    return {"trace_id": c[0], "span_id": c[1]} if c else None


def get_traceparent() -> Optional[str]:
    c = _ctx.get()
    return f"00-{c[0]}-{c[1]}-01" if c else None


def _attr(k, v):
    if isinstance(v, bool):
        return {"key": k, "value": {"boolValue": v}}
    if isinstance(v, int):
        return {"key": k, "value": {"intValue": str(v)}}
    return {"key": k, "value": {"stringValue": str(v)}}


def _run() -> None:
    while True:
        batch = [_q.get()]
        with contextlib.suppress(queue.Empty):
            while len(batch) < 50:
                batch.append(_q.get_nowait())
        body = {"resourceSpans": [{
            "resource": {"attributes": [_attr("service.name", SERVICE), _attr("service.namespace", "local-ai")]},
            "scopeSpans": [{"scope": {"name": "otel_lite"}, "spans": batch}],
        }]}
        try:
            req = urllib.request.Request(_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=1.5).close()
        except Exception:  # fail-open: collector down/slow must never matter
            pass


def _emit(span: dict) -> None:
    global _worker
    try:
        with _started:
            if _worker is None:
                _worker = threading.Thread(target=_run, name="otel-lite", daemon=True)
                _worker.start()
        _q.put_nowait(span)
    except Exception:
        pass


@contextlib.contextmanager
def span(name: str, kind: int = 1, attrs: Optional[dict] = None, traceparent: Optional[str] = None):
    """kind: 1 internal, 2 server, 3 client. Yields a mutable attrs dict."""
    parsed, cur = parse_traceparent(traceparent), _ctx.get()
    trace, parent = parsed or (cur[:2] if cur else (secrets.token_hex(16), ""))
    sid = secrets.token_hex(8)
    token, rec, t0, failed = _ctx.set((trace, sid)), dict(attrs or {}), time.time_ns(), False
    try:
        yield rec
    except BaseException as e:
        failed = True
        rec["exception.type"] = type(e).__name__
        raise
    finally:
        _ctx.reset(token)
        failed = failed or int(rec.get("http.response.status_code", 0)) >= 400
        s = {"traceId": trace, "spanId": sid, "name": name, "kind": kind,
             "startTimeUnixNano": str(t0), "endTimeUnixNano": str(time.time_ns()),
             "attributes": [_attr(k, v) for k, v in rec.items()],
             "status": {"code": 2 if failed else 1}}
        if parent:
            s["parentSpanId"] = parent
        _emit(s)


class TraceMiddleware:
    """Pure ASGI middleware: continues inbound traceparent, emits a server span."""

    def __init__(self, app, service: Optional[str] = None):
        self.app = app
        if service:
            init(service)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        tp = dict(scope.get("headers") or []).get(b"traceparent", b"").decode("latin-1")
        method, path = scope.get("method", ""), scope.get("path", "")
        t0 = time.perf_counter()
        with span(f"{method} {path}", 2, {"http.request.method": method, "url.path": path}, tp) as rec:
            async def _send(msg):
                if msg["type"] == "http.response.start":
                    rec["http.response.status_code"] = msg["status"]
                await send(msg)
            try:
                await self.app(scope, receive, _send)
            finally:
                c = _ctx.get()
                _REQ_LOG.info(json.dumps({
                    "trace_id": c[0] if c else "", "span_id": c[1] if c else "",
                    "method": method, "path": path,
                    "status": rec.get("http.response.status_code", 0),
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1)}))


def install_log_correlation() -> None:
    """Append trace_id/span_id to log messages emitted inside a span."""
    old = logging.getLogRecordFactory()

    def factory(*a, **kw):
        r = old(*a, **kw)
        c = _ctx.get()
        r.trace_id, r.span_id = (c[0], c[1]) if c else ("", "")
        if c:
            r.msg, r.args = f"{r.getMessage()} trace_id={c[0]} span_id={c[1]}", None
        return r
    logging.setLogRecordFactory(factory)
