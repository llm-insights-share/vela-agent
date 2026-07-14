import httpx
from typing import List, Dict, Any, Optional
from models import ModelProvider, ModelService, ProviderStatus


class ModelProviderService:

    @staticmethod
    async def list_models(provider: ModelProvider) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
        if provider.extra_headers:
            headers.update(provider.extra_headers)

        timeout = httpx.Timeout(
            connect=10.0,
            read=float(provider.timeout_seconds),
            write=30.0,
            pool=10.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                url = provider.base_url.rstrip("/") + "/models"
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()

                models = []
                model_list = data.get("data", data.get("models", []))
                for m in model_list:
                    model_id = m.get("id", m.get("model", ""))
                    if not model_id:
                        continue
                    models.append({
                        "model_name": model_id,
                        "display_name": model_id,
                        "max_tokens": m.get("max_tokens", 4096),
                        "capabilities": ["text"],
                    })
                return models
            except Exception as e:
                print(f"[ModelProviderService] list_models error for {provider.provider_code}: {e}")
                return []

    @staticmethod
    async def chat_completion(
        provider: ModelProvider,
        model_name: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
        if provider.extra_headers:
            headers.update(provider.extra_headers)

        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        read_timeout = float(timeout_seconds) if timeout_seconds else float(provider.timeout_seconds)
        timeout = httpx.Timeout(
            connect=10.0,
            read=read_timeout,
            write=30.0,
            pool=10.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                url = provider.base_url.rstrip("/") + "/chat/completions"
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code >= 400:
                    detail = response.text[:1000]
                    print(f"[ModelProviderService] chat error body: {detail}")
                    response.raise_for_status()
                data = response.json()

                result = dict(data)
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    if msg.get("reasoning_content"):
                        result["reasoning_content"] = msg["reasoning_content"]
                    elif msg.get("thinking"):
                        result["reasoning_content"] = msg["thinking"]
                return result
            except httpx.ReadTimeout:
                raise ValueError(f"模型服务响应超时（{read_timeout}s），请尝试简化 Skill 内容或增加超时时间")
            except Exception as e:
                print(f"[ModelProviderService] chat error for {provider.provider_code}: {e}")
                raise

    @staticmethod
    async def health_check(provider: ModelProvider) -> bool:
        try:
            models = await ModelProviderService.list_models(provider)
            return len(models) > 0
        except Exception:
            return False


model_provider_service = ModelProviderService()