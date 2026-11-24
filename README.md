# Jobo for Dify

Tool plugin for the [Jobo](https://jobo.world) jobs API: live job listings collected from employer career sites and applicant tracking systems (ATS), and the hiring signals Jobo detects in them, as tools for Dify Chatflow, Workflow and Agent apps.

- Source repository: <https://github.com/JoboAI/jobo-dify>
- Homepage: <https://jobo.world>
- API documentation: <https://jobo.world/docs>
- Support: support@jobo.world
- Privacy policy: [PRIVACY.md](PRIVACY.md) and <https://jobo.world/privacy>

## Tools

| Tool | What it does | Jobo endpoint | Billed |
| --- | --- | --- | --- |
| Search jobs | Live job listings matching a query and filters | `POST /api/jobs/search` | Per job returned |
| Get job | One listing by Jobo job ID, with the full posting | `GET /api/jobs/{id}` | Free |
| Find companies | Company name or domain to Jobo company IDs | `GET /api/connectors/companies/suggest` | Free |
| Find filter values | The values a search filter accepts (ATS sources, industries, skills, company categories, job categories, job subcategories, occupations), with live job counts | `GET /api/connectors/filter-options/{facet}`, `GET /api/occupations` | Free |
| Find locations | A place name to the locations Search jobs takes | `GET /api/connectors/locations/suggest` | Free |
| List hiring signals | Events at companies detected from their job postings: a hiring surge, a first job in a country, a leadership search, a new technology, a slowdown | `GET /api/signals`, `GET /api/companies/{id}/signals` | Per signal returned, at ten times the price of a job |

Find locations uses the free connector typeahead. It does not call the metered `GET /api/locations/geocode` endpoint.

## Setup

1. Create a Jobo API key at <https://enterprise.jobo.world/api-keys>. New accounts get a free starting balance when they verify their email address, and a sandbox key (`jbe_test_...`) is free (see Limits).
2. In Dify, open **Plugins**, install **Jobo** from the Marketplace, then open the plugin and choose **To Authorize**.
3. Paste the API key into **Jobo API key** and save. The plugin checks the key against `GET /api/connectors/filters`, which is free and answers 401 without a valid key. Only a 401 or 403 rejects the key. If Jobo is unavailable, rate limited or unreachable at that moment, the key is saved without the check, and a tool call reports any problem later.
4. Add the tools to an Agent app, or drop a tool node into a Workflow or Chatflow.

## Usage

In an Agent app, enable the tools and ask, for example, "Find three remote senior Python jobs paying over 150k USD". The agent can look up the company, filter and place values with the free tools first, then call Search jobs once.

In a Workflow, Search jobs outputs `text` (readable results) and `json` with `summary` (total matches, page, and the credits the API reported for the call) and `jobs` (one object per job with `id`, `title`, `company`, `location`, `salary`, `url` and more, when the posting states them).

Search jobs takes lists as one string, because Dify tool parameters are plain values:

- Comma-separated: `work_model`, `employment_type`, `experience_level`, `skills`, `exclude_skills`, `occupation_ids`, `exclude_occupation_ids`, `sources`, `language`, `company_categories`, `exclude_company_categories`.
- Semicolon-separated (names can contain commas): `location`, `companies`, `exclude_companies`, `industries`, `exclude_industries`, `job_categories`, `exclude_job_categories`, `job_subcategories`, `exclude_job_subcategories`.
- `work_model` is `remote`, `hybrid` or `onsite`. `employment_type` is `full-time`, `part-time`, `contract`, `internship`, `freelance` or `temporary`. `experience_level` is `intern`, `entry`, `mid`, `senior`, `lead` or `executive`. An unknown value is rejected before any request, because the API would answer it with zero results rather than an error.
- Open-value filters (`sources`, `skills`, `industries`, `job_categories`, `job_subcategories`, `occupation_ids`, `companies`) match only values the index holds. Look them up with the free tools first.
- `discovered_after` and `discovered_before` bound when Jobo first indexed a job; `posted_after` and `posted_before` bound when the employer posted it. `search_description` set to false matches the query against job titles only.

Search jobs has every search filter of the shared connector contract except `description_format`: its results never include a job description, so the format would change nothing.

### Hiring signals

A hiring signal is one event at one company, detected from its job postings. Ask an agent, for example, "Which fintech companies in Germany started hiring data engineers this month?". List hiring signals returns the newest detection day first, and for each signal the company and its domain, the type, one sentence such as "17 new jobs this week vs 3.1 a week normally", the detection day, the strength (1 to 100, comparable between signals of the same type) and up to five evidence job IDs. Get job reads those jobs for free.

- Filters: `types`, `domains`, `countries`, `company_sizes`, `industries`, `funding_stages`, `functions`, `roles`, `seniority`, `technologies`, `skills`, `job_countries`, `min_strength`, `detected_after`, `detected_before`, `created_after` and `exclude_agencies`. They combine with AND; several values in one filter match any of them.
- `industries`, `funding_stages` and `functions` are semicolon-separated, the rest comma-separated. The API separates values with commas, so a value that contains a comma is refused before any request.
- `types` is `hiring_surge`, `new_function`, `new_country`, `leadership_hire`, `new_skill`, `hiring_slowdown`, `first_role`, `new_technology`, `function_surge`, `new_city`, `hard_to_fill`, `leadership_role_closed`, `hiring_freeze` or `hiring_resumed`. `seniority` is `junior`, `mid`, `senior`, `director`, `vp`, `c_level` or `executive`. `company_sizes` is `1-10`, `11-50`, `51-200`, `201-500`, `501-1000`, `1001-5000`, `5001-10000` or `10001+`. Country filters take two-letter codes.
- `detected_after` and `detected_before` are days (`yyyy-MM-dd`), inclusive. `created_after` is an instant and is exclusive: to read only what is new, pass the newest `created_at` you already have.
- `company_id` reads one company's signals. With it, only `types`, `min_strength`, the three date filters, `limit` and `cursor` apply, and any other filter is refused by name rather than ignored.
- One call is one request. The result says whether more signals remain and gives the cursor; the tool never reads the next page by itself.
- In a Workflow the tool outputs `text` and `json` with `summary` (count, `has_more`, `next_cursor`, signals billed and the credits the API reported) and `signals` (each signal as the API returns it, with `company`, `details`, `focus` and `evidence_job_ids`, plus `type_label` and `summary`).

The shared signals contract has filters the tool leaves out on purpose: `company_ids` (use `company_id` or `domains`), `exclude_domains`, `categories`, `founded_after`, `technology_categories`, `job_regions`, `job_cities`, `min_new_jobs`, `min_days_open` and `reposted_only`. `tests/test_contract_drift.py` records the reason for each.

## Billing

Jobo bills per job, not per request. These notes follow the [billing docs](https://jobo.world/docs/billing), which are the source of truth.

- Search jobs bills every job a response returns, including a job an earlier search already returned. An empty result costs nothing.
- A Job Search plan's included jobs are used first, then the prepaid wallet at the pay-as-you-go rate of $3.00 per 1,000 jobs. The Unlimited plan has no per-job charge on Search, within the rate limits.
- Before a billed request runs, the API checks that included jobs plus the wallet cover a full page (`page_size`) and answers `402` if they do not. A smaller `page_size` needs less cover.
- List hiring signals bills every signal a response returns, at ten times the price of a job, and bills a signal again each time it is read. A plan's included signals are used first, then the wallet. The Unlimited plan has no per-signal charge. A call that returns no signals is free. When included signals plus the wallet cannot cover the page, the API answers `402`.
- Get job, Find companies, Find filter values and Find locations are free. They still count toward rate limits.

What the plugin does about it: Search jobs asks for 5 jobs by default and never more than 25 per call (a larger `page_size` is reduced to 25 and the result says so). A `402` is never retried, and neither is a read timeout, because a billed page may already have been delivered. An agent that searches in a loop pays for every job each call returns, so tell it when to stop.

List hiring signals asks for 5 signals by default and never more than 25 per call (a larger `limit` is reduced to 25 and the result says so). It reads one page per call, and its last line says how many signals were billed. A signals request is retried only when the API answered that it did not run: a `429`, or a `503` with `Retry-After`. It is never retried after a `500`, a timeout or a dropped connection, because those signals may already have been billed.

## Errors

| HTTP status | What the tool tells you |
| --- | --- |
| 401 | The API key was rejected. Check it in the plugin's authorization settings. |
| 402 | Included jobs (or signals) plus the wallet cannot cover the request. Top up the wallet (a top-up link is included when the API sends one) or use a smaller `page_size` or `limit`. |
| 403 | The key or account may not use the endpoint. For hiring signals, `account_key_required` means the key belongs to no account: signals are charged to an account, so use an account API key. |
| 404 | With a sandbox key, List hiring signals reports that signals are not available in the sandbox. |
| 429 | A rate limit was reached, with the wait the API asked for. Short waits (up to 20 seconds) are retried automatically, up to twice. Without a subscription, hiring signals allow 20 requests a minute, 200 an hour and 1,000 a day. |
| 5xx, no connection | The error is reported. A 500, a 503 that says when to retry (`Retry-After`) and a failure to connect are retried up to twice, except on List hiring signals, which retries only a 503 with `Retry-After`. A 503 without `Retry-After` ("Search took too long") is not retried, because the same request runs out of time again: narrow the search instead. |

## Limits and connection requirements

- The plugin contacts one host, `connect.jobo.world`, over HTTPS. The host is fixed in the code (`jobo_client/client.py`); Dify's plugin manifest has no field that declares or restricts outbound hosts. Self-hosted Dify instances need outbound HTTPS access to it, including through any proxy they use.
- A sandbox key (`jbe_test_...`) returns fictional jobs in the real response shape and serves job search and job lookups only. With a sandbox key the three lookup tools return a message saying the lookup is unavailable, List hiring signals fails with a message saying signals need a live account key, and the key is still accepted when you authorize. See <https://jobo.world/docs/sandbox>.
- Every call counts toward the account's rate limits: <https://jobo.world/docs/rate-limits>.

## Development

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
```

The tests use mocked HTTP and never touch the network. `tests/test_contract_drift.py` checks the Search jobs parameters and enums against the shared filter contract (`../contracts/filters.json`), and the List hiring signals parameters, enums and type labels against the signals contract (`../contracts/signals.json`). It is skipped where those files are absent, as in the standalone mirror. `tests/test_signal_summary.py` holds the same table of signal sentences as the connector core. To run the plugin against a Dify instance, copy `.env.example` to `.env`, fill in the debugging key from **Plugins** in Dify, and run `python -m main`.

## License

MIT. See [LICENSE](LICENSE).
