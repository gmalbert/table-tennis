# Odds snapshot request limits

`scripts/odds_sync.py` archives prices in batches of ten events. Each run
fetches at most 950 events and makes at most 100 HTTP attempts, including
event discovery, bookmaker discovery, and retries. Temporary network and
server failures use bounded retries with exponential backoff.

The local request cap is not a promise of available account quota: manual
runs and other clients can share the same API key. If a response supplies
`X-RateLimit-Remaining`, the script reduces its remaining budget accordingly.
On HTTP 429 or exhaustion of that budget, it stops requesting odds, emits a
warning in Actions, and archives the successfully fetched batches. If no
batches completed, no new snapshots are inserted. It does not retry 429 or
wait for the hourly reset; the next scheduled run attempts a fresh snapshot.
Coverage can therefore be partial when quota is low.

Quota deferral returns successfully so the Frontier workflow can publish the
audit store and continue its ranking steps. Authentication, malformed data,
and persistent server/network failures still fail visibly.

The Frontier workflow runs the regression suite before accessing the API:

```powershell
python -m unittest discover -s tests -p 'test_odds_sync.py' -v
```

Provider reference: [Odds-API.io best practices](https://docs.odds-api.io/guides/best-practices).
