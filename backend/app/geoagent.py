from __future__ import annotations

from typing import Any
import json
import statistics

from .config import settings
from .services import compute_change_signals


def _summarize_frames(frames: list[dict[str, Any]], downloader) -> dict[str, Any]:
    datetimes = [f.get("datetime") for f in frames if f.get("datetime")]
    clouds = [f.get("cloud_cover") for f in frames if f.get("cloud_cover") is not None]
    change_signals = compute_change_signals(frames, downloader)

    return {
        "frame_count": len(frames),
        "start_datetime": min(datetimes) if datetimes else None,
        "end_datetime": max(datetimes) if datetimes else None,
        "mean_cloud_cover": round(statistics.mean(clouds), 2) if clouds else None,
        "max_cloud_cover": max(clouds) if clouds else None,
        "top_changes": change_signals[:5],
    }


def _fallback_report(prompt: str, summary: dict[str, Any], latest_item: dict[str, Any] | None) -> str:
    lines = [
        "# AOI Intelligence Report",
        "",
        f"## Analyst Prompt",
        f"{prompt}",
        "",
        "## Temporal Summary",
        f"- Frames analyzed: {summary.get('frame_count', 0)}",
        f"- Time window: {summary.get('start_datetime')} to {summary.get('end_datetime')}",
        f"- Mean cloud cover: {summary.get('mean_cloud_cover')}",
        "",
        "## Potential Change Signals",
    ]

    top_changes = summary.get("top_changes", [])
    if top_changes:
        for idx, item in enumerate(top_changes, start=1):
            lines.append(
                f"{idx}. {item['before_item_id']} -> {item['after_item_id']} (delta score {item['mean_abs_delta']})"
            )
    else:
        lines.append("No measurable frame-to-frame deltas were computed from available previews.")

    if latest_item:
        lines.extend(
            [
                "",
                "## Latest Frame",
                f"- Item ID: {latest_item.get('id')}",
                f"- Datetime: {latest_item.get('datetime')}",
                f"- Cloud cover: {latest_item.get('cloud_cover')}",
            ]
        )

    lines.extend(
        [
            "",
            "## Assessment",
            "This is a metadata + low-resolution preview based assessment. Confirm critical findings with full-resolution exploitation and external context.",
        ]
    )
    return "\n".join(lines)


def generate_geo_report(
    prompt: str,
    frames: list[dict[str, Any]],
    latest_item: dict[str, Any] | None,
    downloader,
) -> tuple[str, list[dict[str, Any]]]:
    summary = _summarize_frames(frames, downloader)
    insights = summary.get("top_changes", [])

    if not settings.openai_api_key:
        return _fallback_report(prompt, summary, latest_item), insights

    try:
        from openai import OpenAI  # lazy import

        client = OpenAI(api_key=settings.openai_api_key)
        system_prompt = (
            "You are a senior GEOINT analyst. Generate a concise intelligence-style report about a small AOI "
            "using temporal satellite imagery metadata and change metrics. Be explicit about confidence, assumptions, "
            "and likely explanations for change/no-change patterns."
        )

        user_payload = {
            "user_prompt": prompt,
            "latest_item": latest_item,
            "time_series_summary": summary,
            "tasking_context": "Satellogic visual l1d-sr collection, small AOI such as an air base",
        }

        # Prefer Responses API; fallback to Chat Completions for compatibility.
        try:
            resp = client.responses.create(
                model=settings.openai_model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, indent=2)},
                ],
            )
            report = getattr(resp, "output_text", None)
            if report:
                return report, insights
        except Exception:
            pass

        chat = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, indent=2)},
            ],
            temperature=0.2,
        )
        report = chat.choices[0].message.content or "No report content returned by model."
        return report, insights

    except Exception:
        return _fallback_report(prompt, summary, latest_item), insights
