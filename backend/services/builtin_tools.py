import os
import json
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class BuiltinTool:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    _tool_type: str = "builtin"

    @property
    def tool_type(self):
        return self._tool_type


BUILTIN_READ_TOOL = BuiltinTool(
    name="read_file",
    description="读取指定路径的文件内容。可以读取文本文件、代码文件、配置文件等。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要读取的文件的绝对路径或相对于工作目录的路径",
            },
            "offset": {
                "type": "integer",
                "description": "从第几行开始读取（从1开始），默认为1",
            },
            "limit": {
                "type": "integer",
                "description": "读取的最大行数，默认读取全部",
            },
        },
        "required": ["file_path"],
    },
)

BUILTIN_WRITE_TOOL = BuiltinTool(
    name="write_file",
    description="创建新文件或覆盖已有文件。如果文件已存在，其内容将被完全替换。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要写入的文件的绝对路径或相对于工作目录的路径",
            },
            "content": {
                "type": "string",
                "description": "要写入文件的完整内容",
            },
        },
        "required": ["file_path", "content"],
    },
)

BUILTIN_EDIT_TOOL = BuiltinTool(
    name="edit_file",
    description="在文件中进行精确的字符串替换。找到 old_string 并将其替换为 new_string。old_string 必须在文件中精确匹配且唯一。",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要编辑的文件的绝对路径或相对于工作目录的路径",
            },
            "old_string": {
                "type": "string",
                "description": "要被替换的原始文本内容，必须在文件中精确匹配",
            },
            "new_string": {
                "type": "string",
                "description": "替换后的新文本内容",
            },
            "replace_all": {
                "type": "boolean",
                "description": "是否替换所有匹配项（默认 false，只替换第一个匹配项）",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    },
)

BUILTIN_BASH_TOOL = BuiltinTool(
    name="bash",
    description="在沙箱环境中执行 shell 命令。支持常见的 Linux 命令（ls、cat、grep、find、mkdir、python 等）。",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令",
            },
            "timeout": {
                "type": "integer",
                "description": "命令执行超时时间（秒），默认 30 秒",
            },
        },
        "required": ["command"],
    },
)

BUILTIN_TAVILY_SEARCH_TOOL = BuiltinTool(
    name="tavily_web_search",
    description="使用 Tavily 搜索引擎进行网络搜索，获取实时网络信息。适用于需要最新信息、事实查询、新闻搜索等场景。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询关键词",
            },
            "max_results": {
                "type": "integer",
                "description": "返回结果数量，默认5，最大10",
            },
            "search_depth": {
                "type": "string",
                "description": "搜索深度：basic（基础）或 advanced（深度），默认 basic",
                "enum": ["basic", "advanced"],
            },
            "include_answer": {
                "type": "boolean",
                "description": "是否包含 AI 生成的摘要答案，默认 true",
            },
        },
        "required": ["query"],
    },
)

BUILTIN_WEB_EXTRACT_TOOL = BuiltinTool(
    name="web_extract",
    description="提取指定 URL 网页的正文内容，输出为 Markdown 格式。适用于获取网页文章、文档、新闻等正文内容，与 tavily_web_search 互补。",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要提取内容的网页 URL",
            },
            "max_length": {
                "type": "integer",
                "description": "返回内容的最大字符数，默认 10000，超出部分将被截断",
            },
        },
        "required": ["url"],
    },
)

BUILTIN_SEARCH_FILES_TOOL = BuiltinTool(
    name="search_files",
    description="在指定目录中搜索文件内容，支持正则表达式。类似 grep/ripgrep 的功能，用于在代码库或文档中快速定位包含特定内容的文件。",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "搜索的正则表达式模式",
            },
            "path": {
                "type": "string",
                "description": "搜索的目录路径，默认为当前工作目录",
            },
            "file_pattern": {
                "type": "string",
                "description": "文件名过滤模式（如 *.py, *.js），默认搜索所有文件",
            },
            "max_results": {
                "type": "integer",
                "description": "返回的最大匹配结果数，默认 50",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "是否忽略大小写，默认 false",
            },
        },
        "required": ["pattern"],
    },
)

BUILTIN_MEMORY_TOOL = BuiltinTool(
    name="memory",
    description="持久记忆读写工具。Agent 可跨会话保存和检索关键信息，如用户偏好、项目上下文、重要事实等。记忆存储在本地文件中，重启后依然可用。",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：save（保存记忆）、recall（检索记忆）、delete（删除记忆）、list（列出所有记忆）",
                "enum": ["save", "recall", "delete", "list"],
            },
            "key": {
                "type": "string",
                "description": "记忆的键名（save/recall/delete 时必填）",
            },
            "value": {
                "type": "string",
                "description": "记忆的内容（save 时必填）",
            },
            "tags": {
                "type": "string",
                "description": "记忆的标签，逗号分隔（save 时可选，便于分类检索）",
            },
        },
        "required": ["action"],
    },
)

BUILTIN_EXECUTE_CODE_TOOL = BuiltinTool(
    name="execute_code",
    description="在沙箱环境中执行 Python 或 JavaScript 代码。比 bash 更安全可控，适合数据处理、计算、脚本执行等场景。代码在独立子进程中运行，有超时保护。",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的代码内容",
            },
            "language": {
                "type": "string",
                "description": "编程语言：python 或 javascript，默认 python",
                "enum": ["python", "javascript"],
            },
            "timeout": {
                "type": "integer",
                "description": "执行超时时间（秒），默认 30 秒",
            },
        },
        "required": ["code"],
    },
)

BUILTIN_KB_SEARCH_TOOL = BuiltinTool(
    name="kb_search",
    description="检索内部知识库，从已上传的文档中查找相关信息。适用于查询项目文档、FAQ、技术规范等内部知识。可指定知识库 ID 或名称，不指定则搜索所有活跃知识库。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索查询关键词或问题",
            },
            "kb_id": {
                "type": "string",
                "description": "知识库 ID（可选）。不指定时搜索所有活跃知识库",
            },
            "kb_name": {
                "type": "string",
                "description": "知识库名称（可选，模糊匹配）。不指定时搜索所有活跃知识库",
            },
            "top_k": {
                "type": "integer",
                "description": "每个知识库返回的最大结果数，默认 5",
            },
        },
        "required": ["query"],
    },
)

BUILTIN_TOOLS: List[BuiltinTool] = [
    BUILTIN_READ_TOOL,
    BUILTIN_WRITE_TOOL,
    BUILTIN_EDIT_TOOL,
    BUILTIN_BASH_TOOL,
    BUILTIN_TAVILY_SEARCH_TOOL,
    BUILTIN_WEB_EXTRACT_TOOL,
    BUILTIN_SEARCH_FILES_TOOL,
    BUILTIN_MEMORY_TOOL,
    BUILTIN_EXECUTE_CODE_TOOL,
    BUILTIN_KB_SEARCH_TOOL,
]


def build_builtin_openai_tool_def(tool: BuiltinTool) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


async def execute_builtin_tool(tool_name: str, args: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    if tool_name == "read_file":
        return await _execute_read(args, output_dir)
    elif tool_name == "write_file":
        return await _execute_write(args, output_dir)
    elif tool_name == "edit_file":
        return await _execute_edit(args, output_dir)
    elif tool_name == "bash":
        return await _execute_bash(args, output_dir)
    elif tool_name == "tavily_web_search":
        return await _execute_tavily_search(args)
    elif tool_name == "web_extract":
        return await _execute_web_extract(args)
    elif tool_name == "search_files":
        return await _execute_search_files(args, output_dir)
    elif tool_name == "memory":
        return await _execute_memory(args)
    elif tool_name == "execute_code":
        return await _execute_code(args, output_dir)
    elif tool_name == "kb_search":
        return await _execute_kb_search(args)
    else:
        return {"success": False, "error": f"未知的内置工具: {tool_name}"}


def _resolve_path(file_path: str, output_dir: str) -> str:
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(output_dir, file_path)


def _sanitize_path(file_path: str, output_dir: str) -> str:
    resolved = os.path.realpath(_resolve_path(file_path, output_dir))
    output_real = os.path.realpath(output_dir)

    if not resolved.startswith(output_real):
        home = os.path.realpath(os.path.expanduser("~"))
        if resolved.startswith(home):
            return resolved
        raise ValueError(f"路径不在允许的范围内: {file_path}")

    return resolved


async def _execute_read(args: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    file_path = args.get("file_path", "")
    if not file_path:
        return {"success": False, "error": "缺少 file_path 参数"}

    try:
        resolved = _sanitize_path(file_path, output_dir)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not os.path.isfile(resolved):
        return {"success": False, "error": f"文件不存在: {file_path}"}

    try:
        offset = max(1, int(args.get("offset", 1)))
        limit = args.get("limit")

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if limit is not None:
            limit = int(limit)
            selected = lines[offset - 1 : offset - 1 + limit]
        else:
            selected = lines[offset - 1:]

        result = "".join(selected)
        return {
            "success": True,
            "result": result,
            "total_lines": total_lines,
            "lines_read": len(selected),
            "file_path": resolved,
        }
    except Exception as e:
        return {"success": False, "error": f"读取文件失败: {str(e)}"}


async def _execute_write(args: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    file_path = args.get("file_path", "")
    content = args.get("content", "")

    if not file_path:
        return {"success": False, "error": "缺少 file_path 参数"}

    try:
        resolved = _sanitize_path(file_path, output_dir)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        file_size = os.path.getsize(resolved)
        return {
            "success": True,
            "result": f"文件已写入: {resolved} ({_format_size(file_size)})",
            "file_path": resolved,
            "size": file_size,
        }
    except Exception as e:
        return {"success": False, "error": f"写入文件失败: {str(e)}"}


async def _execute_edit(args: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    file_path = args.get("file_path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    replace_all = args.get("replace_all", False)

    if not file_path:
        return {"success": False, "error": "缺少 file_path 参数"}
    if not old_string:
        return {"success": False, "error": "缺少 old_string 参数"}

    try:
        resolved = _sanitize_path(file_path, output_dir)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not os.path.isfile(resolved):
        return {"success": False, "error": f"文件不存在: {file_path}"}

    try:
        with open(resolved, "r", encoding="utf-8") as f:
            original = f.read()

        count = original.count(old_string)
        if count == 0:
            return {"success": False, "error": f"在文件中未找到指定的文本: {old_string[:100]}..."}

        if not replace_all and count > 1:
            return {
                "success": False,
                "error": f"old_string 在文件中出现了 {count} 次，不是唯一的。请使用 replace_all=true 替换所有匹配项，或提供更精确的 old_string。",
            }

        if replace_all:
            new_content = original.replace(old_string, new_string)
            replaced_count = count
        else:
            new_content = original.replace(old_string, new_string, 1)
            replaced_count = 1

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "success": True,
            "result": f"文件已编辑: {resolved}（替换了 {replaced_count} 处）",
            "file_path": resolved,
            "replacements": replaced_count,
        }
    except Exception as e:
        return {"success": False, "error": f"编辑文件失败: {str(e)}"}


async def _execute_bash(args: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    command = args.get("command", "")
    timeout = int(args.get("timeout", 30))

    if not command:
        return {"success": False, "error": "缺少 command 参数"}

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=output_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "success": False,
                "error": f"命令执行超时 ({timeout}s): {command[:100]}",
            }

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        result_parts = []
        if stdout_str:
            result_parts.append(stdout_str)
        if stderr_str:
            result_parts.append(f"[stderr]\n{stderr_str}")

        return {
            "success": process.returncode == 0,
            "result": "\n".join(result_parts) if result_parts else "(无输出)",
            "exit_code": process.returncode,
            "stdout": stdout_str,
            "stderr": stderr_str,
        }
    except Exception as e:
        return {"success": False, "error": f"命令执行失败: {str(e)}"}


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def _load_tavily_api_key() -> str:
    """从 vela.yaml 配置文件中读取 Tavily API Key"""
    import yaml
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vela.yaml")
    if not os.path.isfile(config_path):
        return ""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return (config.get("tools", {}).get("tavily", {}).get("api_key", "")) or ""
    except Exception:
        return ""


async def _execute_tavily_search(args: Dict[str, Any]) -> Dict[str, Any]:
    import httpx

    api_key = _load_tavily_api_key()
    if not api_key:
        return {"success": False, "error": "Tavily API Key 未配置，请在系统配置中设置"}

    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "缺少 query 参数"}

    max_results = min(int(args.get("max_results", 5)), 10)
    search_depth = args.get("search_depth", "basic")
    include_answer = args.get("include_answer", True)

    request_body = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": include_answer,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()

        answer = data.get("answer", "")
        results = data.get("results", [])

        output_parts = []
        if answer:
            output_parts.append(f"摘要答案:\n{answer}")
        if results:
            output_parts.append("搜索结果:")
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")
                output_parts.append(f"{i}. {title}\n   链接: {url}\n   内容: {content}")

        return {
            "success": True,
            "result": "\n\n".join(output_parts) if output_parts else "未找到相关结果",
        }

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"Tavily API 请求失败 (HTTP {e.response.status_code}): {e.response.text[:300]}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Tavily API 请求超时"}
    except Exception as e:
        return {"success": False, "error": f"Tavily 搜索异常: {str(e)}"}


# ─── web_extract: 网页正文提取 ─────────────────────────────────────────────

async def _execute_web_extract(args: Dict[str, Any]) -> Dict[str, Any]:
    import httpx

    url = args.get("url", "")
    if not url:
        return {"success": False, "error": "缺少 url 参数"}

    max_length = int(args.get("max_length", 10000))

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; VelaAgent/1.0; +https://vela.agent)"
            })
            response.raise_for_status()
            html = response.text

        # 使用 readability 提取正文
        try:
            from readability import Document
            doc = Document(html)
            title = doc.title()
            summary_html = doc.summary()
        except ImportError:
            # readability 不可用时，做简单的 HTML 标签清理
            import re
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""
            # 移除 script/style 标签
            summary_html = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
            summary_html = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", summary_html, flags=re.IGNORECASE)
            summary_html = re.sub(r"<nav[^>]*>[\s\S]*?</nav>", "", summary_html, flags=re.IGNORECASE)
            summary_html = re.sub(r"<footer[^>]*>[\s\S]*?</footer>", "", summary_html, flags=re.IGNORECASE)

        # HTML 转 Markdown（简易版）
        content = _html_to_markdown(summary_html)

        if len(content) > max_length:
            content = content[:max_length] + "\n\n... (内容已截断)"

        output_parts = []
        if title:
            output_parts.append(f"# {title}\n")
        output_parts.append(f"来源: {url}\n")
        output_parts.append(content)

        return {
            "success": True,
            "result": "\n".join(output_parts),
            "title": title,
            "url": url,
            "content_length": len(content),
        }

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"网页请求失败 (HTTP {e.response.status_code})"}
    except httpx.TimeoutException:
        return {"success": False, "error": "网页请求超时"}
    except Exception as e:
        return {"success": False, "error": f"网页提取失败: {str(e)}"}


def _html_to_markdown(html: str) -> str:
    """简易 HTML 转 Markdown"""
    import re

    text = html

    # 处理常见块级元素
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h4[^>]*>(.*?)</h4>", r"\n#### \1\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h5[^>]*>(.*?)</h5>", r"\n##### \1\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h6[^>]*>(.*?)</h6>", r"\n###### \1\n", text, flags=re.IGNORECASE | re.DOTALL)

    # 处理行内元素
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<a[^>]*href=[\"']([^\"']*)[\"'][^>]*>(.*?)</a>", r"[\2](\1)", text, flags=re.IGNORECASE | re.DOTALL)

    # 处理列表
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.IGNORECASE | re.DOTALL)

    # 处理段落和换行
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</blockquote>", "\n", text, flags=re.IGNORECASE)

    # 移除所有剩余 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)

    # 处理 HTML 实体
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    # 清理多余空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


# ─── search_files: 文件内容搜索 ────────────────────────────────────────────

async def _execute_search_files(args: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    pattern = args.get("pattern", "")
    if not pattern:
        return {"success": False, "error": "缺少 pattern 参数"}

    search_path = args.get("path", output_dir)
    if not os.path.isabs(search_path):
        search_path = os.path.join(output_dir, search_path)

    if not os.path.isdir(search_path):
        return {"success": False, "error": f"目录不存在: {search_path}"}

    file_pattern = args.get("file_pattern", "")
    max_results = min(int(args.get("max_results", 50)), 200)
    case_insensitive = args.get("case_insensitive", False)

    try:
        import re
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"success": False, "error": f"正则表达式无效: {str(e)}"}

    matches = []
    file_count = 0
    skipped_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode", ".next", "dist", "build"}

    try:
        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if d not in skipped_dirs]

            for filename in files:
                # 文件名过滤
                if file_pattern:
                    import fnmatch
                    if not fnmatch.fnmatch(filename, file_pattern):
                        continue

                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, search_path)

                # 跳过二进制文件和大文件
                try:
                    if os.path.getsize(filepath) > 1024 * 1024:  # > 1MB
                        continue
                except OSError:
                    continue

                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, 1):
                            if len(matches) >= max_results:
                                break
                            if regex.search(line):
                                matches.append({
                                    "file": rel_path,
                                    "line": line_no,
                                    "content": line.rstrip()[:200],
                                })
                        if len(matches) >= max_results:
                            break
                except (OSError, UnicodeDecodeError):
                    continue

            if len(matches) >= max_results:
                break

        if not matches:
            return {
                "success": True,
                "result": f"在 {search_path} 中未找到匹配 '{pattern}' 的内容",
                "matches": [],
                "total": 0,
            }

        output_parts = [f"在 {search_path} 中搜索 '{pattern}'，找到 {len(matches)} 个匹配:\n"]
        current_file = None
        for m in matches:
            if m["file"] != current_file:
                current_file = m["file"]
                output_parts.append(f"\n📄 {current_file}")
            output_parts.append(f"  L{m['line']}: {m['content']}")

        return {
            "success": True,
            "result": "\n".join(output_parts),
            "matches": matches,
            "total": len(matches),
        }

    except Exception as e:
        return {"success": False, "error": f"搜索失败: {str(e)}"}


# ─── memory: 持久记忆读写 ──────────────────────────────────────────────────

_MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")


def _ensure_memory_dir() -> str:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
    return _MEMORY_DIR


def _load_all_memories() -> Dict[str, Any]:
    """加载所有记忆到字典"""
    memory_dir = _ensure_memory_dir()
    memory_file = os.path.join(memory_dir, "memories.json")
    if os.path.isfile(memory_file):
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_all_memories(memories: Dict[str, Any]) -> None:
    """保存所有记忆"""
    memory_dir = _ensure_memory_dir()
    memory_file = os.path.join(memory_dir, "memories.json")
    with open(memory_file, "w", encoding="utf-8") as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)


async def _execute_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    action = args.get("action", "")
    if not action:
        return {"success": False, "error": "缺少 action 参数"}

    try:
        memories = _load_all_memories()

        if action == "save":
            key = args.get("key", "")
            value = args.get("value", "")
            if not key:
                return {"success": False, "error": "save 操作需要 key 参数"}
            if not value:
                return {"success": False, "error": "save 操作需要 value 参数"}

            tags_str = args.get("tags", "")
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

            from datetime import datetime
            entry = {
                "key": key,
                "value": value,
                "tags": tags,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            if key in memories:
                entry["created_at"] = memories[key].get("created_at", entry["created_at"])

            memories[key] = entry
            _save_all_memories(memories)

            return {
                "success": True,
                "result": f"记忆已保存: {key}",
                "key": key,
            }

        elif action == "recall":
            key = args.get("key", "")
            if not key:
                return {"success": False, "error": "recall 操作需要 key 参数"}

            if key not in memories:
                # 尝试模糊匹配
                matches = [k for k in memories if key.lower() in k.lower()]
                if matches:
                    results = []
                    for k in matches[:5]:
                        results.append(f"- {k}: {memories[k]['value']}")
                    return {
                        "success": True,
                        "result": f"未找到精确匹配 '{key}'，但找到相似的记忆:\n" + "\n".join(results),
                        "matches": matches,
                    }
                return {
                    "success": True,
                    "result": f"未找到记忆: {key}",
                    "found": False,
                }

            entry = memories[key]
            tags_str = f" [标签: {', '.join(entry.get('tags', []))}]" if entry.get("tags") else ""
            return {
                "success": True,
                "result": f"{key}: {entry['value']}{tags_str}",
                "key": key,
                "value": entry["value"],
                "tags": entry.get("tags", []),
                "found": True,
            }

        elif action == "delete":
            key = args.get("key", "")
            if not key:
                return {"success": False, "error": "delete 操作需要 key 参数"}

            if key not in memories:
                return {"success": False, "error": f"记忆不存在: {key}"}

            del memories[key]
            _save_all_memories(memories)
            return {
                "success": True,
                "result": f"记忆已删除: {key}",
            }

        elif action == "list":
            if not memories:
                return {
                    "success": True,
                    "result": "当前没有任何记忆",
                    "items": [],
                }

            items = []
            for key, entry in memories.items():
                tags_str = f" [{', '.join(entry.get('tags', []))}]" if entry.get("tags") else ""
                items.append(f"- {key}: {entry['value'][:100]}{tags_str}")

            return {
                "success": True,
                "result": f"共 {len(items)} 条记忆:\n" + "\n".join(items),
                "items": list(memories.keys()),
                "total": len(items),
            }

        else:
            return {"success": False, "error": f"未知的 action: {action}，可选: save, recall, delete, list"}

    except Exception as e:
        return {"success": False, "error": f"记忆操作失败: {str(e)}"}


# ─── execute_code: 沙箱代码执行 ────────────────────────────────────────────

# 安全限制：禁止导入的模块
_BLOCKED_MODULES = {
    "os", "subprocess", "shutil", "sys", "ctypes",
    "socket", "http", "urllib", "requests",
    "pathlib", "signal", "multiprocessing",
    "importlib", "pickle", "shelve", "marshal",
}

_PYTHON_SAFE_HEADER = """\
import math
import json
import re
import datetime
import collections
import itertools
import functools
import statistics
import random
import string
import hashlib
import base64
import textwrap
import typing
from decimal import Decimal
from fractions import Fraction
"""


async def _execute_code(args: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    code = args.get("code", "")
    if not code:
        return {"success": False, "error": "缺少 code 参数"}

    language = args.get("language", "python").lower()
    timeout = int(args.get("timeout", 30))

    if language == "python":
        return await _execute_python(code, output_dir, timeout)
    elif language == "javascript":
        return await _execute_javascript(code, output_dir, timeout)
    else:
        return {"success": False, "error": f"不支持的语言: {language}，可选: python, javascript"}


async def _execute_python(code: str, output_dir: str, timeout: int) -> Dict[str, Any]:
    # 安全检查：扫描危险的 import
    import re as _re
    dangerous_imports = _re.findall(
        r"^\s*(?:import|from)\s+(\w+)", code, _re.MULTILINE
    )
    blocked = [m for m in dangerous_imports if m in _BLOCKED_MODULES]
    if blocked:
        return {
            "success": False,
            "error": f"安全限制：不允许导入以下模块: {', '.join(blocked)}。"
                     f"execute_code 仅用于数据处理和计算，如需系统操作请使用 bash 工具。",
        }

    # 在代码前注入安全头和输出捕获
    wrapped_code = _PYTHON_SAFE_HEADER + "\n" + code

    # 写入临时文件执行
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8", dir=output_dir
    ) as f:
        f.write(wrapped_code)
        script_path = f.name

    try:
        process = await asyncio.create_subprocess_exec(
            "python", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=output_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {"success": False, "error": f"代码执行超时 ({timeout}s)"}

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        if process.returncode != 0:
            return {
                "success": False,
                "error": f"代码执行出错 (exit code {process.returncode}):\n{stderr_str[:2000]}",
                "stdout": stdout_str[:5000],
                "stderr": stderr_str[:2000],
            }

        result_parts = []
        if stdout_str:
            result_parts.append(stdout_str)
        if stderr_str:
            result_parts.append(f"[stderr]\n{stderr_str}")

        return {
            "success": True,
            "result": "\n".join(result_parts) if result_parts else "(无输出)",
            "stdout": stdout_str[:5000],
            "exit_code": process.returncode,
        }

    except Exception as e:
        return {"success": False, "error": f"代码执行失败: {str(e)}"}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


async def _execute_javascript(code: str, output_dir: str, timeout: int) -> Dict[str, Any]:
    # 检查 node 是否可用
    try:
        proc = await asyncio.create_subprocess_exec(
            "node", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            return {"success": False, "error": "Node.js 未安装或不可用"}
    except (asyncio.TimeoutError, FileNotFoundError):
        return {"success": False, "error": "Node.js 未安装或不可用，无法执行 JavaScript"}

    # 安全检查：禁止 require 调用
    import re as _re
    dangerous_requires = _re.findall(r"require\s*\(\s*['\"]([^'\"]+)", code)
    blocked = [r for r in dangerous_requires if not r.startswith(".") and r not in ("fs",)]
    if blocked:
        return {
            "success": False,
            "error": f"安全限制：不允许 require 以下模块: {', '.join(blocked)}。"
                     f"execute_code 仅用于数据处理和计算，如需系统操作请使用 bash 工具。",
        }

    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8", dir=output_dir
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        process = await asyncio.create_subprocess_exec(
            "node", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=output_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {"success": False, "error": f"代码执行超时 ({timeout}s)"}

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        if process.returncode != 0:
            return {
                "success": False,
                "error": f"代码执行出错 (exit code {process.returncode}):\n{stderr_str[:2000]}",
                "stdout": stdout_str[:5000],
                "stderr": stderr_str[:2000],
            }

        result_parts = []
        if stdout_str:
            result_parts.append(stdout_str)
        if stderr_str:
            result_parts.append(f"[stderr]\n{stderr_str}")

        return {
            "success": True,
            "result": "\n".join(result_parts) if result_parts else "(无输出)",
            "stdout": stdout_str[:5000],
            "exit_code": process.returncode,
        }

    except Exception as e:
        return {"success": False, "error": f"代码执行失败: {str(e)}"}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ─── kb_search: 知识库检索 ─────────────────────────────────────────────────

async def _execute_kb_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "缺少 query 参数"}

    kb_id = args.get("kb_id", "")
    kb_name = args.get("kb_name", "")
    top_k = min(int(args.get("top_k", 5)), 20)

    try:
        # 延迟导入，避免循环依赖
        from database import SessionLocal
        from models import KnowledgeBase, KnowledgeBaseStatus
        from services.knowledge_service import knowledge_service as ks

        db = SessionLocal()
        try:
            # 确定要搜索的知识库列表
            if kb_id:
                kbs = db.query(KnowledgeBase).filter(
                    KnowledgeBase.kb_id == kb_id,
                    KnowledgeBase.status == KnowledgeBaseStatus.ACTIVE,
                ).all()
                if not kbs:
                    return {"success": False, "error": f"知识库不存在或未激活: {kb_id}"}
            elif kb_name:
                kbs = db.query(KnowledgeBase).filter(
                    KnowledgeBase.name.ilike(f"%{kb_name}%"),
                    KnowledgeBase.status == KnowledgeBaseStatus.ACTIVE,
                ).all()
                if not kbs:
                    return {"success": False, "error": f"未找到匹配的知识库: {kb_name}"}
            else:
                kbs = db.query(KnowledgeBase).filter(
                    KnowledgeBase.status == KnowledgeBaseStatus.ACTIVE,
                ).all()
                if not kbs:
                    return {"success": False, "error": "当前没有可用的知识库"}

            all_results = []
            for kb in kbs:
                results = ks.search(kb.kb_id, query, top_k=top_k)
                for r in results:
                    r["kb_id"] = kb.kb_id
                    r["kb_name"] = kb.name
                    all_results.append(r)

            # 按分数排序，取前 top_k 条
            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            all_results = all_results[:top_k]

            if not all_results:
                kb_names = ", ".join(kb.name for kb in kbs)
                return {
                    "success": True,
                    "result": f"在知识库 [{kb_names}] 中未找到与 '{query}' 相关的内容",
                    "results": [],
                    "total": 0,
                }

            # 格式化输出
            output_parts = [f"在 {len(kbs)} 个知识库中检索 '{query}'，找到 {len(all_results)} 条相关结果:\n"]
            for i, r in enumerate(all_results, 1):
                score = r.get("score", 0)
                kb_name_found = r.get("kb_name", "")
                content = r["content"]
                if len(content) > 500:
                    content = content[:500] + "..."
                source = r.get("metadata", {}).get("filename", "")
                source_str = f" (来源: {source})" if source else ""
                output_parts.append(f"\n--- 结果 {i} [score: {score:.4f}] [{kb_name_found}]{source_str} ---\n{content}")

            return {
                "success": True,
                "result": "\n".join(output_parts),
                "results": all_results,
                "total": len(all_results),
                "searched_kbs": [kb.name for kb in kbs],
            }
        finally:
            db.close()

    except Exception as e:
        return {"success": False, "error": f"知识库检索失败: {str(e)}"}