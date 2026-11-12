# Social debate agents

This project runs configured, round-based debates with Microsoft Agent Framework.
Each worker publishes once per round. All worker responses are collected before
the next round starts, so agents only see peers' messages from earlier rounds.
A configured judge reviews the completed transcript and gives the conclusion.

## Setup

```bash
uv sync
```

Add your API key to the repository's ignored `.env` file:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_CHAT_MODEL=gpt-4o-mini
```

`OPENAI_CHAT_MODEL` is optional and defaults to `gpt-4o-mini`.

## Run

```bash
uv run social-debate
uv run social-debate src/agents/debates/desk_selection.coworkers.yaml
```

## View a transcript

After a debate has written its JSONL transcript, launch the Streamlit viewer:

```bash
uv sync
uv run streamlit run src/app/streamlit_app.py
```

The viewer opens the configured desk-selection transcript by default. Enter a
different JSONL path in the sidebar or upload a transcript file to view another
run.

Debate files define workers, judge, number of rounds, and optional JSONL
transcription. Persona and judge YAML files hold the corresponding prompts.
Relative transcript paths are resolved from the current working directory.

The desk-selection debate has judge variations:

```bash
uv run social-debate src/agents/debates/desk_selection.objective.yaml
uv run social-debate src/agents/debates/desk_selection.employee_biased.yaml
uv run social-debate src/agents/debates/desk_selection.random_bias.yaml
```

The original `desk_selection.coworkers.yaml` favors the manager (Worker1).
Each variation saves a separate transcript under `transcripts/`.

Run every debate config in `src/agents/debates/` sequentially with:

```bash
uv run social-debate --all
```

To run a three-worker version with an objective judge:

```bash
uv run social-debate src/agents/debates/desk_selection.three_workers.yaml
```
