"""Run a configured, round-based multi-agent debate."""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from pathlib import Path
from typing import Any

import yaml
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv
from loguru import logger

from common.logging import add_jsonl_sink

DEFAULT_CONFIG = Path(__file__).parent / "debates" / "desk_selection.coworkers.yaml"
PERSONAS_DIR = Path(__file__).parent / "personas"
JUDGES_DIR = Path(__file__).parent / "judges"
DEBATES_DIR = Path(__file__).parent / "debates"
BASE_PROMPT = PERSONAS_DIR / "base_prompt.md"


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        content = yaml.safe_load(file)
    if not isinstance(content, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return content


def _required(mapping: dict[str, Any], key: str, context: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required {context} field: {key}")
    return value


def _persona_prompt(persona_name: str, *, judge: bool = False) -> str:
    folder = JUDGES_DIR if judge else PERSONAS_DIR
    definition = None
    for path in sorted(folder.glob("*.yaml")):
        config = _read_yaml(path)
        if isinstance(config.get(persona_name), dict):
            definition = config[persona_name]
            break
    if definition is None:
        raise ValueError(f"Could not find persona '{persona_name}' in YAML files under {folder}")

    base = BASE_PROMPT.read_text(encoding="utf-8").strip()
    system = str(definition.get("System_Prompt", "")).strip()
    rounds = str(definition.get("Debate_Round_Prompt", "")).strip()
    persona = str(definition.get("Persona", persona_name)).strip()
    background = str(definition.get("Background", "")).strip()
    return "\n\n".join(part for part in (
        base,
        f"Your role: {persona}.",
        f"Background: {background}" if background else "",
        system,
        rounds,
    ) if part)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text is None:
        text = str(response)
    text = str(text).strip()
    if not text:
        raise RuntimeError("Agent returned an empty response")
    return text


def _record(event: str, **fields: Any) -> None:
    logger.bind(event=event, **fields).info(event)


def _format_context(history: list[dict[str, Any]], worker_name: str) -> str:
    if not history:
        return "No earlier debate messages are available."
    messages = []
    for item in history:
        if item["speaker"] == worker_name:
            continue
        messages.append(f"{item['speaker']} (round {item['round']}): {item['text']}")
    return "\n\n".join(messages) or "No other agents have spoken yet."


async def run_debate(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    load_dotenv()
    config_path = config_path.resolve()
    config = _read_yaml(config_path)
    topic = str(_required(config, "Topic", "debate"))
    workers = config.get("Agents")
    if not isinstance(workers, dict) or not workers:
        raise ValueError("Debate config must define at least one worker in 'Agents'")
    workers = {str(name): str(persona) for name, persona in workers.items()}
    rounds = int(_required(config, "Debate_Rounds", "debate"))
    if rounds < 1:
        raise ValueError("Debate_Rounds must be at least 1")

    judge_config = config.get("Judge")
    if not isinstance(judge_config, dict):
        raise ValueError("Debate config must define a 'Judge' mapping")
    judge_name = str(_required(judge_config, "name", "judge"))
    judge_persona = str(_required(judge_config, "persona", "judge"))
    favored_worker = judge_config.get("biased_towards")
    if favored_worker not in (None, "random", *workers.keys()):
        raise ValueError(f"Judge biased_towards must be 'random' or one of {list(workers)}")

    transcript_config = config.get("transcript", {})
    if not isinstance(transcript_config, dict):
        raise ValueError("'transcript' must be a mapping")
    should_transcribe = bool(transcript_config.get("enabled", False))
    transcript_path: Path | None = None
    sink_id: int | None = None
    if should_transcribe:
        transcript_path = Path(str(_required(transcript_config, "path", "transcript")))
        if not transcript_path.is_absolute():
            transcript_path = Path.cwd() / transcript_path
        sink_id = add_jsonl_sink(transcript_path)

    try:
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_CHAT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        if api_key:
            client = OpenAIChatClient(api_key=api_key, model=model)
        else:
            # The provider reads OPENAI_API_KEY and model settings from the environment.
            client = OpenAIChatClient(model=model)

        try:
            agents = {
                name: Agent(client=client, name=name, instructions=_persona_prompt(persona))
                for name, persona in workers.items()
            }
            judge = Agent(
                client=client,
                name=judge_name,
                instructions=_persona_prompt(judge_persona, judge=True),
            )

            history: list[dict[str, Any]] = []
            _record("debate_started", topic=topic, rounds=rounds, workers=list(workers), judge=judge_name)
            _record("topic_published", topic=topic, recipients=list(workers) + [judge_name])

            for round_number in range(1, rounds + 1):
                # Snapshot the history at round start: no agent sees another response
                # from this round until every worker has finished (the round barrier).
                earlier_rounds = list(history)

                async def speak(name: str, agent: Agent) -> tuple[str, str]:
                    prompt = (
                        f"Debate topic:\n{topic}\n\n"
                        f"You are {name}. This is round {round_number} of {rounds}.\n\n"
                        f"Messages from other agents in earlier rounds:\n"
                        f"{_format_context(earlier_rounds, name)}\n\n"
                        "Publish your contribution for this round. Address the arguments you have seen, "
                        "and state your position clearly."
                    )
                    _record("agent_received", recipient=name, round=round_number, message=prompt)
                    response = await agent.run(prompt)
                    return name, _response_text(response)

                contributions = await asyncio.gather(*(speak(name, agent) for name, agent in agents.items()))
                for name, message in contributions:
                    item = {"speaker": name, "round": round_number, "text": message}
                    history.append(item)
                    _record("agent_published", **item)
                _record("round_completed", round=round_number, messages=len(contributions))

            if favored_worker == "random":
                favored_worker = random.choice(list(workers))
            judge_prompt = (
                f"Debate topic:\n{topic}\n\n"
                f"The debate has concluded after {rounds} rounds.\n\n"
                f"Full transcript:\n{_format_judgment_history(history)}\n\n"
                "Conclude by evaluating the arguments, naming the strongest case, and giving a concise verdict."
            )
            if favored_worker:
                judge_prompt += f"\n\nConfigured bias: favor {favored_worker} when weighing the debate."
            _record("judge_received", judge=judge_name, message=judge_prompt)
            judgment = _response_text(await judge.run(judge_prompt))
            _record("judge_concluded", judge=judge_name, biased_towards=favored_worker, conclusion=judgment)
            _record("debate_finished", topic=topic, rounds=rounds)
            return {"topic": topic, "rounds": rounds, "transcript": history, "judge": judge_name, "conclusion": judgment}
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                await close()
    finally:
        if sink_id is not None:
            logger.remove(sink_id)


def _format_judgment_history(history: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"Round {item['round']} — {item['speaker']}:\n{item['text']}" for item in history
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a configured social debate")
    parser.add_argument("config", nargs="?", type=Path, default=DEFAULT_CONFIG, help="Path to debate YAML")
    parser.add_argument(
        "--all",
        dest="run_all",
        action="store_true",
        help="Run every YAML debate config in the debates directory",
    )
    args = parser.parse_args()
    if args.run_all and args.config != DEFAULT_CONFIG:
        parser.error("pass either a config path or --all, not both")

    if args.run_all:
        configs = sorted(DEBATES_DIR.glob("*.yaml"))
        if not configs:
            parser.error(f"No debate YAML files found in {DEBATES_DIR}")

        failures = []
        for index, config_path in enumerate(configs, start=1):
            print(f"\n[{index}/{len(configs)}] Running {config_path.name}")
            try:
                result = asyncio.run(run_debate(config_path))
            except Exception as error:
                failures.append((config_path, error))
                print(f"Failed: {error}", file=sys.stderr)
                continue
            print(f"{result['judge']} concluded:\n{result['conclusion']}")

        if failures:
            print(f"\n{len(failures)} of {len(configs)} simulations failed:", file=sys.stderr)
            for config_path, error in failures:
                print(f"- {config_path.name}: {error}", file=sys.stderr)
            raise SystemExit(1)
        print(f"\nCompleted all {len(configs)} simulations.")
        return

    result = asyncio.run(run_debate(args.config))
    print(f"\n{result['judge']} concluded:\n{result['conclusion']}")


if __name__ == "__main__":
    main()
