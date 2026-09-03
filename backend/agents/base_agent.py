# agents/base_agent.py
#
# BaseAgent: Shared Foundation for all Multi-Agent Reasoning Roles.
#
# Features:
#   - Reuses existing LLM infrastructure (Groq -> OpenRouter -> Gemini failover)
#   - Strict request timeout (12s) and retry limits (max 2)
#   - <think>...</think> reasoning block stripper (for Qwen3 / DeepSeek thinking models)
#   - Deterministic post-LLM schema validation & correction retry
#   - Observability logging (agent, provider, model, latency, status)
#   - Anti-hallucination guardrails (never invent missing data)

import os
import json
import time
import re
import asyncio
import aiohttp
from typing import Dict, Any, Optional, Tuple, Callable
from dotenv import load_dotenv

load_dotenv()


class BaseAgent:
    """
    Shared base class for all specialist reasoning agents.
    """
    AGENT_ID: str = "base"
    TIME_HORIZON: str = "MEDIUM_TERM"
    TEMPERATURE: float = 0.1

    # Shared cooldown state across all agent instances in the same process
    _provider_cooldowns: Dict[str, float] = {}

    def __init__(self):
        groq_key       = os.getenv("GROQ_API_KEY")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        gemini_key     = os.getenv("GEMINI_API_KEY")

        self.providers = []

        if groq_key:
            self.providers.append({
                "name":    "Groq (gpt-oss-20b)",
                "url":     "https://api.groq.com/openai/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                "model":   "openai/gpt-oss-20b",
            })
            self.providers.append({
                "name":    "Groq (qwen3.8-27b)",
                "url":     "https://api.groq.com/openai/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                "model":   "qwen/qwen3.8-27b",
            })
            self.providers.append({
                "name":    "Groq (qwen3.6-27b)",
                "url":     "https://api.groq.com/openai/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                "model":   "qwen/qwen3.6-27b",
            })

        if openrouter_key:
            self.providers.append({
                "name":    "OpenRouter (llama-3.1-8b)",
                "url":     "https://openrouter.ai/api/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
                "model":   "meta-llama/llama-3.1-8b-instruct",
            })

        if gemini_key:
            self.providers.append({
                "name":    "Gemini (2.5-flash)",
                "url":     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                "headers": {"Authorization": f"Bearer {gemini_key}", "Content-Type": "application/json"},
                "model":   "gemini-2.5-flash",
            })

        if not self.providers:
            raise RuntimeError("No LLM API keys found. Please set GROQ_API_KEY, OPENROUTER_API_KEY, or GEMINI_API_KEY in backend/.env")

    # ── LLM Invocation with Failover ──────────────────────────────────────────

    async def _call_llm_with_failover(
        self,
        session: aiohttp.ClientSession,
        system_prompt: str,
        user_content: str,
        analysis_id: str = "local",
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Tries providers in sequence (Groq models -> OpenRouter -> Gemini).
        Returns (raw_text, provider_name, model_name) or (None, None, None) on complete failure.
        """
        timeout = aiohttp.ClientTimeout(total=14)
        last_error = None
        
        try:
            cooldown_seconds = int(os.getenv("GROQ_PROVIDER_COOLDOWN_SECONDS", "30"))
        except ValueError:
            cooldown_seconds = 30

        for provider in self.providers:
            provider_name = provider["name"]
            provider_family = provider_name.split()[0]  # e.g., "Groq", "OpenRouter"

            # Check shared cooldown
            if time.time() < BaseAgent._provider_cooldowns.get(provider_family, 0):
                continue

            start_time = time.time()
            try:
                payload = {
                    "model":       provider["model"],
                    "temperature": self.TEMPERATURE,
                    "max_tokens":  2048,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_content},
                    ],
                }

                if provider_family == "Groq":
                    payload["response_format"] = {"type": "json_object"}

                async with session.post(provider["url"], headers=provider["headers"], json=payload, timeout=timeout) as resp:
                    if resp.status == 429:
                        raise aiohttp.ClientResponseError(
                            resp.request_info,
                            resp.history,
                            status=resp.status,
                            message="Too Many Requests",
                            headers=resp.headers,
                        )
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    raw_content = data["choices"][0]["message"]["content"]
                    latency = round((time.time() - start_time) * 1000, 1)

                    print(f"  ⚡ [{analysis_id}] [{self.AGENT_ID}] Success via {provider_name} ({provider['model']}) in {latency}ms")
                    return raw_content, provider_name, provider["model"]

            except Exception as e:
                latency = round((time.time() - start_time) * 1000, 1)
                last_error = str(e)

                is_429 = getattr(e, 'status', None) == 429 or "429" in str(e) or "Too Many Requests" in str(e)
                if is_429:
                    print(f"  ⚠️ [{analysis_id}] [{self.AGENT_ID}] {provider_family} rate limited (429). Skipping remaining {provider_family} providers and moving to fallback.")
                    BaseAgent._provider_cooldowns[provider_family] = time.time() + cooldown_seconds
                    continue
                
                print(f"  ⚠️ [{analysis_id}] [{self.AGENT_ID}] {provider_name} failed in {latency}ms: {last_error}")
                await asyncio.sleep(0.3)

        return None, None, None

    # ── Text & JSON Sanitization ──────────────────────────────────────────────

    @staticmethod
    def parse_json_response(content: str) -> Dict[str, Any]:
        if not content:
            raise ValueError("Empty LLM response")
            
        content = content.strip()

        # Remove Markdown code fences if the model still returns them.
        if content.startswith("```"):
            content = content.replace("```json", "", 1)
            content = content.replace("```", "", 1)
            content = content.strip()
            
        # Also clean up trailing tags if it's a thinking model (since it might output <think>)
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.replace("</think>", "").strip()
        
        # Ensure it's json bounded
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            cleaned = cleaned[start_idx : end_idx + 1]
            
        # Optional heuristics for trailing commas and newlines
        try:
            return json.loads(cleaned)
        except Exception:
            # 2. Heuristic: Remove trailing commas before closing braces/brackets
            cleaned_patched = re.sub(r",\s*([\]}])", r"\1", cleaned)
            try:
                return json.loads(cleaned_patched)
            except Exception:
                pass

            # 3. Heuristic: Replace raw newlines/tabs inside string literals
            cleaned_patched = re.sub(r'(?<!\\)\n', ' ', cleaned_patched)
            cleaned_patched = re.sub(r'(?<!\\)\t', ' ', cleaned_patched)
            
            # Standard fallback to raise informative error
            return json.loads(cleaned_patched)


    # ── Schema Validation & Correction Retry ──────────────────────────────────

    async def execute_with_validation(
        self,
        session: aiohttp.ClientSession,
        system_prompt: str,
        user_content: str,
        validator_func: Callable[[Dict], Tuple[bool, Optional[str]]],
        analysis_id: str = "local",
    ) -> Dict[str, Any]:
        """
        Executes LLM call, parses JSON, and deterministically validates schema.
        If validation fails, performs one correction attempt before graceful degradation.
        """
        raw_text, provider, model = await self._call_llm_with_failover(session, system_prompt, user_content, analysis_id)
        
        if not raw_text:
            return self._build_error_report("All LLM providers timed out or failed to respond.")

        # Attempt 1: Parse and validate
        try:
            parsed = self.parse_json_response(raw_text)
            is_valid, err_msg = validator_func(parsed)
            if is_valid:
                parsed["status"] = "SUCCESS"
                parsed["time_horizon"] = self.TIME_HORIZON
                parsed["provider_used"] = provider
                return parsed

            print(f"  ⚠️ [{analysis_id}] [{self.AGENT_ID}] Validation error: {err_msg}. Triggering correction retry...")
        except Exception as e:
            err_msg = f"JSON parse error: {str(e)}"
            print(f"  ⚠️ [{analysis_id}] [{self.AGENT_ID}] {err_msg}. Triggering correction retry...")

        # Attempt 2: Correction prompt
        correction_prompt = f"The previous output had an issue: {err_msg}. Please return ONLY valid JSON matching the exact schema."
        corr_text, provider, model = await self._call_llm_with_failover(
            session, system_prompt, f"{user_content}\n\nCORRECTION: {correction_prompt}", analysis_id
        )

        if corr_text:
            try:
                parsed = self.parse_json_response(corr_text)
                is_valid, err_msg = validator_func(parsed)
                if is_valid:
                    parsed["status"] = "SUCCESS"
                    parsed["time_horizon"] = self.TIME_HORIZON
                    parsed["provider_used"] = provider
                    return parsed
            except Exception as e:
                err_msg = str(e)

        return self._build_error_report(f"Validation failed after retry: {err_msg}")

    def _build_error_report(self, reason: str) -> Dict[str, Any]:
        """Subclasses can override to match their exact schema."""
        return {
            "agent":        self.AGENT_ID,
            "status":       "ERROR",
            "time_horizon": self.TIME_HORIZON,
            "error":        reason,
        }
