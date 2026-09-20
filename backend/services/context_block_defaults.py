"""System-level default context blocks per execution mode (immutable catalog)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

EXECUTION_MODES = ("auto", "react", "plan_and_execute", "direct")

BUILTIN_BLOCK_KEYS = frozenset({
    "system_base",
    "connector",
    "cu_norms",
    "code_norms",
    "tool_search_norms",
    "knowledge",
    "project",
    "date",
    "memory_suffix",
    "skill_suffix",
    "plan_prompt",
})

CU_NORMS_DEFAULT = (
    "【驭屏已注册系统】调用 cu_navigate / cu_run_task 时，"
    "system_id 必须使用下列 name 或 UUID（也可使用 entry_url 中的域名词，如 asiainfo）；"
    "优先省略 url，使用 entry_url，勿猜测官网域名。\n"
    "{systems}\n\n"
    "【驭屏 UI 技能优先】执行浏览器/驭屏任务时：\n"
    "1. 必须先 cu_search_skills(query=用户任务) 或直接 cu_run_task(system_id, goal=用户任务)；\n"
    "2. 若检索命中 ACTIVE 技能，必须 cu_navigate 拿到 screen_session_id 后调用 "
    "cu_replay_skill(skill_id, screen_session_id)，按技能库步骤执行；\n"
    "3. 禁止在未检索技能库的情况下直接逐步 cu_act 完成可通过技能重放的任务；"
    "仅当检索无命中或 cu_replay_skill 返回 needs_replan 时，才允许 cu_observe/cu_act 临时操作。"
)

CODE_NORMS_DEFAULT = (
    "【Code Interpreter 使用规范】\n"
    "1. 涉及数值计算、统计分析、数据处理时，必须写代码执行，禁止心算。\n"
    "2. 使用 execute_code 工具执行 Python；同一会话内变量与文件跨调用保留。\n"
    "3. 工作区相对路径: {workspace}；产物保存到 outputs/ 子目录或使用 plt.show() 自动出图。\n"
    "4. 代码报错时阅读 traceback，修正后重试；连续失败 3 次应换思路。\n"
    "5. 缺少依赖时用 install_packages 安装白名单内的包。"
)

TOOL_SEARCH_NORMS_DEFAULT = (
    "【工具延迟加载 / Tool Search】\n"
    "平台内置工具已全部出现在可用工具列表中，可直接调用，无需 tool_search。\n"
    "tool_search 仅用于查找并激活用户安装（MCP/自定义）且尚未加载的工具。"
    "不要猜测未激活工具的名称；若无命中请换关键词。\n"
    "已激活的工具会在下一轮对话中出现在可用工具列表中。"
)

DATE_DEFAULT = (
    "当前日期：{today}（星期{weekday}）。"
    "理解「今天/本周/本月/今年」时必须以该日期为准；"
    "搜索新闻或时效信息时，查询关键词应使用正确的公历年份，不要使用过时年份。"
)

MEMORY_SUFFIX_DEFAULT = (
    "---\n"
    "【系统附注·长期记忆·必须遵从】\n"
    "下面是已为你检索到的长期记忆。若其中包含回答本问题所需的代号、组名、格式或事实，"
    "你必须原样采用；禁止回答「无法确认/不知道」，禁止编造其他代号。\n"
    "{body}"
)

SKILL_SUFFIX_DEFAULT = (
    "---\n"
    "【系统附注·Skill·必须遵从】\n"
    "{body}"
)

PLAN_PROMPT_DEFAULT = (
    "请先制定一个执行计划。列出需要执行的步骤，每步一行，格式为：\n"
    "- 步骤N: 描述 [可选: 工具名称]\n"
    "然后给出最终答案。"
)


def _base_specs(system_prompt: str = "") -> List[Dict[str, Any]]:
    base = (system_prompt or "").strip() or "你是一个智能助手。"
    return [
        {
            "block_key": "system_base",
            "title": "基础人设",
            "placement": "system",
            "source": "static",
            "content": base,
            "enabled": True,
            "sort_order": 10,
            "deletable": False,
        },
        {
            "block_key": "connector",
            "title": "连接器",
            "placement": "system",
            "source": "dynamic",
            "content": "## 连接器\n{body}",
            "enabled": True,
            "sort_order": 20,
            "deletable": False,
        },
        {
            "block_key": "cu_norms",
            "title": "驭屏规范",
            "placement": "system",
            "source": "builtin_template",
            "content": CU_NORMS_DEFAULT,
            "enabled": True,
            "sort_order": 30,
            "deletable": False,
        },
        {
            "block_key": "code_norms",
            "title": "Code 规范",
            "placement": "system",
            "source": "builtin_template",
            "content": CODE_NORMS_DEFAULT,
            "enabled": True,
            "sort_order": 40,
            "deletable": False,
        },
        {
            "block_key": "tool_search_norms",
            "title": "Tool Search 规范",
            "placement": "system",
            "source": "builtin_template",
            "content": TOOL_SEARCH_NORMS_DEFAULT,
            "enabled": True,
            "sort_order": 50,
            "deletable": False,
        },
        {
            "block_key": "knowledge",
            "title": "知识库名单",
            "placement": "system",
            "source": "dynamic",
            "content": "{body}",
            "enabled": True,
            "sort_order": 60,
            "deletable": False,
        },
        {
            "block_key": "project",
            "title": "项目上下文",
            "placement": "system",
            "source": "dynamic",
            "content": "{body}",
            "enabled": True,
            "sort_order": 70,
            "deletable": False,
        },
        {
            "block_key": "date",
            "title": "当前日期",
            "placement": "system",
            "source": "dynamic",
            "content": DATE_DEFAULT,
            "enabled": True,
            "sort_order": 80,
            "deletable": False,
        },
        {
            "block_key": "memory_suffix",
            "title": "长期记忆",
            "placement": "user_suffix",
            "source": "dynamic",
            "content": MEMORY_SUFFIX_DEFAULT,
            "enabled": True,
            "sort_order": 90,
            "deletable": False,
        },
        {
            "block_key": "skill_suffix",
            "title": "Skill",
            "placement": "user_suffix",
            "source": "dynamic",
            "content": SKILL_SUFFIX_DEFAULT,
            "enabled": True,
            "sort_order": 100,
            "deletable": False,
        },
    ]


def get_system_default_specs(
    execution_mode: str,
    system_prompt: str = "",
) -> List[Dict[str, Any]]:
    """Return deep-copied system default block specs for a mode (never mutated in place)."""
    mode = (execution_mode or "auto").strip() or "auto"
    if mode not in EXECUTION_MODES:
        mode = "auto"
    specs = deepcopy(_base_specs(system_prompt))
    if mode == "plan_and_execute":
        specs.append({
            "block_key": "plan_prompt",
            "title": "计划提示词",
            "placement": "mode_inject",
            "source": "static",
            "content": PLAN_PROMPT_DEFAULT,
            "enabled": True,
            "sort_order": 110,
            "deletable": False,
        })
    return specs


def validate_execution_mode(mode: str) -> str:
    m = (mode or "auto").strip() or "auto"
    if m not in EXECUTION_MODES:
        raise ValueError(f"invalid execution_mode: {mode}")
    return m
