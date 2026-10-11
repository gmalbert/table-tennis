from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

import requests

from scripts import odds_sync


def response(status: int, payload: object) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result._content_consumed = True
    return result


class OddsRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = Mock(spec=requests.Session)
        self.params = {"apiKey": "secret-test-key", "eventIds": "1"}
        self.sleep = patch.object(odds_sync.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def fetch(self, budget: odds_sync.RequestBudget | None = None) -> object:
        return odds_sync._get_json(
            self.session, odds_sync.DEFAULT_API_URL, "/odds/multi", self.params, budget
        )

    def test_temporary_server_errors_recover(self) -> None:
        for status in odds_sync.RETRYABLE_STATUS_CODES:
            with self.subTest(status=status):
                self.session.get.reset_mock()
                self.sleep.reset_mock()
                self.session.get.side_effect = [response(status, {"error": "busy"}), response(200, [])]
                budget = odds_sync.RequestBudget()
                self.assertEqual(self.fetch(budget), [])
                self.assertEqual(self.session.get.call_count, 2)
                self.assertEqual(budget.remaining, 98)
                self.sleep.assert_called_once_with(2)

    def test_persistent_outage_is_bounded_and_redacts_key(self) -> None:
        self.session.get.side_effect = [response(503, {"error": "busy secret-test-key"}) for _ in range(4)]
        with self.assertRaises(RuntimeError) as caught:
            self.fetch()
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertNotIn("secret-test-key", str(caught.exception))
        self.assertEqual(self.session.get.call_count, 4)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [2, 4, 8])

    def test_authentication_and_quota_errors_are_not_retried(self) -> None:
        for status in (400, 401, 403, 404, 429):
            with self.subTest(status=status):
                self.session.get.reset_mock()
                self.session.get.return_value = response(status, {"error": "denied"})
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                    self.fetch()
                self.session.get.assert_called_once()
        self.sleep.assert_not_called()

    def test_network_errors_recover(self) -> None:
        self.session.get.side_effect = [requests.Timeout("secret-test-key"), requests.ConnectionError(), response(200, [])]
        self.assertEqual(self.fetch(), [])
        self.assertEqual(self.session.get.call_count, 3)

    def test_persistent_network_error_does_not_expose_url(self) -> None:
        self.session.get.side_effect = requests.ConnectionError("https://example.com?apiKey=secret-test-key")
        with self.assertRaises(RuntimeError) as caught:
            self.fetch()
        self.assertNotIn("secret-test-key", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(self.session.get.call_count, 4)

    def test_invalid_json_fails_without_retry(self) -> None:
        bad_response = response(200, [])
        bad_response._content = b"invalid JSON"
        self.session.get.return_value = bad_response
        with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
            self.fetch()
        self.session.get.assert_called_once()
        self.sleep.assert_not_called()

    def test_budget_is_shared_across_requests_and_retries(self) -> None:
        self.session.get.side_effect = [response(503, {}), response(200, []), response(200, [])]
        budget = odds_sync.RequestBudget(remaining=3)
        self.fetch(budget)
        self.fetch(budget)
        with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            self.fetch(budget)
        self.assertEqual(self.session.get.call_count, 3)
        self.assertEqual(budget.remaining, 0)

    def test_no_retry_when_budget_is_spent(self) -> None:
        self.session.get.return_value = response(503, {})
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            self.fetch(odds_sync.RequestBudget(remaining=1))
        self.session.get.assert_called_once()
        self.sleep.assert_not_called()


class OddsSyncTests(unittest.TestCase):
    @patch.dict(os.environ, {"ODDS_API_IO_KEY": "test-key", "ODDS_API_IO_BOOKMAKERS": ""})
    @patch.object(odds_sync, "append_odds", return_value=2)
    @patch.object(odds_sync.time, "sleep")
    @patch.object(odds_sync.requests, "Session")
    def test_full_sync_archives_after_503_and_respects_request_cap(self, session_factory, sleep, append_odds) -> None:
        session = session_factory.return_value.__enter__.return_value
        events = [{"id": event_id} for event_id in range(odds_sync.EVENTS_PER_RUN + 10)]
        odds = [{"id": 1, "bookmakers": {"TestBook": [{"name": "ML", "odds": [{"home": 2, "away": 2}]}]}}]
        # 2 setup calls + 3 transient errors + 95 successful batches = 100.
        session.get.side_effect = (
            [response(200, events), response(200, ["TestBook"])]
            + [response(503, {"error": "Server busy, retry shortly"}) for _ in range(3)]
            + [response(200, odds)]
            + [response(200, []) for _ in range(94)]
        )
        odds_sync.main()
        self.assertEqual(session.get.call_count, odds_sync.MAX_REQUESTS_PER_RUN)
        append_odds.assert_called_once()
        self.assertEqual(len(append_odds.call_args.args[0]), 2)
        last_batch = session.get.call_args.kwargs["params"]["eventIds"].split(",")
        self.assertEqual(last_batch[-1], str(odds_sync.EVENTS_PER_RUN - 1))


if __name__ == "__main__":
    unittest.main()
