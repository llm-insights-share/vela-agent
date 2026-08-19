from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def render_schedule_prompt(
    template: str,
    *,
    schedule_name: str,
    agent_name: str,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> str:
    raw_template = (template or "").strip() or "{{schedule_name}} 定时任务触发，请执行并输出结果。"
    safe_tz = timezone_name or "Asia/Shanghai"
    current = now or datetime.now(ZoneInfo(safe_tz))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(safe_tz))
    local_now = current.astimezone(ZoneInfo(safe_tz))
    replacements = {
        "{{date}}": local_now.strftime("%Y-%m-%d"),
        "{{time}}": local_now.strftime("%H:%M:%S"),
        "{{weekday}}": str(local_now.isoweekday()),
        "{{datetime}}": local_now.isoformat(),
        "{{schedule_name}}": schedule_name or "",
        "{{agent_name}}": agent_name or "",
    }
    rendered = raw_template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered
