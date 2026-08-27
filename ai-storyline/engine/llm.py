"""LLM Provider：可插拔。

- MockProvider：确定性脚本模型，用于引擎逻辑验证（Phase 0 默认）。
  读取剧本配套的 mock 脚本（beat_id -> 场景模板），保证金标准走查可复现。
- OpenAICompatProvider：兼容 OpenAI 接口（DeepSeek/豆包/Qwen 等），
  通过环境变量 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 配置。
"""
import json
import os
import re
import time
import urllib.request
from typing import Any, Dict, List, Optional


class LLMError(RuntimeError):
    pass


META_RE = re.compile(r"\[META\]\s*(\{.*?\})\s*\[/META\]", re.S)


class MockProvider:
    """确定性脚本模型。user 消息里携带 [META]{...}[/META] 结构块，
    内含 beat_id，Mock 据此查表生成场景，保证可复现。"""

    is_mock = True

    def __init__(self, script: Dict[str, Any]):
        self.script = script

    @staticmethod
    def load_script(path: str) -> Dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def generate(self, system: str, user: str) -> str:
        m = META_RE.search(user)
        if not m:
            raise LLMError("MockProvider: user 消息缺少 [META] 块")
        meta = json.loads(m.group(1))
        beat_id = meta.get("beat_id")
        scene = self.script.get("scenes", {}).get(beat_id or "")
        if scene is None:
            raise LLMError("MockProvider: 脚本中找不到 beat %r" % beat_id)
        # 依据玩家已选选项决定条件选项（visible_condition）
        scene = json.loads(json.dumps(scene))  # 深拷贝
        facts = set(meta.get("facts", []))
        choices = [c for c in scene.get("choices", []) if self._visible(c, facts)]
        scene["choices"] = choices
        return json.dumps(scene, ensure_ascii=False)

    @staticmethod
    def _visible(choice: Dict[str, Any], facts: set) -> bool:
        cond = choice.get("visible_condition")
        if not cond:
            return True
        if "fact" in cond:
            return cond["fact"] in facts
        if "all" in cond:
            return all(MockProvider._visible({"visible_condition": c}, facts) for c in cond["all"])
        return True


class OpenAICompatProvider:
    """OpenAI 兼容接口（DeepSeek/豆包/Qwen）。非流式，Phase 0 够用。"""

    is_mock = False

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None):
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL")
                         or "https://api.deepseek.com").rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or ""
        self.model = model or os.environ.get("LLM_MODEL") or "deepseek-chat"
        if not self.api_key:
            raise LLMError("未配置 LLM_API_KEY（环境变量）")
        self.last_usage: Optional[Dict[str, Any]] = None  # 每次调用后更新

    @staticmethod
    def parse_usage(data: Dict[str, Any], latency_ms: float = 0.0) -> Optional[Dict[str, Any]]:
        """从API响应解析用量（供埋点与测试）。"""
        usage = data.get("usage") or {}
        if not usage:
            return None
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "latency_ms": round(latency_ms, 1),
        }

    def generate(self, system: str, user: str) -> str:
        for use_json_mode in (True, False):
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 1.0,
            }
            if use_json_mode:
                body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(
                self.base_url + "/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + self.api_key},
            )
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", "ignore")
                except Exception:  # noqa: BLE001
                    pass
                # 部分端点要求prompt含"json"字样才接受json_object；去掉该模式重试
                if use_json_mode and e.code == 400 and "json" in err_body.lower():
                    continue
                raise LLMError("LLM 调用失败(HTTP %s): %s" % (e.code, err_body[:300])) from e
            except Exception as e:  # noqa: BLE001
                raise LLMError("LLM 调用失败: %s" % e) from e
            self.last_usage = self.parse_usage(data, (time.time() - t0) * 1000)
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                raise LLMError("LLM 响应格式异常: %s" % data) from e
    def generate_stream(self, system: str, user: str):
        """流式生成：逐块yield文本增量；最终chunk带usage时记录用量。

        用法（Python 3.9 无 yield from 返回值限制，直接迭代即可）：
            for delta in provider.generate_stream(sys, usr): ...
        """
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 1.0,
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
        )
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                pass
            raise LLMError("LLM 流式调用失败(HTTP %s): %s" % (e.code, err_body[:300])) from e
        except Exception as e:  # noqa: BLE001
            raise LLMError("LLM 流式调用失败: %s" % e) from e

        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    self.last_usage = self.parse_usage(
                        {"usage": obj["usage"]}, (time.time() - t0) * 1000)
                try:
                    delta = obj["choices"][0].get("delta", {}).get("content")
                except (KeyError, IndexError):
                    delta = None
                if delta:
                    yield delta
