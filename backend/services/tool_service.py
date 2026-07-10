import asyncio
import json
import subprocess
import sys
import os
from typing import Dict, Any, Optional, List
import httpx

from models import Tool, ToolType, ToolStatus
from database import SessionLocal


class ToolExecutionService:
    _MCP_ERROR_PATTERNS = (
        "database error:",
        "error:",
        "no such table",
        "syntax error",
        "sql error",
        "only select queries are allowed",
        "permission denied",
        "access denied",
    )

    @staticmethod
    def _mcp_result_indicates_failure(result: Dict[str, Any], text: str) -> bool:
        if result.get("isError"):
            return True
        low = (text or "").strip().lower()
        if not low:
            return False
        return any(pat in low for pat in ToolExecutionService._MCP_ERROR_PATTERNS)

    async def execute_tool(
        self, tool: Tool, parameters: Dict[str, Any], timeout_seconds: int = 60
    ) -> Dict[str, Any]:
        try:
            config = tool.config or {}
            if config.get("adapter") == "dataquery_agent":
                return await self._execute_dataquery_agent(tool, parameters)
            if tool.tool_type == ToolType.MCP:
                return await self._execute_mcp(tool, parameters, timeout_seconds)
            elif tool.tool_type == ToolType.RESTFUL:
                return await self._execute_restful(tool, parameters, timeout_seconds)
            elif tool.tool_type == ToolType.LOCAL_PYTHON:
                return await self._execute_local_python(tool, parameters, timeout_seconds)
            else:
                return {"success": False, "error": f"不支持的工具类型: {tool.tool_type}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_dataquery_agent(self, tool: Tool, parameters: Dict[str, Any]) -> Dict[str, Any]:
        from services.dataquery_service import dataquery_service

        config = tool.config or {}
        dq_agent_id = parameters.get("dq_agent_id") or config.get("dq_agent_id", "")
        question = parameters.get("question") or parameters.get("query") or ""
        datasource_id = parameters.get("datasource_id")
        top_k = int(parameters.get("top_k", 100))
        strict_mode = bool(parameters.get("strict_mode", True))
        return_sql_only = bool(parameters.get("return_sql_only", False))
        session_id = parameters.get("session_id", "")

        if not dq_agent_id:
            return {"success": False, "error": "缺少 dq_agent_id"}
        if not question:
            return {"success": False, "error": "缺少 question"}

        db = SessionLocal()
        try:
            result = await dataquery_service.query(
                db=db,
                dq_agent_id=dq_agent_id,
                question=question,
                datasource_id=datasource_id,
                top_k=top_k,
                strict_mode=strict_mode,
                return_sql_only=return_sql_only,
                session_id=session_id,
            )
            if result.get("success"):
                return {"success": True, "result": json.dumps(result, ensure_ascii=False), "raw": result}
            return {"success": False, "error": result.get("error", "dataquery 执行失败")}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def _resolve_mcp_tool_name(self, mcp_tool_name, parameters: Dict[str, Any], fallback: str) -> str:
        if isinstance(mcp_tool_name, list) and len(mcp_tool_name) > 0:
            if "tool_name" in parameters:
                requested = parameters.pop("tool_name")
                if requested in mcp_tool_name:
                    return requested
            return mcp_tool_name[0]
        if isinstance(mcp_tool_name, str) and "," in mcp_tool_name:
            names = [n.strip() for n in mcp_tool_name.split(",") if n.strip()]
            if names:
                if "tool_name" in parameters:
                    requested = parameters.pop("tool_name")
                    if requested in names:
                        return requested
                return names[0]
        return mcp_tool_name or fallback

    async def _execute_mcp(
        self, tool: Tool, parameters: Dict[str, Any], timeout_seconds: int
    ) -> Dict[str, Any]:
        config = tool.config or {}
        command = config.get("mcp_command", "") or config.get("command", "")
        args = config.get("mcp_args", []) or config.get("args", [])
        env = config.get("mcp_env", {}) or config.get("env", {})
        raw_tool_name = config.get("mcp_tool_name", "") or config.get("server_name", tool.name)
        mcp_tool_name = self._resolve_mcp_tool_name(raw_tool_name, parameters, tool.name)

        if not command:
            return {"success": False, "error": "MCP 工具缺少 command 配置"}

        merged_env = {**os.environ, **env}

        try:
            process = await asyncio.create_subprocess_exec(
                command, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )

            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "vela-agent", "version": "1.0.0"},
                },
            }

            init_str = json.dumps(init_request) + "\n"
            process.stdin.write(init_str.encode())
            await process.stdin.drain()

            init_response = await asyncio.wait_for(
                process.stdout.readline(), timeout=10
            )
            init_data = json.loads(init_response.decode().strip())

            if "error" in init_data:
                process.terminate()
                return {"success": False, "error": f"MCP 初始化失败: {init_data['error']}"}

            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
            notif_str = json.dumps(initialized_notification) + "\n"
            process.stdin.write(notif_str.encode())
            await process.stdin.drain()

            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": mcp_tool_name,
                    "arguments": parameters,
                },
            }

            call_str = json.dumps(tool_call_request) + "\n"
            process.stdin.write(call_str.encode())
            await process.stdin.drain()

            call_response = await asyncio.wait_for(
                process.stdout.readline(), timeout=timeout_seconds
            )
            call_data = json.loads(call_response.decode().strip())

            process.terminate()
            await process.wait()

            if "error" in call_data:
                return {"success": False, "error": f"MCP 调用失败: {call_data['error']}"}

            result = call_data.get("result", {})
            if result.get("isError"):
                err_text = ""
                for item in result.get("content", []):
                    if isinstance(item, dict) and item.get("type") == "text":
                        err_text = item.get("text", "")
                        break
                return {"success": False, "error": err_text or "MCP 工具返回错误"}

            content = result.get("content", [])
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)

            result_text = "\n".join(text_parts) if text_parts else json.dumps(result)
            if self._mcp_result_indicates_failure(result, result_text):
                return {"success": False, "error": result_text}

            return {
                "success": True,
                "result": result_text,
            }

        except asyncio.TimeoutError:
            if process:
                process.terminate()
            return {"success": False, "error": f"MCP 调用超时 ({timeout_seconds}s)"}
        except Exception as e:
            if process:
                process.terminate()
            return {"success": False, "error": f"MCP 调用异常: {str(e)}"}

    async def discover_mcp_tools(
        self, command: str, args: list, env: dict = None, timeout_seconds: int = 30
    ) -> Dict[str, Any]:
        merged_env = {**os.environ, **(env or {})}

        try:
            process = await asyncio.create_subprocess_exec(
                command, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )

            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "vela-agent", "version": "1.0.0"},
                },
            }

            init_str = json.dumps(init_request) + "\n"
            process.stdin.write(init_str.encode())
            await process.stdin.drain()

            init_response = await asyncio.wait_for(
                process.stdout.readline(), timeout=10
            )
            init_data = json.loads(init_response.decode().strip())

            if "error" in init_data:
                process.terminate()
                return {"success": False, "error": f"MCP 初始化失败: {init_data['error']}"}

            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
            notif_str = json.dumps(initialized_notification) + "\n"
            process.stdin.write(notif_str.encode())
            await process.stdin.drain()

            list_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }

            list_str = json.dumps(list_request) + "\n"
            process.stdin.write(list_str.encode())
            await process.stdin.drain()

            list_response = await asyncio.wait_for(
                process.stdout.readline(), timeout=timeout_seconds
            )
            list_data = json.loads(list_response.decode().strip())

            process.terminate()
            await process.wait()

            if "error" in list_data:
                return {"success": False, "error": f"获取工具列表失败: {list_data['error']}"}

            tools = list_data.get("result", {}).get("tools", [])
            tool_info_list = []
            for t in tools:
                tool_info_list.append({
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                })

            return {"success": True, "tools": tool_info_list, "total": len(tool_info_list)}

        except asyncio.TimeoutError:
            if process:
                process.terminate()
            return {"success": False, "error": f"获取工具列表超时 ({timeout_seconds}s)"}
        except Exception as e:
            if process:
                process.terminate()
            return {"success": False, "error": f"获取工具列表异常: {str(e)}"}

    async def _execute_restful(
        self, tool: Tool, parameters: Dict[str, Any], timeout_seconds: int
    ) -> Dict[str, Any]:
        config = tool.config or {}
        url = config.get("restful_url", "") or config.get("url", "")
        method = (config.get("restful_method", "") or config.get("method", "POST")).upper()
        headers = config.get("restful_headers", {}) or config.get("headers", {})
        body_template = config.get("restful_body_template", None) or config.get("body_template", None)

        if not url:
            return {"success": False, "error": "RESTful 工具缺少 url 配置"}

        url = url.format(**parameters)

        request_body = None
        if body_template:
            try:
                request_body = json.loads(json.dumps(body_template).format(**parameters))
            except (KeyError, ValueError) as e:
                request_body = {k: v.format(**parameters) if isinstance(v, str) else v
                               for k, v in body_template.items()}

        if method in ("GET", "DELETE") and not request_body:
            request_body = None

        timeout = httpx.Timeout(
            connect=10.0, read=float(timeout_seconds), write=30.0, pool=10.0
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=request_body,
                )
                response.raise_for_status()

                try:
                    result = response.json()
                except json.JSONDecodeError:
                    result = {"text": response.text}

                return {"success": True, "result": json.dumps(result, ensure_ascii=False)}
            except httpx.HTTPStatusError as e:
                return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"}
            except httpx.TimeoutException:
                return {"success": False, "error": f"RESTful 调用超时 ({timeout_seconds}s)"}
            except Exception as e:
                return {"success": False, "error": f"RESTful 调用异常: {str(e)}"}

    async def _execute_local_python(
        self, tool: Tool, parameters: Dict[str, Any], timeout_seconds: int
    ) -> Dict[str, Any]:
        config = tool.config or {}
        module_path = config.get("module", "")
        function_name = config.get("function", "")
        script = config.get("python_code", "") or config.get("script", "")

        if not module_path and not function_name and not script:
            return {"success": False, "error": "本地 Python 工具缺少 module 或 function 配置"}

        script = config.get("script", "")
        if script:
            return await self._execute_inline_script(script, parameters, timeout_seconds)

        try:
            import importlib
            mod = importlib.import_module(module_path)
            func = getattr(mod, function_name)

            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(**parameters), timeout=timeout_seconds)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, **parameters), timeout=timeout_seconds
                )

            if isinstance(result, dict):
                return {"success": True, "result": json.dumps(result, ensure_ascii=False)}
            elif isinstance(result, str):
                return {"success": True, "result": result}
            else:
                return {"success": True, "result": str(result)}

        except asyncio.TimeoutError:
            return {"success": False, "error": f"本地 Python 工具执行超时 ({timeout_seconds}s)"}
        except ModuleNotFoundError:
            return {"success": False, "error": f"模块未找到: {module_path}"}
        except AttributeError:
            return {"success": False, "error": f"函数未找到: {module_path}.{function_name}"}
        except Exception as e:
            return {"success": False, "error": f"本地 Python 工具执行异常: {str(e)}"}

    async def _execute_inline_script(
        self, script: str, parameters: Dict[str, Any], timeout_seconds: int
    ) -> Dict[str, Any]:
        try:
            script_with_params = script
            for key, value in parameters.items():
                script_with_params = script_with_params.replace(
                    f"{{{{{key}}}}}", json.dumps(value) if not isinstance(value, str) else value
                )

            process = await asyncio.create_subprocess_exec(
                sys.executable, "-c", script_with_params,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )

            if process.returncode != 0:
                return {"success": False, "error": stderr.decode()[:1000]}

            output = stdout.decode().strip()
            try:
                result = json.loads(output)
                return {"success": True, "result": json.dumps(result, ensure_ascii=False)}
            except json.JSONDecodeError:
                return {"success": True, "result": output}

        except asyncio.TimeoutError:
            return {"success": False, "error": f"内联脚本执行超时 ({timeout_seconds}s)"}
        except Exception as e:
            return {"success": False, "error": f"内联脚本执行异常: {str(e)}"}

    def _get_mcp_tool_names(self, config: dict) -> list:
        raw = config.get("mcp_tool_name", "")
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str) and raw.strip():
            return [n.strip() for n in raw.split(",") if n.strip()]
        return []

    def build_openai_tool_def(self, tool: Tool) -> Dict[str, Any]:
        params_schema = tool.parameters_schema or {}

        if tool.tool_type == "mcp":
            mcp_names = self._get_mcp_tool_names(tool.config or {})
            if len(mcp_names) > 1:
                return self._build_multi_mcp_tool_def(tool, params_schema, mcp_names)

        if isinstance(params_schema, dict) and params_schema.get("type") == "object":
            return {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or tool.display_name or tool.name,
                    "parameters": params_schema,
                },
            }

        properties = {}
        required = []
        for param_name, param_def in params_schema.items():
            if isinstance(param_def, dict):
                properties[param_name] = {
                    "type": param_def.get("type", "string"),
                    "description": param_def.get("description", ""),
                }
                if param_def.get("enum"):
                    properties[param_name]["enum"] = param_def["enum"]
                if param_def.get("required"):
                    required.append(param_name)
            elif isinstance(param_def, str):
                properties[param_name] = {"type": param_def, "description": ""}

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or tool.display_name or tool.name,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _build_multi_mcp_tool_def(
        self, tool: Tool, params_schema: dict, mcp_names: list
    ) -> Dict[str, Any]:
        tool_name_desc = "要调用的具体工具名称，可选: " + ", ".join(mcp_names)

        if isinstance(params_schema, dict) and params_schema.get("type") == "object":
            schema = json.loads(json.dumps(params_schema))
            props = schema.setdefault("properties", {})
            props["tool_name"] = {
                "type": "string",
                "description": tool_name_desc,
                "enum": mcp_names,
            }
            schema["required"] = ["tool_name"]
            return {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or tool.display_name or tool.name,
                    "parameters": schema,
                },
            }

        properties = {"tool_name": {
            "type": "string",
            "description": tool_name_desc,
            "enum": mcp_names,
        }}
        required = ["tool_name"]
        for param_name, param_def in (params_schema or {}).items():
            if isinstance(param_def, dict):
                properties[param_name] = {
                    "type": param_def.get("type", "string"),
                    "description": param_def.get("description", ""),
                }
                if param_def.get("enum"):
                    properties[param_name]["enum"] = param_def["enum"]
            elif isinstance(param_def, str):
                properties[param_name] = {"type": param_def, "description": ""}

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or tool.display_name or tool.name,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


tool_execution_service = ToolExecutionService()