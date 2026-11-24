# Submitting the Jobo plugin to the Dify Marketplace

Maintainer notes. This file is not part of the package (`.difyignore` leaves it out). Nothing here has been run against the live repository: no fork, branch or PR exists yet.

Rules below were read on 2026-11-23 from:

- Docs: <https://docs.dify.ai/en/develop-plugin/publishing/marketplace-listing/submit-plugin-to-marketplace.md> (the "release-to-dify-marketplace" page serves the same text)
- `langgenius/dify-plugins` `main`: `README.md`, `.github/pull_request_template.md`, `docs/plugin-submission-requirements.md`, `docs/plugin-review-guidelines.md`, `docs/marketplace-curation-policy.md`, `.github/workflows/pre-check-plugin.yaml`
- `langgenius/dify-marketplace-toolkit` at commit `83ee707`: `validator/` and `toolkit/checks/`
- Guidelines: <https://docs.dify.ai/en/develop-plugin/publishing/standards/contributor-covenant-code-of-conduct.md> and <https://docs.dify.ai/en/develop-plugin/publishing/standards/privacy-protection-guidelines.md>

They change. Re-read the live PR template and the two repository docs before opening the PR; the docs page itself says "Review the live template before submitting; repository requirements can evolve."

## 0. Before anything

1. **Public source repository.** `manifest.yaml` has `repo: https://github.com/JoboAI/jobo-dify` and the README links it. The repository was created empty on 2026-11-23, and `connectors-mirror.yml` in this monorepo fills it from `Jobo.Connectors/dify` on every push to `main`. Check that it holds this folder before submitting: reviewers open it. The validator rejects a `repo` that is not on an allowed host (github.com, gitlab.com, bitbucket.org, gitee.com, codeberg.org, git.sr.ht) and a README with no such link (`toolkit/checks/source_hosts.py`).
   Docs: "A public source repository that reviewers and users can inspect."
2. **Unique name.** Guidelines checklist: "Unique name. Search the Marketplace first." On 2026-11-23 a Marketplace search for `jobo` (tool category) returned no plugin, and `langgenius/dify-plugins` had no `jobo/` directory. Re-check just before submitting.
3. **Free only.** Guidelines: "The Dify Marketplace currently accepts free plugins only." The plugin is free; it needs the user's own Jobo API key, and job search is billed by Jobo, not by Dify. Say so in the PR.
4. **Test in Dify.** The PR template asks: "I tested this plugin on Dify Community Edition and Dify Cloud, or documented any limitation below." The unit tests here mock HTTP and prove nothing about Dify itself. Run the plugin through remote debugging (`cp .env.example .env`, fill the key from **Plugins** in Dify, `python -m main`) on both, with a real Jobo key, and use only free calls plus one `page_size: 1` search. Do not tick the box until that is done.

## 1. Tools

| Tool | Where | Notes |
| --- | --- | --- |
| Dify plugin CLI (`dify`) | Homebrew `brew tap langgenius/dify && brew install dify` (Mac), or the release binary from <https://github.com/langgenius/dify-plugin-daemon/releases> | Docs: "Dify Plugin CLI". The 2026-11-23 build used release `0.6.15`, asset `dify-plugin-darwin-arm64`, whose SHA-256 matches the digest GitHub shows for the asset. Homebrew refused the tap until it was trusted (`brew trust`), so the release asset was used instead. |
| `yq` | <https://github.com/mikefarah/yq> (`brew install yq`) | Docs: "Python 3 and `yq` for local validation." |
| Marketplace toolkit | `git clone https://github.com/langgenius/dify-marketplace-toolkit.git` | Runs `validator/validate-difypkg.py`. |

## 2. Package and validate

From the repository root, with the plugin folder at `Jobo.Connectors/dify`:

```bash
# Run the unit tests first (Python 3.12).
cd Jobo.Connectors/dify
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt && python -m pytest
deactivate && rm -rf .venv .pytest_cache && find . -name __pycache__ -prune -exec rm -rf {} +
cd ../..

# Package. Docs: "dify plugin package ./your-plugin" from the directory above the plugin.
dify plugin package Jobo.Connectors/dify -o /path/outside/the/repo/jobo-0.1.0.difypkg

# Validate. Docs: "python3 validator/validate-difypkg.py /path/to/your-plugin.difypkg --output-dir ./validation-report"
git clone https://github.com/langgenius/dify-marketplace-toolkit.git
cd dify-marketplace-toolkit
python3 validator/validate-difypkg.py /path/outside/the/repo/jobo-0.1.0.difypkg \
  --output-dir ./validation-report \
  --pr-body-file /path/to/pr-body.md
```

Docs: "Exit code `0` means no blocking package-level errors were found. Exit code `1` means a blocking finding or environment error must be resolved. Warnings do not fail validation, but reviewers may ask for clarification." Open `validation-report/summary.md`, and paste the command and result into the PR's **Local validation** section.

`.difyignore` keeps `tests/`, `SUBMITTING.md`, dev requirements and caches out of the package. Check with `unzip -l jobo-0.1.0.difypkg`: no `.env`, no `__pycache__`, no `.git`.

Every release: bump `version` in `manifest.yaml` (and `jobo_client/client.py` `__version__`, sent in the `User-Agent`), rebuild, revalidate.

## 3. Where the package goes in `langgenius/dify-plugins`

Docs, "New plugin":

> Create a package directory under your author namespace: `<author>/<plugin-name>/<plugin-package>.difypkg`

For this plugin: `jobo/jobo/jobo-0.1.0.difypkg` (README example: "`langgenius/dify-plugin/dify-plugin-0.0.1.difypkg`"). The toolkit requires the author directory name to match `author` in `manifest.yaml` ("The author directory name should match the `author` field", `marketplace-curation-policy.md` section 5).

- Add exactly one `.difypkg` per PR. Docs: "Submit one `.difypkg` per PR. Combining plugins or versions prevents CI from identifying a single package path and blocks the submission."
- Not settled by the sources: the repository README says "Place your plugin source code and the packaged `.difypkg` file in that subdirectory", while the docs say the Marketplace "accepts a packaged `.difypkg`, not your source tree" and the update rule is "must contain only one file change - the new `.difypkg` file". Default to adding only the `.difypkg`; the source lives in the public repository from step 0.
- Keep only the current version in the directory: "Keep only the current version in that subdirectory and publish older versions as GitHub Releases" (README). On an update, add the new package; the docs say "Keep old published packages unless a maintainer explicitly asks otherwise", while the curation policy says "Keep only the current version in the repository". These two disagree; ask in the PR if it comes up.

## 4. Commit, branch and PR conventions

Docs ("Open the PR"), verbatim commands:

```bash
git clone https://github.com/<your-github-name>/dify-plugins.git
cd dify-plugins
git remote add upstream https://github.com/langgenius/dify-plugins.git
git fetch upstream
git switch main
git merge --ff-only upstream/main

git switch -c add-<plugin-name>-<version>      # add-jobo-0.1.0
mkdir -p <author>/<plugin-name>                # jobo/jobo
cp /path/to/plugin.difypkg <author>/<plugin-name>/

git status --short
git diff --stat                                # exactly one .difypkg

git add <author>/<plugin-name>/<plugin-package>.difypkg
git commit -m "add <plugin-name> <version>"    # add jobo 0.1.0
git push -u origin HEAD
```

- Branch: `add-<plugin-name>-<version>`. Commit message: `add <plugin-name> <version>`.
- PR title: the docs and templates give no title format. Not settled by the sources. Use the commit message form (`add jobo 0.1.0`). It must be English: the toolkit fails a PR whose title or body has CJK characters ("PR title/body primary content must be English", `toolkit/checks/pr/body.py`).
- Open the PR from your fork to `langgenius/dify-plugins:main`. Docs: "Keep the PR out of draft only when the package and description are ready for automated and human review." Opening, pushing or marking ready starts the automated checks.
- Do not open a replacement PR after a failed check: "Fix the package or PR, rebuild when needed, and update the same PR."

## 5. PR template

Docs: "The current template is part of the review contract. Do not delete fields or replace it with a short free-form description." Template: `.github/pull_request_template.md`. Draft body for this plugin (re-check against the live template; save it as a file to pass to `--pr-body-file`):

```markdown
# Plugin Submission

## Plugin information

- **Author**: jobo
- **Plugin name**: jobo
- **Version**: 0.1.0
- **Source repository**: https://github.com/JoboAI/jobo-dify
- **Contact**: support@jobo.world

## Submission type

- [x] New plugin
- [ ] Version update

## What changed

New tool plugin for the Jobo jobs API (https://jobo.world). Five tools: search jobs (billed by Jobo per job returned; page size defaults to 5 and is capped at 25), get job by id, find companies, find filter values and find locations (all free). It fills a gap: [explain; the Marketplace had no plugin named jobo on the day of the check, and no jobs-data search was looked for]. The user brings their own Jobo API key. The plugin is free.

## Risk level

- [x] Low risk
- [ ] Medium risk
- [ ] High risk

## Required checks

(Copy the live checklist. Tick each box only after verifying it.)

## Security and privacy notes

None of: command or code execution, SQL, SSH/SFTP, browser automation, file operations, arbitrary URL fetching, proxying, sensitive-data handling. The plugin calls one fixed HTTPS host, connect.jobo.world (hard-coded in jobo_client/client.py; the Dify manifest has no egress field), and sends the user's API key in the `X-Api-Key` header and the tool parameters as query or body. Requests have timeouts; error messages never contain the key. Privacy: PRIVACY.md, https://jobo.world/privacy.

## Local validation

(Paste the validator command and its summary table.)

## Reviewer notes

- Jobo bills search per job returned; the plugin states this in every description and README, caps page_size at 25 and never retries a 402.
- The validator's "prohibited financial activity" warning comes from README text that quotes Jobo's pay-as-you-go price. The plugin makes no payment, transfer or purchase.
- `meta.minimum_dify_version` is not set (recommended, not required); tested on: (fill in).
```

Risk level rationale: the docs' **Low** is "calls fixed, documented HTTPS APIs and does not execute user-controlled code, commands, SQL, file operations, browser automation, or arbitrary network requests". The plugin only builds requests to one fixed host. If a reviewer reads "sends user content externally" (Medium) into search text, accept Medium. The docs say: "If more than one level could apply, select the higher level."

## 6. What reviewers reject for

Each quoted from the source named.

| Rejected or flagged for | Source |
| --- | --- |
| Secrets, `.env`, `.git`, virtualenvs, caches, logs, local settings, IDE files, OS files, unexplained executables | "Reject or request changes if the package includes secrets, `.env`, `.git`, virtual environments, caches, logs, local settings, IDE files, OS-generated files, or unexplained executables." (`docs/plugin-review-guidelines.md`) |
| README without setup, usage, credentials, connection requirements and source link; exaggerated claims, ads, dead links, real user data in screenshots | "README in English with setup steps, required credentials, and usage. No exaggerated claims, ads, self-promotion, offensive content, real user data in screenshots, or dead links." (guidelines page) |
| Primary README not in English | "README.md primary content must be English; move localized content to README.<locale>.md" (`toolkit/checks/readme.py`); the docs say translations go under `readme/README_<locale>.md` |
| Missing or placeholder privacy policy; privacy not matching behaviour | "Check that the privacy policy matches the plugin behavior and the third-party services it calls." (`docs/plugin-review-guidelines.md`); `PRIVACY.md` is required, a template placeholder is an error (`toolkit/checks/manifest.py`) |
| Dependencies without a version, git or URL installs, `dify_plugin` below 0.9.0, broad ranges | "Avoid bare requirements, direct URL installs, and git-based installs unless the PR explains why they are required." and "Python plugins must use `dify-plugin >= 0.9.0`." (docs) |
| Known-vulnerable dependencies | "The validator also checks dependency metadata and queries the OSV database for known vulnerabilities." (docs) |
| Author containing `dify` or `langgenius` | "author must not contain 'dify'" (`toolkit/checks/manifest.py`) |
| Missing `repo`, `contact` (valid email), `privacy`, `description.en_US`, `label.en_US` in the manifest | `REQUIRED_FIELDS` in `toolkit/checks/manifest.py` |
| Missing, empty or off-vocabulary `tags` | "Every `manifest.yaml` must declare a non-empty `tags` list, and every tag must be one of the controlled values" (curation policy section 1). This plugin uses `search`, `business`. |
| Default template icon, or Dify's logos | The pre-check fails the template icon; guidelines: "Do not use Dify's logos in your plugin assets." |
| Wrong risk level, none or several ticked | "Selecting none or multiple levels produces `risk: missing` and a bot comment." (docs) |
| Plugin that duplicates another, or is one of several wrappers of the same API | "No functional duplicates." and "Restricted: unnecessary splitting, multiple plugins for the same API/auth; bundle them instead" (guidelines). Ship all five tools in this one plugin. |
| Same-author name collision | "collisions within the same author fail the check" (curation policy section 3) |
| Version already published, or an update that only bumps metadata | "must not already exist on the Dify Marketplace" (`docs/plugin-submission-requirements.md`); "New versions must add real capability, not just metadata bumps." (guidelines) |
| More than one `.difypkg`, flattened layout, several plugins in one directory | "no `.difypkg` flattened into the author root directory (fails)" (curation policy section 5) |
| Non-English PR title or body, template fields deleted | "Use English for the PR title, body, and primary README." (docs) |
| Payments, asset or token transfers | "Prohibited: financial transactions" (guidelines). The plugin only reads data; the validator still raises a manual-review warning because of the price in the README. |
| Unmonitored support channel | "Provide at least one support channel (GitHub repository or email) and keep it active." (guidelines) |

## 7. After the PR is open

- Checks run: package validation, PR body, PR review notes, version update, icon, version exists, dependency install (`pip install -r requirements.txt` from the package), plugin install, packaging rules (`.github/workflows/pre-check-plugin.yaml`).
- Docs: "After approval and merge, the repository validates the package again and uploads it to the production Marketplace. You do not need to start CI or upload the approved package yourself."
- Optional: `verified: true` is requested in a PR once criteria are met; the curation policy lists labels in at least `en_US` and `zh_Hans` among them, which this plugin does not have.
