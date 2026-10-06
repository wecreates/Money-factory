# Workflow Pro checkout QA — 2026-10-06

Public checkout page: https://cyzorcreations.com/pay/vertical-pro

Verified through the free cloud browser runner:
- page renders successfully;
- title is “Checkout — CYZOR Workflow Pro — CYZOR Creations”;
- $0 due today;
- first month free;
- then $29/month;
- copy explicitly says cancel before the first charge to avoid being charged;
- card required for verification;
- checkout identifies Helcim as the secure card processor;
- page states card details do not touch CYZOR servers;
- page says one key covers RenewGuard, GrantRadar, AuthBridge, CredFlow, FreightFill, ComplyWatch and HireSignal.

Production license endpoint was separately verified:
- invalid test key → HTTP 200 → {valid:false}.

Not yet tested:
- entering a real card;
- creation of a real trial/customer;
- valid:true license issuance;
- cancellation/expiry lifecycle.

Those actions would create real payment/account state and should not be simulated with fake payment data.
