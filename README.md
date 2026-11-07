<h1 align="center">Product Card Assistant</h1>

<p align="center">Draft Russian-language B2B catalog cards for measuring instruments.</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square">
</p>

## Features

- Reads one UTF-8 product record from a JSON file or standard input.
- Uses OpenAI to rank source facts and search queries and select an editorial focus.
- Returns a Markdown or JSON draft with a title of up to 70 characters, a description
  of 800–1,200 characters, specifications, 3–5 search queries and a short manager brief.
- Lists missing fields and marks unavailable specification values with `данных нет`.

## Installation

Requires Python 3.11 or newer and an OpenAI API key. The CLI has no runtime Python dependencies
outside the standard library. From the repository root, on macOS or Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

## Usage

Set `OPENAI_API_KEY` in the shell environment using your secret manager or local shell setup.
Then run:

```sh
product-card examples/manometer.json
product-card examples/manometer.json --format json > card.json
product-card - < examples/demo-temperature-probe.json
```

Each command sends one request. Markdown is the default. JSON contains `seo_title`,
`seo_description`, `specifications`, `search_queries`, `commercial` and `missing_fields`.
Errors go to stderr. Exit status `2` indicates invalid input or missing configuration, and
`1` indicates an API or response error. API requests have a 30-second network timeout.

| Setting | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Required | API authentication |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Chat Completions model with Structured Outputs support |

The CLI reads environment variables directly. `.env.example` lists their names.

### Input contract

`name`, `manufacturer` and `description` accept strings or null. `specs` is a mapping
from names to strings or null. Use strings for numbers and their units, such as `"100 мм"`.
Missing keys, nulls and whitespace-only strings are reported as missing. The optional
`expected_specs` array lets the editor specify which additional parameters to check.
The maximum input size is 64 KiB. Unrecognized top-level fields are ignored.

### Sample drafts

| Product | Input | Markdown output |
| --- | --- | --- |
| DM 02 pressure gauge | [JSON](examples/manometer.json) | [Draft](examples/manometer.md) |
| DEMO-T temperature probe | [JSON](examples/demo-temperature-probe.json) | [Draft](examples/demo-temperature-probe.md) |

The pressure gauge uses the product record shown in the assignment. The two extra specification
names are a demonstration checklist. The supplied PDF contains one product record, so DEMO-T is
a synthetic fixture with a missing manufacturer and missing technical values. Both drafts were
rendered from fixed, hand-selected plans. A regression test reproduces them byte for byte.
Tests exercise the OpenAI request and response contract with a mocked HTTP transport.

## Prompt and rendering

1. Python validates and normalizes the source JSON and builds indexed candidates for the
   copy, search queries and exact excerpts. The supplied specifications are retained for
   the structured output.
2. The system prompt treats the product record as untrusted source material and asks
   the model to choose a focus, prioritize candidate facts and queries, and select a
   usable excerpt. The API uses a strict JSON schema. Python checks candidate bounds,
   uniqueness and list lengths before rendering.
3. Python composes the Russian prose from predefined paragraphs and selected source material.
   Technical values in the structured output come from the input, with surrounding
   whitespace trimmed. The renderer condenses whitespace for inline copy. A model response
   can change the emphasis and ordering through the plan. It cannot introduce free text
   or populate a missing specification.

The OpenAI request uses [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Limitations and next steps

- The constrained renderer trades stylistic variety for factual control. Category-specific
  copy and checklists would make the description more useful for common instrument families.
- The app reports absent fields against the source record and its checklist. It does not
  infer parameter requirements, resolve conflicting values, or extract specifications
  from a datasheet. Long prose is eligible for quoting only when it contains a suitable
  line of up to 250 characters. Evidence-linked extraction would extend that workflow.
- Query suggestions are based on the record. Their search volume is unmeasured.
- Source assertions are taken as supplied and need an editor's review. The local example
  checks do not measure the live model's plan quality.
- Provider errors stop the run. A production version could add bounded retries for transient
  failures and collect draft acceptance data.

## Development

```sh
python -m pip install -e '.[dev]'
ruff format --check
ruff check
pytest
```

See the [roadmap](ROADMAP.md) and [MIT license](LICENSE).
