"""Explore a debate transcript produced by the Loguru JSONL sink."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

DEFAULT_TRANSCRIPT = "transcripts/desk_selection.coworkers.jsonl"


def parse_transcript(data: str) -> tuple[list[dict[str, Any]], int]:
    """Parse serialized Loguru JSON lines into normalized events."""
    events: list[dict[str, Any]] = []
    invalid_lines = 0
    for line_number, line in enumerate(data.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue

        record = payload.get("record", {}) if isinstance(payload, dict) else {}
        extra = record.get("extra", {}) if isinstance(record, dict) else {}
        if not isinstance(extra, dict):
            extra = {}
        time_data = record.get("time", {}) if isinstance(record, dict) else {}
        if not isinstance(time_data, dict):
            time_data = {}

        event = dict(extra)
        event["event"] = extra.get("event", payload.get("event", "log"))
        event["message"] = extra.get("message", record.get("message", payload.get("text", "")))
        event["timestamp"] = time_data.get("repr", "")
        event["line"] = line_number
        events.append(event)
    return events, invalid_lines


def _event_values(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") == name]


def _render_transcript(events: list[dict[str, Any]]) -> None:
    starts = _event_values(events, "debate_started")
    topic_events = _event_values(events, "topic_published")
    topic = (starts[-1].get("topic") if starts else None) or (
        topic_events[-1].get("topic") if topic_events else None
    )
    if topic:
        st.subheader("Debate topic")
        st.info(topic)

    rounds = _event_values(events, "round_completed")
    published = _event_values(events, "agent_published")
    conclusions = _event_values(events, "judge_concluded")
    agents = sorted({str(item.get("speaker", "Agent")) for item in published})

    metric_columns = st.columns(3)
    metric_columns[0].metric("Rounds", len(rounds) or max(
        (int(item.get("round", 0)) for item in published), default=0
    ))
    metric_columns[1].metric("Participants", len(agents))
    metric_columns[2].metric("Messages", len(published))

    if published:
        round_numbers = sorted({int(item.get("round", 0)) for item in published})
        tabs = st.tabs([f"Round {number}" for number in round_numbers])
        for tab, round_number in zip(tabs, round_numbers):
            with tab:
                for item in published:
                    if int(item.get("round", 0)) != round_number:
                        continue
                    with st.container(border=True):
                        st.markdown(f"**{item.get('speaker', 'Agent')}**")
                        st.text(str(item.get("text", "")))
    else:
        st.info("No worker contributions were found in this transcript yet.")

    if conclusions:
        conclusion = conclusions[-1]
        st.subheader("Judge’s conclusion")
        judge_name = conclusion.get("judge", "Judge")
        favored = conclusion.get("biased_towards")
        if favored:
            st.caption(f"{judge_name} · configured preference: {favored}")
        else:
            st.caption(str(judge_name))
        st.success(str(conclusion.get("conclusion", "No conclusion text recorded.")))
    elif _event_values(events, "debate_finished"):
        st.info("The debate finished, but the transcript contains no judge conclusion event.")
    else:
        st.warning("This transcript appears to be from a debate that has not concluded yet.")

    with st.expander("Raw transcript events"):
        st.dataframe(events, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Debate transcript viewer", page_icon="💬", layout="wide")
    st.title("Social debate viewer")
    st.caption("Browse round-by-round messages and the judge’s final conclusion.")

    with st.sidebar:
        st.header("Transcript")
        transcript_path = st.text_input("JSONL file path", value=DEFAULT_TRANSCRIPT)
        uploaded = st.file_uploader("Or upload a JSONL transcript", type=["jsonl", "json", "txt"])

    transcript_text: str | None = None
    source = ""
    if uploaded is not None:
        transcript_text = uploaded.getvalue().decode("utf-8", errors="replace")
        source = uploaded.name
    else:
        path = Path(transcript_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_file():
            try:
                transcript_text = path.read_text(encoding="utf-8")
                source = str(path)
            except OSError as error:
                st.error(f"Could not read transcript: {error}")

    if transcript_text is None:
        st.info("Transcript not found. Run a debate or choose a JSONL file in the sidebar.")
        return

    events, invalid_lines = parse_transcript(transcript_text)
    st.caption(f"Source: `{source}` · {len(events)} events")
    if invalid_lines:
        st.warning(f"Skipped {invalid_lines} malformed JSON line(s).")
    if not events:
        st.warning("No valid events were found in this file.")
        return
    _render_transcript(events)


if __name__ == "__main__":
    main()
