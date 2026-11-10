# Pinned market observation database identity regression

The bridge workflow pins the Content Control main revision from
[PR 1163](https://github.com/wecreates/content-control/pull/1163). Its existing
market-evidence suite exercises exact insert acknowledgements, replay scope,
and malformed timestamp evidence. The expanded storage writer step checks
expiry and storage cutoffs without opening the live database. The real SQL
rollback/retry regression runs against disposable PostgreSQL in Content Control.

This is a CI-only verification change. No live Money Factory authority host,
marketplace source, production database or publication path is exercised. Both
publication flags remain false. No live acceptance area is closed and this
scheduled run is not evidence of a continuously running worker.
