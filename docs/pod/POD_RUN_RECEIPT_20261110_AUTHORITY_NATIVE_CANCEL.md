# Native authority cancellation — November 10, 2026

Three regressions failed against the exact current authority-handler source.
A snapshot loader could replace signal.throwIfAborted and receive a signed grant
after the monotonic lookup deadline. Signal getters could break cleanup, and a
synthetic abort event prematurely rejected lookup without native cancellation.

The authority now captures native AbortSignal checks and EventTarget listener
methods. Deadline/disconnect checks and cleanup do not invoke loader-shadowed
members. Synthetic events are ignored without consuming the real cancellation
listener. A current snapshot still receives only its existing scoped permission;
fixtures retain publication_permission false. Unsettled loaders still occupy
the original bounded admission capacity; cancellation does not prove I/O stops.

Focused tests cover deadline refusal before issuance clock, safe cleanup,
synthetic-event handling, real timeout and ordinary current snapshot admission.
Exact CI, merge and unchanged Content Control deployment evidence is recorded on
the PR. No new Content Control runtime revision or extra Render deploy is needed.

All 24 live acceptance areas remain OPEN. The real MF core/authoritative snapshot
loader and authenticated inbox are not mounted by these module tests. No live
grant, approval, database, marketplace, rights, revenue, capacity or continuous
worker acceptance is fabricated. No publication/service activation, credentials,
network expansion or paid resource change; unchanged DB admin was not retried.
