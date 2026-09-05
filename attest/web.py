"""Local server: static UI plus the JSON API.

Stdlib only. No framework, no build step, no dependency the engine does not
already have — `python -m attest.web` and the product opens.

Everything is served from 127.0.0.1 and nothing leaves the machine, which is the
correct default for a tool that reads a merchant's books.
"""

from __future__ import annotations

import json
import os
import threading
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from attest import api
from attest.policy import Costs

#: Local default. A hosted deployment overrides both from the environment —
#: PaaS platforms assign the port and require binding every interface, and
#: 127.0.0.1 inside a container is reachable by nothing.
PORT = int(os.environ.get("PORT", "8420"))
HOST = os.environ.get("HOST", "127.0.0.1")

#: Opening a browser is right on a laptop and wrong on a server, where there is
#: no display and the process must not block on one.
OPEN_BROWSER = os.environ.get("ATTEST_OPEN_BROWSER", "1") != "0"

#: The seed the live demo runs on. 555001 is one of the two EVALUATION seeds in
#: benchmark/results.json — held out from the three the policy was calibrated on.
#:
#: It used to be 20260821, a calibration seed, and that was wrong for a reason
#: FAILURES.md D7 already wrote down: "Published 'precision 1.000' for six days.
#: It was one seed." The demo was reporting exactly the pair of numbers that
#: entry retracts. A product whose claim is that it will not assert what it
#: cannot prove does not get to demonstrate itself on the data it was tuned on.
#: The headline is worse on this seed. That is the point of holding it out.
DEMO_SEED = 555001

#: The review cost every screen defaults to, read from the policy rather
#: than typed. Seven call sites carried the literal 15000 after the policy
#: moved to 25000, so the workspace said 17 settlements post while the front
#: door and the journal said nothing did — two screens disagreeing about one
#: portfolio, which is the failure journal_view's own docstring warns about.
DEFAULT_REVIEW = Costs().review_paise
UI = Path(__file__).resolve().parent / "ui"


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive on a single-threaded server deadlocks: the browser
    # holds the connection open and every subsequent request queues behind it.
    # Threading is not an optimisation here, it is what makes the page load.
    protocol_version = "HTTP/1.1"

    def log_message(self, *a: object) -> None:
        pass

    def _reply(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, code: int = 200) -> None:
        self._reply(json.dumps(payload).encode(), "application/json", code)

    def do_POST(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/events/demo":
            self._json(api.demonstrate_events(api.get(q.get("run", [""])[0])))
            return
        if u.path != "/api/events":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        sig = self.headers.get("X-Razorpay-Signature", "")
        try:
            self._json(api.receive_event(
                api.get(q.get("run", [""])[0]), body, sig))
        except Exception as exc:  # a malformed body is the client's problem
            self._json({"error": str(exc)}, 400)

    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/api/run":
            n = max(10, min(5000, int(q.get("n", ["250"])[0])))
            self._json(api.summary(_run(n)))

        elif u.path == "/api/attention":
            r = api.get(q.get("run", [""])[0])
            self._json(api.attention(r) if r else {"error": "unknown run"},
                       200 if r else 404)

        elif u.path == "/api/claims":
            self._json(api.trust_claims(api.get(q.get("run", [""])[0])))

        elif u.path == "/api/activity":
            self._json(api.activity_view(api.get(q.get("run", [""])[0]),
                                         q.get("type", ["portfolio"])[0],
                                         q.get("id", [""])[0]))

        elif u.path == "/api/replay":
            self._json(api.replay_view(api.get(q.get("run", [""])[0])))

        elif u.path == "/api/decision":
            self._json(api.decision_view(
                api.get(q.get("run", [""])[0]),
                q.get("type", ["portfolio"])[0], q.get("id", [""])[0],
                int(q.get("review", [str(DEFAULT_REVIEW)])[0]),
                int(q.get("exposure", ["10000000"])[0])))

        elif u.path == "/api/loop":
            r = api.get(q.get("run", [""])[0])
            self._json(api.control_loop(
                r, q.get("id", [""])[0],
                int(q.get("review", [str(DEFAULT_REVIEW)])[0]),
                int(q.get("exposure", ["10000000"])[0]),
            ) if r else {"error": "unknown run"}, 200 if r else 404)

        elif u.path == "/api/investigation":
            self._json(api.investigation_view(api.get(q.get("run", [""])[0]),
                                              q.get("type", ["portfolio"])[0],
                                              q.get("id", [""])[0]))

        elif u.path == "/api/evidence":
            self._json(api.evidence_view(api.get(q.get("run", [""])[0]),
                                         q.get("type", ["portfolio"])[0],
                                         q.get("id", [""])[0]))

        elif u.path == "/api/subject":
            self._json(api.subject_view(api.get(q.get("run", [""])[0]),
                                        q.get("type", ["portfolio"])[0],
                                        q.get("id", [""])[0]))

        elif u.path == "/api/spine":
            self._json(api.spine_view(api.get(q.get("run", [""])[0]),
                                      q.get("type", ["portfolio"])[0],
                                      q.get("id", [""])[0],
                                      int(q.get("review", [str(DEFAULT_REVIEW)])[0]),
                                      int(q.get("exposure", ["10000000"])[0])))

        elif u.path == "/api/actions":
            r = api.get(q.get("run", [""])[0])
            self._json(api.actions_view(r) if r
                       else {"error": "unknown run"}, 200 if r else 404)

        elif u.path == "/api/journal":
            r = api.get(q.get("run", [""])[0])
            self._json(api.journal_view(
                r,
                int(q.get("review", [str(DEFAULT_REVIEW)])[0]),
                int(q.get("exposure", ["10000000"])[0]),
            ) if r else {"error": "unknown run"}, 200 if r else 404)

        # §38.P0-3. A read, on GET, with no side effect. The queue leaves as
        # a file so the refusal has somewhere to go; nothing about the run
        # changes because it was asked for.
        # §43. Prepared, never sent. A GET with no side effect: the packet is
        # assembled from a run that already happened.
        elif u.path == "/api/evidence-request":
            r = api.get(q.get("run", [""])[0])
            sid = q.get("id", [""])[0]
            if r is None:
                self._json({"error": "unknown run"}, 404)
            elif q.get("format", ["json"])[0] == "text":
                body = api.evidence_request_text(r, sid).encode()
                if not body:
                    self._json({"error": "nothing to request"}, 404)
                else:
                    self._reply(body, "text/plain; charset=utf-8")
            else:
                d = api.evidence_request(r, sid)
                self._json(d or {"error": "nothing to request"}, 200 if d else 404)

        elif u.path == "/api/export/queue":
            r = api.get(q.get("run", [""])[0])
            if r is None:
                self._json({"error": "unknown run"}, 404)
            elif q.get("format", ["json"])[0] == "csv":
                body = api.export_queue_csv(r).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="attest-queue-{r.run_id}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(api.export_queue(r))

        elif u.path == "/api/observatory":
            self._json(api.observatory())

        elif u.path == "/api/events":
            self._json(api.event_feed())

        elif u.path == "/api/settlement":
            r = api.get(q.get("run", [""])[0])
            d = api.detail(r, q.get("id", [""])[0]) if r else None
            self._json(d or {"error": "not found"}, 200 if d else 404)

        else:
            # THE FRONT DOOR IS THE INVESTIGATION.
            #
            # `/` is the long-form narrative; `/app` is the instrument
            # workspace. The workspace keeps its own filename as a route
            # because that is what a person lands on when they open the
            # application directly — and because the browser contracts address
            # it there, so moving the front door cannot silently move what
            # 150 of them are testing.
            if u.path in ("/", "", "/story", "/story/"):
                name = "investigation.html"
            elif u.path in ("/app", "/app/"):
                name = "workspace.html"
            else:
                name = "workspace.html" if u.path == "/index.html" else u.path.lstrip("/")
            path = (UI / name).resolve()
            if UI not in path.parents or not path.is_file():
                self._reply(b"not found", "text/plain", 404)
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self._reply(path.read_bytes(), f"{ctype}; charset=utf-8")


#: Runs already computed, by portfolio size. `execute` is a pure function of
#: (n, seed) and the seed is fixed, so the second caller can have the first
#: caller's answer.
#:
#: This is a serving concern, not an engine one. Locally the engine takes ~2s
#: and nobody noticed; on a shared-CPU container it takes ~23s, and the landing
#: page opens by calling this endpoint — so every visitor was re-deriving an
#: identical result while looking at nothing. The first visitor still pays.
_MEMO: dict[int, object] = {}

#: One lock, not one per size. Two threads computing DIFFERENT portfolios at
#: once is just as bad as two computing the same one: the container has a single
#: shared core, so concurrent runs do not overlap, they interleave, and both
#: callers wait for the sum of the work instead of the larger half. Serialising
#: is what makes the startup warm-up worth anything — a request that arrives
#: mid-warm now waits for that answer rather than starting a second copy of it.
_LOCK = threading.Lock()


def _run(n: int):
    with _LOCK:
        if n not in _MEMO:
            _MEMO[n] = api.execute(n, DEMO_SEED)
        return _MEMO[n]


#: The batch sizes the control room offers. Every one is warmed at startup, so
#: the choice is genuinely free at the point of use.
#:
#: The dropdown used to offer 120/250/500 while `/api/run` accepted 10 to 5000,
#: which hid the most interesting thing the engine does. Coverage is not a
#: constant: 60 settlements over the same 90-day window resolve 51.7% of the
#: time, 500 resolve 8.0%, because a denser portfolio puts more disjoint subsets
#: inside tolerance and the engine reports them as ambiguous rather than
#: guessing. Being able to move that dial and watch it happen is the difference
#: between reading the limitation in a document and discovering it.
#:
#: 1000 is not offered. It takes ~23s locally and nearly four minutes on a
#: shared core, and an option that appears to hang is worse than an option that
#: is absent. The shape is already unmistakable across 60 to 500.
SIZES: tuple[int, ...] = (60, 120, 250, 500)


def _warm() -> None:
    """Compute every offered run before anyone asks for one.

    The memo turns the second request into a lookup, but somebody still has to
    be the first — and on a shared-CPU container that is ~45 seconds of blank
    page. Doing it at startup, off the serving thread, means the socket accepts
    immediately and the answers are usually already there by the time a person
    arrives.

    Warmed largest-first: 500 is the one worth waiting for, and a visitor who
    arrives mid-warm is far more likely to want the default than the extreme.
    """
    for n in sorted(SIZES, reverse=True):
        try:
            _run(n)
            print(f"warm: n={n}", flush=True)
        except Exception as e:              # a warm-up must never stop serving
            print(f"warm-up skipped n={n}: {e!r}", flush=True)


def main() -> None:
    url = f"http://{'127.0.0.1' if HOST in ('127.0.0.1', '') else HOST}:{PORT}/"
    print(f"ATTEST → {url}", flush=True)
    if OPEN_BROWSER:
        webbrowser.open(url)
    threading.Thread(target=_warm, name="warm", daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
