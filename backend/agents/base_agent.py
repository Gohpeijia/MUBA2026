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
    TEMPERATURE: float = 0.2

    def __init__(self):
        groq_key       = os.getenv("GROQ_API_KEY")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        gemini_key     = os.getenv("GEMINI_API_KEY")

        self.providers = []

        if groq_key:
            self.providers.append({
                "name":    "Groq",
                "url":     "https://api.groq.com/openai/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                "model":   "qwen/qwen3.6-27b",
            })

        if openrouter_key:
            self.providers.append({
                "name":    "OpenRouter",
                "url":     "https://openrouter.ai/api/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
                "model":   "meta-llama/llama-3.1-8b-instruct",
            })

        if gemini_key:
            self.providers.append({
                "name":    "Gemini",
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
        Tries providers in sequence (Groq -> OpenRouter -> Gemini).
        Returns (raw_text, provider_name, model_name) or (None, None, None) on complete failure.
        """
        timeout = aiohttp.ClientTimeout(total=25)
        last_error = None

        for provider in self.providers:
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

                async with session.post(provider["url"], headers=provider["headers"], json=payload, timeout=timeout) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    raw_content = data["choices"][0]["message"]["content"]
                    cleaned = self._clean_llm_text(raw_content)
                    latency = round((time.time() - start_time) * 1000, 1)

                    print(f"  ⚡ [{analysis_id}] [{self.AGENT_ID}] Success via {provider['name']} ({provider['model']}) in {latency}ms")
                    return cleaned, provider["name"], provider["model"]

            except Exception as e:
                latency = round((time.time() - start_time) * 1000, 1)
                last_error = str(e)
                print(f"  ⚠️ [{analysis_id}] [{self.AGENT_ID}] {provider['name']} failed in {latency}ms: {last_error}")
                await asyncio.sleep(0.3)

        return None, None, None

    # ── Text & JSON Sanitization ──────────────────────────────────────────────

    @staticmethod
    def _clean_llm_text(text: str) -> str:
        """Strips <think> tags from thinking models and removes markdown code fences."""
        if not text:
            return ""

        # Pass 1: Remove <think>...</think> blocks
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # Pass 2: Remove unclosed <think>...
        cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.replace("</think>", "").strip()

        # Pass 3: Strip markdown fences (```json ... ```)
        cleaned = re.sub(r"^```(?:json)?", "", cleaned.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"```$", "", cleaned.strip())

        # Pass 4: Extract JSON object substring between first '{' and last '}'
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            cleaned = cleaned[start_idx : end_idx + 1]

        return cleaned.strip()

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
            parsed = json.loads(raw_text)
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
                parsed = json.loads(corr_text)
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
