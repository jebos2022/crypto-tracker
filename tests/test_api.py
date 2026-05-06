import importlib
import os
import unittest
from unittest.mock import patch

from core import api
from core import api_public_evidence


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


def _rate_limit_response() -> FakeResponse:
    return FakeResponse({
        "status": "0",
        "message": "NOTOK",
        "result": "Max rate limit reached",
    })


def _ok_list_response() -> FakeResponse:
    return FakeResponse({
        "status": "1",
        "message": "OK",
        "result": [{"blockNumber": "1"}],
    })


def _ok_single_response(value: str = "42") -> FakeResponse:
    return FakeResponse({
        "status": "1",
        "message": "OK",
        "result": value,
    })


class ApiEnvLoadingTests(unittest.TestCase):
    def test_import_does_not_load_env(self) -> None:
        with patch("core.env.load_env") as load_mock:
            importlib.reload(api)
            load_mock.assert_not_called()
        importlib.reload(api)

    def test_api_params_loads_env_lazily_on_call(self) -> None:
        original_key = os.environ.get("ETHERSCAN_API_KEY")
        os.environ["ETHERSCAN_API_KEY"] = "test-key"
        try:
            with patch.object(api, "load_env") as load_mock:
                params = api._api_params("ethereum")
        finally:
            if original_key is None:
                os.environ.pop("ETHERSCAN_API_KEY", None)
            else:
                os.environ["ETHERSCAN_API_KEY"] = original_key

        load_mock.assert_called_once()
        self.assertEqual(params["apikey"], "test-key")

    def test_api_params_raises_when_etherscan_key_is_missing(self) -> None:
        original_key = os.environ.get("ETHERSCAN_API_KEY")
        os.environ.pop("ETHERSCAN_API_KEY", None)
        try:
            with (
                patch.object(api, "load_env", lambda: None),
                self.assertRaisesRegex(ValueError, "ETHERSCAN_API_KEY"),
            ):
                api._api_params("ethereum")
        finally:
            if original_key is not None:
                os.environ["ETHERSCAN_API_KEY"] = original_key

    def test_public_evidence_env_loads_lazily_on_call(self) -> None:
        original_key = os.environ.get("COINMARKETCAP_API_KEY")
        os.environ.pop("COINMARKETCAP_API_KEY", None)
        try:
            with patch.object(api_public_evidence, "load_env") as load_mock:
                self.assertIsNone(
                    api_public_evidence.fetch_coinmarketcap_token_info("0x" + "1" * 40)
                )
        finally:
            if original_key is not None:
                os.environ["COINMARKETCAP_API_KEY"] = original_key

        load_mock.assert_called_once()


class ApiRetryTests(unittest.TestCase):
    def test_paginated_request_retries_rate_limit_then_returns_batch(self) -> None:
        client = FakeClient([_rate_limit_response(), _ok_list_response()])
        sleeps = []

        with patch.object(api.time, "sleep", lambda seconds: sleeps.append(seconds)):
            kind, batch = api._request_with_retry(client, "https://example.test", {"a": "b"})

        self.assertEqual(kind, "ok")
        self.assertEqual(batch, [{"blockNumber": "1"}])
        self.assertEqual(sleeps, [api.INITIAL_BACKOFF])
        self.assertEqual(len(client.calls), 2)

    def test_single_call_retries_rate_limit_then_returns_result(self) -> None:
        client = FakeClient([_rate_limit_response(), _ok_single_response("123")])
        sleeps = []

        with (
            patch.object(api.httpx, "Client", return_value=client),
            patch.object(api.time, "sleep", lambda seconds: sleeps.append(seconds)),
        ):
            result = api._single_call("https://example.test", {"a": "b"})

        self.assertEqual(result, "123")
        self.assertEqual(sleeps, [api.INITIAL_BACKOFF])
        self.assertEqual(len(client.calls), 2)


class ApiSingleBalanceParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_single_call = api._single_call
        self.original_api_params = api._api_params
        api._api_params = lambda _chain: {}

    def tearDown(self) -> None:
        api._single_call = self.original_single_call
        api._api_params = self.original_api_params

    def test_native_balance_returns_int_for_numeric_result(self) -> None:
        api._single_call = lambda _url, _params: "123"

        self.assertEqual(api.fetch_native_balance("0x" + "1" * 40, "ethereum"), 123)

    def test_native_balance_wraps_non_numeric_result_in_etherscan_error(self) -> None:
        api._single_call = lambda _url, _params: "not-a-number"

        with self.assertRaisesRegex(api.EtherscanError, "non-numeric balance result"):
            api.fetch_native_balance("0x" + "1" * 40, "ethereum")

    def test_token_balance_wraps_non_numeric_result_in_etherscan_error(self) -> None:
        api._single_call = lambda _url, _params: ""

        with self.assertRaisesRegex(api.EtherscanError, "non-numeric tokenbalance result"):
            api.fetch_token_balance("0x" + "1" * 40, "0x" + "2" * 40, "ethereum")

    def test_token_supply_wraps_non_numeric_result_in_etherscan_error(self) -> None:
        api._single_call = lambda _url, _params: None

        with self.assertRaisesRegex(api.EtherscanError, "non-numeric tokensupply result"):
            api.fetch_token_supply("0x" + "2" * 40, "ethereum")


if __name__ == "__main__":
    unittest.main()
