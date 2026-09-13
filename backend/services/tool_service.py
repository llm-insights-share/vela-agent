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
        from services.monitor.oi_tracing import mark_span_error, mark_span_ok, oi_span, set_span_attrs
        from services.monitor.openinference_attrs import attrs_for_tool

        tool_name = getattr(tool, "name", "") or "unknown"
        desc = getattr(tool, "description", "") or ""
        with oi_span(
            f"execute_tool.{tool_name}",
            attrs_for_tool(tool_name=tool_name, tool_description=desc, parameters=parameters),
        ) as span:
            try:
                config = tool.config or {}
                if self._is_dataquery_tool(tool, config):
                    result = await self._execute_dataquery_agent(tool, parameters)
                elif tool.tool_type == ToolType.MCP:
                    result = await self._execute_mcp(tool, parameters, timeout_seconds)
                elif tool.tool_type == ToolType.RESTFUL:
                    result = await self._execute_restful(tool, parameters, timeout_seconds)
                elif tool.tool_type == ToolType.LOCAL_PYTHON:
                    result = await self._execute_local_python(tool, parameters, timeout_seconds)
                else:
                    result = {"success": False, "error": f"不支持的工具类型: {tool.tool_type}"}
                set_span_attrs(
                    span,
                    attrs_for_tool(
                        tool_name=tool_name,
                        tool_description=desc,
                        parameters=parameters,
                        output=result,
                    ),
                )
                if isinstance(result, dict) and result.get("success") is False:
                    mark_span_error(span, str(result.get("error") or "tool failed"))
                else:
                    mark_span_ok(span)
                return result
            except Exception as e:
                mark_span_error(span, str(e))
                set_span_attrs(
                    span,
                    attrs_for_tool(
                        tool_name=tool_name,
                        tool_description=desc,
                        parameters=parameters,
                        output={"success": False, "error": str(e)},
                    ),
                )
                return {"success": False, "error": str(e)}

    @staticmethod
    def _is_dataquery_tool(tool: Tool, config: Dict[str, Any]) -> bool:
        if isinstance(config, dict) and config.get("adapter") == "dataquery_agent":
            return True
        return getattr(tool, "name", "") == "nl2sql_query"

    def _resolve_dq_agent_id(self, parameters: Dict[str, Any], config: Dict[str, Any]) -> str:
        dq_agent_id = (parameters or {}).get("dq_agent_id") or (config or {}).get("dq_agent_id") or ""
        if dq_agent_id:
            return dq_agent_id
        db = SessionLocal()
        try:
            from models import DataQueryAgent, DataQueryAgentStatus
            agents = (
                db.query(DataQueryAgent)
                .filter(DataQueryAgent.status == DataQueryAgentStatus.ACTIVE)
                .all()
            )
            if len(agents) == 1:
                return agents[0].dq_agent_id
            return ""
        finally:
            db.close()

    def _heal_dataquery_config(self, tool: Tool, dq_agent_id: str) -> None:
        config = dict(tool.config or {})
        changed = False
        if config.get("adapter") != "dataquery_agent":
            config["adapter"] = "dataquery_agent"
            changed = True
        if dq_agent_id and not config.get("dq_agent_id"):
            config["dq_agent_id"] = dq_agent_id
            changed = True
        if not changed:
            return
        db = SessionLocal()
        try:
            from sqlalchemy.orm.attributes import flag_modified
            row = db.query(Tool).filter(Tool.tool_id == tool.tool_id).first()
            if not row:
                return
            merged = dict(row.config or {})
            merged["adapter"] = "dataquery_agent"
            if dq_agent_id:
                merged["dq_agent_id"] = dq_agent_id
            row.config = merged
            flag_modified(row, "config")
            db.commit()
            tool.config = merged
        finally:
            db.close()

    async def _execute_dataquery_agent(self, tool: Tool, parameters: Dict[str, Any]) -> Dict[str, Any]:
        from services.dataquery_service import dataquery_service

        config = tool.config or {}
        dq_agent_id = self._resolve_dq_agent_id(parameters, config)
        self._heal_dataquery_config(tool, dq_agent_id)
        question = parameters.get("question") or parameters.get("query") or ""
        datasource_id = parameters.get("datasource_id") or None
        if not datasource_id:
            datasource_id = None
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
        from services.mcp.client import call_mcp_tool
        from services.mcp.jsonrpc import McpAuthError, McpError

        config = dict(tool.config or {})
        raw_tool_name = config.get("mcp_tool_name", "") or config.get("server_name", tool.name)
        mcp_tool_name = self._resolve_mcp_tool_name(raw_tool_name, parameters, tool.name)

        if config.get("adapter") == "screenpilot":
            from services.screenpilot.mcp_pool import call_screenpilot_inprocess

            return await call_screenpilot_inprocess(mcp_tool_name, parameters)

        if config.get("mcp_pool") or config.get("screenpilot_pool"):
            from services.screenpilot.mcp_pool import default_pool_command, screenpilot_mcp_pool

            command = config.get("mcp_command", "") or config.get("command", "")
            args = config.get("mcp_args", []) or config.get("args", [])
            env = config.get("mcp_env", {}) or config.get("env", {})
            merged_env = {**os.environ, **env}
            pool_cmd, pool_args, pool_env = default_pool_command()
            return await screenpilot_mcp_pool.call_tool(
                mcp_tool_name,
                parameters,
                command=command or pool_cmd,
                args=args or pool_args,
                env={**pool_env, **merged_env},
                timeout_seconds=float(timeout_seconds),
            )

        db = SessionLocal()
        try:
            from services.mcp.server_service import resolve_tool_connection

            config = await resolve_tool_connection(db, tool)
        except McpAuthError as e:
            return {"success": False, "error": str(e)}
        except McpError as e:
            return {"success": False, "error": str(e)}
        finally:
            db.close()

        result = await call_mcp_tool(config, mcp_tool_name, parameters, timeout_seconds=timeout_seconds)
        if result.get("success"):
            raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
            text = result.get("result") or ""
            if self._mcp_result_indicates_failure(raw, text):
                return {"success": False, "error": text}
        return result

    async def discover_mcp_tools(
        self,
        command: str = "",
        args: list = None,
        env: dict = None,
        timeout_seconds: int = 30,
        transport: str = "stdio",
        url: str = "",
        headers: dict = None,
        auth_type: str = "none",
        auth_token: str = "",
        mcp_server_id: str = "",
    ) -> Dict[str, Any]:
        from services.mcp.client import discover_mcp_tools as mcp_discover
        from services.mcp.jsonrpc import McpAuthError, McpError

        if mcp_server_id:
            db = SessionLocal()
            try:
                from models import McpServer
                from services.mcp.server_service import connection_config_for_server

                server = db.query(McpServer).filter(McpServer.server_id == mcp_server_id).first()
                if not server:
                    return {"success": False, "error": "MCP Server 不存在"}
                cfg = await connection_config_for_server(db, server)
            except McpAuthError as e:
                return {"success": False, "error": str(e)}
            except McpError as e:
                return {"success": False, "error": str(e)}
            finally:
                db.close()
            return await mcp_discover(cfg, timeout_seconds=timeout_seconds)

        return await mcp_discover(
            {
                "transport": transport or "stdio",
                "mcp_command": command or "",
                "mcp_args": args or [],
                "mcp_env": env or {},
                "mcp_url": url or "",
                "mcp_headers": headers or {},
                "auth_type": auth_type or "none",
                "auth_token": auth_token or "",
            },
            timeout_seconds=timeout_seconds,
        )

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
            import inspect
            mod = importlib.import_module(module_path)
            func = getattr(mod, function_name)

            # Drop unexpected kwargs (models often invent placeholders like _unused)
            call_params = dict(parameters or {})
            try:
                sig = inspect.signature(func)
                accepts_var_kw = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                )
                if not accepts_var_kw:
                    allowed = {
                        name for name, p in sig.parameters.items()
                        if p.kind in (
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            inspect.Parameter.KEYWORD_ONLY,
                        )
                    }
                    call_params = {k: v for k, v in call_params.items() if k in allowed}
            except (TypeError, ValueError):
                pass

            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(**call_params), timeout=timeout_seconds)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, **call_params), timeout=timeout_seconds
                )

            # Propagate business-level failure for CLI wrappers ({"success": false, ...})
            if isinstance(result, dict) and result.get("success") is False:
                err = result.get("error") or result.get("message") or "工具返回失败"
                if isinstance(err, dict):
                    err = err.get("detail") or err.get("message") or str(err)
                return {
                    "success": False,
                    "error": str(err),
                    "result": json.dumps(result, ensure_ascii=False),
                }

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