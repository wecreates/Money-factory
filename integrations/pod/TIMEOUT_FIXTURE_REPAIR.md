# Pool timeout regression reliability repair

The R499 run observed an intermittent `resolve is not a function` in the HTTP
pool-timeout test. Its 300 ms fallback started before the request reached the
mock pool. Under scheduling delay it called an unset resolver, or released the
client before the connection timeout and invalidated the intended scenario.

The test now waits for an explicit acquisition-start signal, observes the HTTP
503, and only then releases the late client. Both immediate dispatch and a
350 ms delayed dispatch verify the same redacted response, zero transaction
queries, and exactly one client release. A bounded test deadline detects a
stalled handler; no fallback alters the behavior under test. Runtime code,
production configuration, credentials, and publication flags are unchanged.

Verification: focused suite 12/12; Python bridge 81/81. Full Node bridge and
exact-head hosted workflow results are recorded in the associated pull request.
An initial local full Node invocation omitted CONTENT_CONTROL_ROOT and failed
the cross-repository tests with CONTENT_CONTROL_ROOT_REQUIRED; this is a runner
configuration error, not a product failure, and is not counted as a passing run.

This repair does not close any of the 24 live acceptance areas. Database quota,
live authority/account/rights evidence, authorized adapters, independent QA,
mobile acceptance, and actual end-to-end launch evidence remain required.
PUBLICATION_ENABLED and POD_PUBLICATION_ENABLED remain false.
