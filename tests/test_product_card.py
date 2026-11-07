import io
import itertools
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from product_card.card import FOCUSES, Candidates, Plan, PlanError, render_card
from product_card.cli import main
from product_card.openai import DEFAULT_MODEL, ENDPOINT, APIError, choose_plan
from product_card.product import NO_DATA, InputError, Product

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_PLANS = {
    "manometer": Plan("selection", [0, 1, 2, 3], [0, 2, 4, 6], 0),
    "demo-temperature-probe": Plan("procurement", [], [1, 0, 2], 0),
}


def _response(plan: dict[str, object], finish_reason: str = "stop") -> io.BytesIO:
    return io.BytesIO(
        json.dumps(
            {
                "choices": [
                    {"message": {"content": json.dumps(plan)}, "finish_reason": finish_reason}
                ]
            }
        ).encode()
    )


class ProductTests(unittest.TestCase):
    def test_missing_fields_and_trimmed_values(self) -> None:
        product = Product.from_json(
            '{"name":" ", "specs":{"range":" 0–1,6 МПа ", "body":""},'
            ' "expected_specs":["range","signal","body"]}'
        )
        self.assertEqual(product.specs, {"range": "0–1,6 МПа", "body": None, "signal": None})
        self.assertEqual(
            product.missing_fields(),
            ["name", "manufacturer", "description", "specs.body", "specs.signal"],
        )

    def test_invalid_json_and_shapes(self) -> None:
        for raw in (
            "{",
            "[]",
            '{"name": 42}',
            '{"name": "\\ud800"}',
            '{"specs":[]}',
            '{"specs":{"range":NaN}}',
            '{"specs":{"range":1.6}}',
            '{"specs":{"range":"1"," range":"2"}}',
            '{"name":null,"name":null}',
            '{"expected_specs":"range"}',
            '{"expected_specs":[" "]}',
        ):
            with self.subTest(raw=raw), self.assertRaises(InputError):
                Product.from_json(raw)


class CardTests(unittest.TestCase):
    def test_description_and_title_limits_for_every_focus(self) -> None:
        products = [
            Product.from_json("{}"),
            Product("A", None, {}, None),
            Product("A", "B", {"x": "p"}, "D"),
            Product("А" * 300, "Б" * 300, {"x": "ж" * 146}, "С" * 250),
            Product("Модель " * 17, "Завод", {"x": "p", "y": "q"}, "Пример назначения."),
        ]
        for product, focus in itertools.product(products, FOCUSES):
            with self.subTest(product=product.name, focus=focus):
                candidates = Candidates.from_product(product)
                plan = Plan(
                    focus,
                    list(range(len(candidates.facts))),
                    [0, 1, 2],
                    0 if candidates.excerpts else None,
                )
                card = render_card(product, candidates, plan)
                self.assertLessEqual(len(card.seo_title), 70)
                self.assertTrue(800 <= len(card.seo_description) <= 1200)
                self.assertEqual(len(set(card.search_queries)), 3)

    def test_invalid_model_choices(self) -> None:
        candidates = Candidates(["one"], ["a", "b", "c"], ["source"])
        valid = asdict(Plan("selection", [0], [0, 1, 2], None))
        for override in (
            {"prose": "unsupported 16 bar"},
            {"focus": "free text"},
            {"fact_ids": [1]},
            {"fact_ids": [False]},
            {"query_ids": [0, 0, 1]},
            {"query_ids": [0, 1]},
            {"excerpt_id": -1},
        ):
            with self.subTest(override=override), self.assertRaises(PlanError):
                Plan.from_data(valid | override, candidates)

    def test_missing_values_and_literal_markdown(self) -> None:
        product = Product("Sensor", None, {"range": None, "note": "<img> [text](url)"}, None)
        candidates = Candidates.from_product(product)
        card = render_card(product, candidates, Plan("selection", [], [0, 1, 2], None))
        self.assertEqual(card.specifications["range"], NO_DATA)
        self.assertIn("specs.range", card.missing_fields)
        self.assertNotIn("<img>", card.to_markdown())
        self.assertEqual(card.specifications["note"], "<img> [text](url)")

    def test_sample_cards_match_the_renderer(self) -> None:
        for slug, plan in EXAMPLE_PLANS.items():
            with self.subTest(slug=slug):
                product = Product.from_json((EXAMPLES / f"{slug}.json").read_text(encoding="utf-8"))
                candidates = Candidates.from_product(product)
                validated = Plan.from_data(asdict(plan), candidates)
                card = render_card(product, candidates, validated)
                self.assertTrue(800 <= len(card.seo_description) <= 1200)
                self.assertEqual(
                    (EXAMPLES / f"{slug}.md").read_text(encoding="utf-8"),
                    card.to_markdown() + "\n",
                )


class APITests(unittest.TestCase):
    def setUp(self) -> None:
        self.product = Product("Instrument", None, {}, "Source text")
        self.candidates = Candidates.from_product(self.product)
        self.plan = Plan("selection", [], [0, 1, 2], None)

    def test_request_and_response_contract(self) -> None:
        with patch("product_card.openai.urlopen", return_value=_response(asdict(self.plan))) as api:
            self.assertEqual(
                choose_plan(self.product, self.candidates, "test-key", DEFAULT_MODEL), self.plan
            )
        request = api.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(
            json.loads(body["messages"][1]["content"])["product"], asdict(self.product)
        )

    def test_malformed_refused_and_invalid_plans(self) -> None:
        responses = [
            (io.BytesIO(b'{"choices": []}'), "malformed"),
            (_response(asdict(self.plan), "length"), "complete"),
            (_response(asdict(self.plan) | {"excerpt_id": 9}), "invalid editorial plan"),
            (
                io.BytesIO(b'{"choices":[{"message":{"refusal":"declined"}}]}'),
                "declined",
            ),
        ]
        for response, message in responses:
            with (
                self.subTest(message=message),
                patch("product_card.openai.urlopen", return_value=response),
                self.assertRaisesRegex(APIError, message),
            ):
                choose_plan(self.product, self.candidates, "test-key", DEFAULT_MODEL)

    def test_http_and_network_failures_do_not_echo_response(self) -> None:
        for error, message in (
            (HTTPError(ENDPOINT, 401, "secret", {}, None), "rejected access"),
            (HTTPError(ENDPOINT, 429, "secret", {}, None), "quota"),
            (HTTPError(ENDPOINT, 503, "secret", {}, None), "temporarily"),
            (URLError("secret"), "connection"),
            (TimeoutError("secret"), "connection"),
        ):
            with (
                self.subTest(message=message),
                patch("product_card.openai.urlopen", side_effect=error),
                self.assertRaisesRegex(APIError, message) as raised,
            ):
                choose_plan(self.product, self.candidates, "test-key", DEFAULT_MODEL)
            self.assertNotIn("secret", str(raised.exception))


class CLITests(unittest.TestCase):
    def test_cli_reads_file_and_emits_json(self) -> None:
        stdout = io.StringIO()
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "product_card.openai.urlopen",
                return_value=_response(asdict(EXAMPLE_PLANS["manometer"])),
            ),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(main([str(EXAMPLES / "manometer.json"), "--format", "json"]), 0)
        card = json.loads(stdout.getvalue())
        self.assertEqual(card["specifications"]["присоединение"], "G1/2")
        self.assertEqual(card["specifications"]["рабочая среда"], NO_DATA)

    def test_cli_reads_stdin_and_emits_markdown(self) -> None:
        slug = "demo-temperature-probe"
        stdin = io.TextIOWrapper(io.BytesIO((EXAMPLES / f"{slug}.json").read_bytes()))
        stdout = io.StringIO()
        with (
            stdin,
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "product_card.openai.urlopen",
                return_value=_response(asdict(EXAMPLE_PLANS[slug])),
            ),
            patch("sys.stdin", stdin),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(main(["-"]), 0)
        self.assertEqual(stdout.getvalue(), (EXAMPLES / f"{slug}.md").read_text(encoding="utf-8"))

    def test_cli_rejects_bad_input_before_calling_api(self) -> None:
        stderr = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("product_card.cli.choose_plan") as api,
            patch("sys.stderr", stderr),
        ):
            path = Path(directory) / "broken.json"
            path.write_text("{", encoding="utf-8")
            self.assertEqual(main([str(path)]), 2)
        self.assertIn("Invalid JSON", stderr.getvalue())
        api.assert_not_called()

    def test_cli_requires_key_and_keeps_stdout_empty_on_api_failure(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        args = [str(EXAMPLES / "demo-temperature-probe.json")]
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
            patch("sys.stderr", stderr),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(main(args), 2)
        self.assertIn("set OPENAI_API_KEY", stderr.getvalue())
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch("product_card.cli.choose_plan", side_effect=APIError("connection")),
            patch("sys.stderr", stderr),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(main(args), 1)
        self.assertIn("API error: connection", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
