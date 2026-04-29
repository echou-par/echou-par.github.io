# Agentic Commerce — Channel Assessment

Internal survey to collect team opinions on how to think about each AI ordering channel across six dimensions.

## Folder structure

- **`survey/`** — HTML form, served at <https://echou-par.github.io/agentic-commerce/survey/>
- **`survey-results/`** — One CSV per submission. Team members upload here after filling out the form.

## How submissions flow

1. Team member visits the survey URL and fills out the form.
2. On submit, their responses download as a CSV to their browser.
3. The success screen shows a one-click link to the GitHub upload page for `survey-results/`. They drop the CSV in and commit.
4. To review responses, browse `survey-results/` in this repo and download the CSVs.

No tokens, no servers, no API keys — just static HTML and the GitHub web UI.

## Editing the form

If you ever rename folders or move the repo, edit the `UPLOAD_URL` constant near the top of `survey/index.html`. Everything else (channels, attributes, rating scale) lives in the same file in clearly-labeled sections.
