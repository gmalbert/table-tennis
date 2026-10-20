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

    def test_provider_remaining_allowance_prevents_extra_request(self) -> None:
        result = response(200, [])
        result.headers["X-RateLimit-Remaining"] = "0"
        self.session.get.return_value = result
        budget = odds_sync.RequestBudget()
        self.fetch(budget)
        with self.assertRaises(odds_sync.QuotaReached):
            self.fetch(budget)
        self.session.get.assert_called_once()

    def test_provider_headers_cannot_increase_local_budget(self) -> None:
        for value in (None, "invalid", "1000", "2"):
            with self.subTest(value=value):
                result = response(200, [])
                if value is not None:
                    result.headers["X-RateLimit-Remaining"] = value
                budget = odds_sync.RequestBudget(remaining=3)
                self.session.get.return_value = result
                self.fetch(budget)
                self.assertEqual(budget.remaining, 2)

    def test_429_sets_shared_budget_to_zero_and_redacts_key(self) -> None:
        self.session.get.return_value = response(429, {"error": "quota secret-test-key"})
        budget = odds_sync.RequestBudget()
        with self.assertRaises(odds_sync.QuotaReached) as caught:
            self.fetch(budget)
        self.assertNotIn("secret-test-key", str(caught.exception))
        self.assertEqual(budget.remaining, 0)
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


class OddsQuotaSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        patch.dict(os.environ, {"ODDS_API_IO_KEY": "test-key", "ODDS_API_IO_BOOKMAKERS": "TestBook",
                               "GITHUB_ACTIONS": "true"}).start()
        self.session = patch.object(odds_sync.requests, "Session").start().return_value.__enter__.return_value
        self.archive = patch.object(odds_sync, "append_odds", return_value=2).start()
        self.output = patch("builtins.print").start()
        self.sleep = patch.object(odds_sync.time, "sleep").start()
        self.addCleanup(patch.stopall)
        self.events = [{"id": event_id} for event_id in range(30)]
        self.odds = [{"id": 1, "bookmakers": {"TestBook": [{"name": "ML", "odds": [{"home": 2, "away": 2}]}]}}]

    def assert_quota_warning(self) -> None:
        messages = [call.args[0] for call in self.output.call_args_list]
        self.assertTrue(any(message.startswith("::warning::") for message in messages))

    def test_mid_sync_429_archives_completed_batch_without_retry(self) -> None:
        self.session.get.side_effect = [response(200, self.events), response(200, self.odds),
                                        response(429, {"error": "Resets in 25 minutes"})]
        odds_sync.main()
        self.assertEqual(self.session.get.call_count, 3)
        self.archive.assert_called_once()
        self.assertEqual(len(self.archive.call_args.args[0]), 2)
        self.sleep.assert_not_called()
        self.assert_quota_warning()

    def test_initial_429_exits_cleanly(self) -> None:
        self.session.get.return_value = response(429, {"error": "Hourly quota exhausted"})
        odds_sync.main()
        self.session.get.assert_called_once()
        self.archive.assert_called_once_with([])
        self.assert_quota_warning()

    def test_bookmaker_lookup_429_exits_cleanly(self) -> None:
        with patch.dict(os.environ, {"ODDS_API_IO_BOOKMAKERS": ""}):
            self.session.get.side_effect = [response(200, self.events), response(429, {})]
            odds_sync.main()
        self.assertEqual(self.session.get.call_count, 2)
        self.archive.assert_called_once_with([])
        self.assert_quota_warning()

    def test_zero_remaining_header_archives_without_another_request(self) -> None:
        odds_response = response(200, self.odds)
        odds_response.headers["X-RateLimit-Remaining"] = "0"
        self.session.get.side_effect = [response(200, self.events), odds_response]
        odds_sync.main()
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(len(self.archive.call_args.args[0]), 2)
        self.assert_quota_warning()

    def test_retries_exhaust_local_budget_and_preserve_completed_batch(self) -> None:
        budget = odds_sync.RequestBudget(remaining=4)
        self.session.get.side_effect = [response(200, self.events), response(200, self.odds),
                                        response(503, {}), response(200, self.odds)]
        with patch.object(odds_sync, "RequestBudget", return_value=budget):
            odds_sync.main()
        self.assertEqual(self.session.get.call_count, 4)
        self.archive.assert_called_once()
        self.assertEqual(len(self.archive.call_args.args[0]), 4)
        self.assert_quota_warning()

    def test_authentication_errors_still_fail_the_job(self) -> None:
        self.session.get.return_value = response(401, {"error": "Invalid key"})
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            odds_sync.main()
        self.archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
