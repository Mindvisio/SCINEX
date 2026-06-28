"""Unified LLM clients for strange_lie / Proof Engine (v2, SDK-based).

Rewritten 2026-05-31 to reuse the battle-tested approach from spine-annotator
(ai_pipeline.py): official SDKs + os.environ keys + per-client httpx proxy.
This replaces the v1 hand-rolled urllib client and its fragile key parser.

Five model channels:
  - claude-opus     : Claude Opus 4.8       (Anthropic SDK,  /v1/messages)
  - gpt-5.5-pro     : GPT-5.5 Pro           (OpenAI SDK,     /v1/responses)
  - gemini-pro      : Gemini 3.1 Pro        (google-genai,   generateContent)
  - deepseek-v4-pro : DeepSeek-V4-Pro        (OpenAI SDK -> OpenRouter chat)
  - deepseek-prover : DeepSeek-Prover-V2-671B(OpenAI SDK -> Novita chat)

Keys & networking:
  Keys live in /root/.api_keys. We `source` that file in a subshell and import
  the resulting env (so `$VAR` indirections and bash functions resolve exactly
  as bash sees them -- no naive parsing). Required vars:
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, OPENROUTER_API_KEY,
    NOVITA_API_KEY, and optionally LLM_PROXY.

  Frontier APIs (OpenAI/Anthropic/Google) block sci-node's RU IP (HTTP 403),
  so they go through the HTTPS proxy (LLM_PROXY). DeepSeek via OpenRouter and
  Novita work DIRECT (proxy can even cause 403 / tears long reasoning streams).
  Each ModelSpec declares `use_proxy` accordingly; `call(use_proxy=...)` overrides.

  Effort: every reasoning model is driven at its max sensible level by default
  (Anthropic xhigh, OpenAI high, Gemini HIGH). Pass reasoning_effort=... to lower.

Public API (unchanged from v1):
    from lib.llm_clients import call, MODELS, ping_all
    r = call('claude-opus', 'Prove dim(psl_3 over GF(3)) = 7.', max_tokens=4000)
    print(r.text, r.latency_s, r.usage)
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

def _resolve_keys_file() -> Path:
    env = os.environ.get('SCINEX_KEYS_FILE')
    if env:
        return Path(env)
    for cand in (Path.cwd()/'.env', Path.home()/'.api_keys', Path('/root/.api_keys')):
        if cand.exists():
            return cand
    return Path('/root/.api_keys')


KEYS_FILE = _resolve_keys_file()


# ----------------------------------------------------------------------------
# Key loading: source the bash file, capture env. No naive parsing.
# ----------------------------------------------------------------------------
def _load_keys() -> dict:
    """Source /root/.api_keys in bash and capture the resulting environment.

    Using bash `source` means $VAR indirections and functions resolve exactly
    as the shell sees them -- this is what every other project relies on and
    avoids the v1 bug where `KEY="$KEY"` inside a function clobbered the real key.
    """
    if not KEYS_FILE.exists():
        return {}
    # Print env as NUL-separated key=value after sourcing.
    script = f'set -a; source {KEYS_FILE} >/dev/null 2>&1; env -0'
    try:
        out = subprocess.run(['bash', '-c', script], capture_output=True, timeout=15)
        raw = out.stdout.decode('utf-8', 'replace')
    except Exception:
        return {}
    keys = {}
    for pair in raw.split('\x00'):
        if '=' not in pair:
            continue
        k, v = pair.split('=', 1)
        keys[k] = v
    return keys


_KEYS = _load_keys()
LLM_PROXY: Optional[str] = _KEYS.get('LLM_PROXY') or os.environ.get('LLM_PROXY')


def _key(name: str) -> Optional[str]:
    return _KEYS.get(name) or os.environ.get(name)


# ----------------------------------------------------------------------------
# Model registry
# ----------------------------------------------------------------------------
@dataclass
class ModelSpec:
    name: str
    provider: str            # 'anthropic'|'openai'|'google'|'openrouter'|'novita'
    model_id: str
    api_key_env: str
    role_hint: str
    api_style: str           # 'anthropic'|'responses'|'google'|'chat'
    context_length: int = 0
    reasoning: bool = False
    use_proxy: bool = False   # frontier APIs need proxy from RU; deepseek direct
    base_url: str = ''        # for openai-compat (openrouter/novita)
    fallback: str = ''        # model alias to retry on LLMError (one hop, no chains)
    notes: str = ''


MODELS: dict[str, ModelSpec] = {
    'claude-fable': ModelSpec(
        name='claude-fable', provider='anthropic', model_id='claude-fable-5',
        api_key_env='ANTHROPIC_API_KEY', role_hint='explorer', api_style='anthropic',
        context_length=200000, reasoning=True, use_proxy=True,
        fallback='claude-opus',
        notes='Claude Fable 5 (Claude 5 family, Mythos-class). PRIMARY explorer/verifier '
              'at effort=max (xhigh). Falls back to claude-opus on LLMError.',
    ),
    'claude-opus': ModelSpec(
        name='claude-opus', provider='anthropic', model_id='claude-opus-4-8',
        api_key_env='ANTHROPIC_API_KEY', role_hint='explorer', api_style='anthropic',
        context_length=200000, reasoning=True, use_proxy=True,
        notes='Claude Opus 4.8. Secondary anthropic channel + fallback target for claude-fable. effort=xhigh.',
    ),
    'gpt-5.5-pro': ModelSpec(
        name='gpt-5.5-pro', provider='openai', model_id='gpt-5.5-pro',
        api_key_env='OPENAI_API_KEY', role_hint='verifier', api_style='responses',
        context_length=400000, reasoning=True, use_proxy=True,
        notes='GPT-5.5 Pro. Cross-verify. /v1/responses + reasoning.effort=high. ~50s.',
    ),
    'gemini-pro': ModelSpec(
        name='gemini-pro', provider='google', model_id='gemini-3.1-pro-preview',
        api_key_env='GOOGLE_API_KEY', role_hint='critic', api_style='google',
        context_length=1048576, reasoning=True, use_proxy=True,
        notes='Gemini 3.1 Pro. Critic / lit-search. thinking_level=HIGH. ~7s.',
    ),
    'deepseek-v4-pro': ModelSpec(
        name='deepseek-v4-pro', provider='openrouter', model_id='deepseek/deepseek-v4-pro',
        api_key_env='OPENROUTER_API_KEY', role_hint='verifier', api_style='chat',
        base_url='https://openrouter.ai/api/v1',
        context_length=1048576, reasoning=True, use_proxy=False,
        fallback='deepseek-direct',
        notes='DeepSeek-V4-Pro reasoning verifier via OpenRouter (multi-provider redundancy, our '
              'OpenRouter quota, no proxy). max_tokens>=8000. Falls back to deepseek-direct on LLMError.',
    ),
    'deepseek-direct': ModelSpec(
        name='deepseek-direct', provider='deepseek', model_id='deepseek-v4-pro',
        api_key_env='DEEPSEEK_API_KEY', role_hint='verifier', api_style='chat',
        base_url='https://api.deepseek.com',
        context_length=1048576, reasoning=True, use_proxy=False,
        fallback='deepseek-v4-pro',
        notes='Same DeepSeek-V4-Pro via the official api.deepseek.com (our DeepSeek quota, no proxy). '
              'max_tokens>=8000. Falls back to the OpenRouter route (deepseek-v4-pro) on LLMError.',
    ),
    'deepseek-prover': ModelSpec(
        name='deepseek-prover', provider='novita', model_id='deepseek/deepseek-prover-v2-671b',
        api_key_env='NOVITA_API_KEY', role_hint='prover', api_style='chat',
        base_url='https://api.novita.ai/openai/v1',
        context_length=131072, reasoning=False, use_proxy=False,
        notes='Lean-4 formal prover. V4 obligations + mandatory Lean compile. Not an oracle.',
    ),
}


@dataclass
class LLMResponse:
    text: str
    reasoning: str = ''
    model: str = ''
    provider: str = ''
    latency_s: float = 0.0
    usage: dict = field(default_factory=dict)
    cost_usd: Optional[float] = None
    raw: object = None
    via_proxy: bool = False
    fallback_from: Optional[str] = None  # set if primary failed and fallback answered

    def __repr__(self):
        cost = f', ${self.cost_usd:.4f}' if self.cost_usd is not None else ''
        return (f'<LLMResponse {self.model} {self.latency_s:.1f}s '
                f'reasoning={len(self.reasoning)}{cost} proxy={self.via_proxy}>')


class LLMError(RuntimeError):
    pass


# ----------------------------------------------------------------------------
# Effort translation (universal level -> provider-specific)
# ----------------------------------------------------------------------------
def _anthropic_effort(level: Optional[str]) -> Optional[str]:
    if level in (None, 'none'):
        return None
    if level in ('low', 'medium', 'high', 'xhigh'):
        return level
    if level == 'max':
        return 'xhigh'          # Anthropic's true maximum effort
    return 'medium'


def _openai_effort(level: Optional[str]) -> Optional[str]:
    if level in (None, 'none'):
        return None
    if level in ('minimal', 'low', 'medium', 'high'):
        return level
    if level in ('max', 'xhigh', 'extra'):
        return 'high'           # responses API tops out at 'high'
    return 'medium'


def _google_thinking(level: Optional[str]):
    from google.genai.types import ThinkingConfig, ThinkingLevel
    if level is None:
        return None
    if level in ('none', 'minimal'):
        return ThinkingConfig(thinking_level=ThinkingLevel.MINIMAL)
    if level == 'low':
        return ThinkingConfig(thinking_level=ThinkingLevel.LOW)
    if level == 'medium':
        return ThinkingConfig(thinking_level=ThinkingLevel.MEDIUM)
    if level in ('high', 'xhigh', 'max', 'extra'):
        return ThinkingConfig(thinking_level=ThinkingLevel.HIGH)
    return ThinkingConfig(thinking_level=ThinkingLevel.MEDIUM)


# ----------------------------------------------------------------------------
# Lazy SDK clients (one per provider; cached). Per-client httpx proxy.
# ----------------------------------------------------------------------------
_clients: dict[str, object] = {}


def _proxy_for(use_proxy: bool) -> Optional[str]:
    return LLM_PROXY if (use_proxy and LLM_PROXY) else None


def _anthropic_client(use_proxy: bool):
    ck = f'anthropic:{use_proxy}'
    if ck not in _clients:
        from anthropic import Anthropic
        import httpx
        key = _key('ANTHROPIC_API_KEY')
        if not key:
            raise LLMError('ANTHROPIC_API_KEY missing')
        proxy = _proxy_for(use_proxy)
        if proxy:
            hc = httpx.Client(proxy=proxy, timeout=httpx.Timeout(300.0))
            _clients[ck] = Anthropic(api_key=key, http_client=hc)
        else:
            _clients[ck] = Anthropic(api_key=key)
    return _clients[ck]


def _openai_client(use_proxy: bool, base_url: str = ''):
    ck = f'openai:{use_proxy}:{base_url}'
    if ck not in _clients:
        from openai import OpenAI
        import httpx
        # which key depends on base_url (official vs openrouter vs novita)
        if 'openrouter' in base_url:
            key = _key('OPENROUTER_API_KEY')
        elif 'novita' in base_url:
            key = _key('NOVITA_API_KEY')
        elif 'deepseek' in base_url:
            key = _key('DEEPSEEK_API_KEY')
        else:
            key = _key('OPENAI_API_KEY')
        if not key:
            raise LLMError(f'API key missing for base_url={base_url or "openai"}')
        kwargs = {'api_key': key}
        if base_url:
            kwargs['base_url'] = base_url
        proxy = _proxy_for(use_proxy)
        if proxy:
            kwargs['http_client'] = httpx.Client(proxy=proxy, timeout=httpx.Timeout(300.0))
        _clients[ck] = OpenAI(**kwargs)
    return _clients[ck]


def _google_client(use_proxy: bool):
    ck = f'google:{use_proxy}'
    if ck not in _clients:
        from google import genai
        from google.genai.types import HttpOptions
        import httpx
        key = _key('GOOGLE_API_KEY')
        if not key:
            raise LLMError('GOOGLE_API_KEY missing')
        proxy = _proxy_for(use_proxy)
        if proxy:
            hc = httpx.Client(proxy=proxy, timeout=httpx.Timeout(300.0))
            _clients[ck] = genai.Client(api_key=key, http_options=HttpOptions(httpx_client=hc))
        else:
            _clients[ck] = genai.Client(api_key=key)
    return _clients[ck]


# ----------------------------------------------------------------------------
# Provider implementations
# ----------------------------------------------------------------------------
def _run_anthropic(spec, user_prompt, system_prompt, max_tokens, temperature,
                   effort, timeout, use_proxy):
    from anthropic import APIError
    client = _anthropic_client(use_proxy)
    eff = _anthropic_effort(effort)
    mt = max(max_tokens, 16000) if eff else max_tokens
    kwargs = {
        'model': spec.model_id,
        'messages': [{'role': 'user', 'content': user_prompt}],
        'max_tokens': mt,
    }
    if system_prompt:
        kwargs['system'] = system_prompt
    if eff:
        kwargs['thinking'] = {'type': 'adaptive'}
        kwargs['extra_body'] = {'output_config': {'effort': eff}}
    else:
        kwargs['temperature'] = temperature
    t0 = time.time()
    try:
        msg = client.messages.create(timeout=timeout, **kwargs)
    except APIError as e:
        raise LLMError(f'anthropic: {e}') from None
    dt = time.time() - t0
    text, reasoning = '', ''
    for block in msg.content:
        bt = getattr(block, 'type', None)
        if bt == 'text':
            text += block.text
        elif bt == 'thinking':
            reasoning += getattr(block, 'thinking', '')
    usage = {'input_tokens': msg.usage.input_tokens, 'output_tokens': msg.usage.output_tokens}
    return text, reasoning, usage, None, msg, dt


def _run_openai_responses(spec, user_prompt, system_prompt, max_tokens, temperature,
                          effort, timeout, use_proxy):
    from openai import APIError
    client = _openai_client(use_proxy)
    eff = _openai_effort(effort)
    kwargs = {
        'model': spec.model_id,
        'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': user_prompt}]}],
        'max_output_tokens': max_tokens,
    }
    if system_prompt:
        kwargs['instructions'] = system_prompt
    if eff:
        kwargs['reasoning'] = {'effort': eff}
    t0 = time.time()
    try:
        resp = client.responses.create(timeout=timeout, **kwargs)
    except APIError as e:
        raise LLMError(f'openai-responses: {e}') from None
    dt = time.time() - t0
    text = getattr(resp, 'output_text', '') or ''
    reasoning = ''
    if not text:
        # fall back to manual extraction
        for item in getattr(resp, 'output', []) or []:
            if getattr(item, 'type', '') == 'message':
                for ct in getattr(item, 'content', []) or []:
                    if getattr(ct, 'type', '') == 'output_text':
                        text += getattr(ct, 'text', '')
    usage = {}
    u = getattr(resp, 'usage', None)
    if u:
        usage = {'input_tokens': getattr(u, 'input_tokens', None),
                 'output_tokens': getattr(u, 'output_tokens', None),
                 'reasoning_tokens': getattr(getattr(u, 'output_tokens_details', None), 'reasoning_tokens', None)}
    return text, reasoning, usage, None, resp, dt


def _run_google(spec, user_prompt, system_prompt, max_tokens, temperature,
                effort, timeout, use_proxy):
    from google.genai.types import GenerateContentConfig
    from google.genai import errors as gerr
    client = _google_client(use_proxy)
    cfg_kwargs = {'max_output_tokens': max_tokens, 'temperature': temperature}
    if system_prompt:
        cfg_kwargs['system_instruction'] = system_prompt
    tc = _google_thinking(effort)
    if tc is not None:
        cfg_kwargs['thinking_config'] = tc
    config = GenerateContentConfig(**cfg_kwargs)
    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=spec.model_id, contents=user_prompt, config=config)
    except gerr.APIError as e:
        raise LLMError(f'google: {e}') from None
    dt = time.time() - t0
    text, reasoning = '', ''
    cands = getattr(resp, 'candidates', None) or []
    if cands:
        content = getattr(cands[0], 'content', None)
        for part in (getattr(content, 'parts', None) or []):
            ptext = getattr(part, 'text', '') or ''
            if getattr(part, 'thought', False):
                reasoning += ptext
            else:
                text += ptext
    usage = {}
    um = getattr(resp, 'usage_metadata', None)
    if um:
        usage = {'prompt_tokens': getattr(um, 'prompt_token_count', None),
                 'output_tokens': getattr(um, 'candidates_token_count', None),
                 'thoughts_tokens': getattr(um, 'thoughts_token_count', None)}
    return text, reasoning, usage, None, resp, dt


def _run_chat(spec, user_prompt, system_prompt, max_tokens, temperature,
              effort, timeout, use_proxy):
    """OpenAI-compatible chat completions (OpenRouter / Novita)."""
    from openai import APIError
    client = _openai_client(use_proxy, base_url=spec.base_url)
    messages = []
    if system_prompt:
        messages.append({'role': 'system', 'content': system_prompt})
    messages.append({'role': 'user', 'content': user_prompt})
    extra_headers = {}
    if spec.provider == 'openrouter':
        extra_headers = {'HTTP-Referer': 'https://strange-lie.local', 'X-Title': 'strange_lie'}
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=spec.model_id, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
            timeout=timeout, extra_headers=extra_headers or None)
    except APIError as e:
        raise LLMError(f'chat ({spec.provider}): {e}') from None
    dt = time.time() - t0
    choice = resp.choices[0]
    text = choice.message.content or ''
    reasoning = getattr(choice.message, 'reasoning', '') or ''
    usage = {}
    if resp.usage:
        usage = {'prompt_tokens': resp.usage.prompt_tokens,
                 'completion_tokens': resp.usage.completion_tokens,
                 'total_tokens': resp.usage.total_tokens}
    cost = getattr(resp.usage, 'cost', None) if resp.usage else None
    return text, reasoning, usage, cost, resp, dt


# ----------------------------------------------------------------------------
# Public entrypoint
# ----------------------------------------------------------------------------
def call(
    model_name: str,
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    max_tokens: int = 4000,
    temperature: float = 0.3,
    timeout: int = 300,
    reasoning_effort: str = 'max',
    use_proxy: Optional[bool] = None,
    _no_fallback: bool = False,
) -> LLMResponse:
    """Call a model from MODELS. Returns LLMResponse.

    reasoning_effort: 'max' (default) drives each reasoning model at its top
        sensible level (Anthropic xhigh / OpenAI high / Gemini HIGH). Ignored by
        non-reasoning models. Pass 'low'|'medium'|'high'|'none' to lower.
    use_proxy: None => use the model's declared default (frontier=proxy,
        deepseek=direct). True/False forces it.
    """
    if model_name not in MODELS:
        raise LLMError(f'unknown model {model_name!r}. Known: {list(MODELS)}')
    spec = MODELS[model_name]
    up = spec.use_proxy if use_proxy is None else use_proxy
    if up and not LLM_PROXY:
        raise LLMError('proxy requested but LLM_PROXY unset')

    eff = reasoning_effort if spec.reasoning else None

    try:
        return _dispatch(spec, user_prompt, system_prompt, max_tokens,
                         temperature, eff, timeout, up)
    except LLMError as primary_err:
        if spec.fallback and not _no_fallback:
            r = call(spec.fallback, user_prompt,
                     system_prompt=system_prompt, max_tokens=max_tokens,
                     temperature=temperature, timeout=timeout,
                     reasoning_effort=reasoning_effort, use_proxy=use_proxy,
                     _no_fallback=True)
            r.fallback_from = f'{model_name} ({str(primary_err)[:120]})'
            return r
        raise


def _dispatch(spec, user_prompt, system_prompt, max_tokens,
              temperature, eff, timeout, up) -> LLMResponse:
    if spec.api_style == 'anthropic':
        text, reasoning, usage, cost, raw, dt = _run_anthropic(
            spec, user_prompt, system_prompt, max_tokens, temperature, eff, timeout, up)
    elif spec.api_style == 'responses':
        text, reasoning, usage, cost, raw, dt = _run_openai_responses(
            spec, user_prompt, system_prompt, max_tokens, temperature, eff, timeout, up)
    elif spec.api_style == 'google':
        text, reasoning, usage, cost, raw, dt = _run_google(
            spec, user_prompt, system_prompt, max_tokens, temperature, eff, timeout, up)
    else:  # 'chat'
        text, reasoning, usage, cost, raw, dt = _run_chat(
            spec, user_prompt, system_prompt, max_tokens, temperature, eff, timeout, up)

    return LLMResponse(
        text=text, reasoning=reasoning, model=spec.model_id, provider=spec.provider,
        latency_s=dt, usage=usage, cost_usd=cost, raw=raw, via_proxy=up,
    )


def ping_all() -> dict[str, dict]:
    """Smoke-test every model with a trivial prompt. Returns per-model status."""
    out = {}
    for name, spec in MODELS.items():
        try:
            r = call(name, '2+2=? Reply with one digit.',
                     max_tokens=8000 if spec.reasoning else 64,
                     temperature=0.0)
            out[name] = {
                'ok': True, 'latency_s': round(r.latency_s, 1),
                'reasoning_len': len(r.reasoning), 'via_proxy': r.via_proxy,
                'cost_usd': r.cost_usd, 'text': (r.text or '').strip()[:60],
            }
        except Exception as e:
            out[name] = {'ok': False, 'error': str(e)[:200]}
    return out


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == 'ping':
        print(json.dumps(ping_all(), indent=2, ensure_ascii=False))
    elif len(sys.argv) >= 2 and sys.argv[1] == 'env':
        print(f'LLM_PROXY: {"set" if LLM_PROXY else "NOT SET"}')
        for n in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_API_KEY',
                  'OPENROUTER_API_KEY', 'NOVITA_API_KEY', 'DEEPSEEK_API_KEY'):
            v = _key(n)
            print(f'  {n}: {"set len="+str(len(v)) if v else "MISSING"}')
        print(f'models: {list(MODELS)}')
    else:
        print('usage: python3 -m lib.llm_clients [ping|env]')
        for n, s in MODELS.items():
            print(f'  {n:18s} {s.provider:11s} {s.api_style:10s} proxy={s.use_proxy} {s.model_id}')

# ----------------------------------------------------------------------------
# Vision entrypoint (appended): text + images. anthropic + openai-responses only.
# Reuses the clients/proxy/effort helpers above. call() stays text-only/unchanged.
# ----------------------------------------------------------------------------
def _img_to_b64(item):
    """item: file path (str) or (b64, media_type) tuple -> (b64, media_type)."""
    import base64 as _b64, mimetypes as _mt
    if isinstance(item, tuple):
        return item
    data = Path(item).read_bytes()
    mt = _mt.guess_type(str(item))[0] or 'image/png'
    return _b64.b64encode(data).decode(), mt


def call_vision(model_name, user_prompt, images, *, system_prompt=None,
                max_tokens=2000, temperature=0.2, timeout=300,
                reasoning_effort='medium', use_proxy=None) -> LLMResponse:
    """Multimodal call: text + images (list of file paths or (b64, media_type)).
    Supported on anthropic (claude-*), openai responses (gpt-*) and google (gemini-*) channels."""
    if model_name not in MODELS:
        raise LLMError(f'unknown model {model_name!r}')
    spec = MODELS[model_name]
    up = spec.use_proxy if use_proxy is None else use_proxy
    if up and not LLM_PROXY:
        raise LLMError('proxy requested but LLM_PROXY unset')
    imgs = [_img_to_b64(i) for i in (images or [])]
    eff = reasoning_effort if spec.reasoning else None
    t0 = time.time()

    if spec.api_style == 'anthropic':
        from anthropic import APIError
        client = _anthropic_client(up)
        content = [{'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': b64}}
                   for (b64, mt) in imgs]
        content.append({'type': 'text', 'text': user_prompt})
        ea = _anthropic_effort(eff)
        mtok = max(max_tokens, 16000) if ea else max_tokens
        kwargs = {'model': spec.model_id, 'messages': [{'role': 'user', 'content': content}],
                  'max_tokens': mtok}
        if system_prompt:
            kwargs['system'] = system_prompt
        if ea:
            kwargs['thinking'] = {'type': 'adaptive'}
            kwargs['extra_body'] = {'output_config': {'effort': ea}}
        else:
            kwargs['temperature'] = temperature
        try:
            msg = client.messages.create(timeout=timeout, **kwargs)
        except APIError as e:
            raise LLMError(f'anthropic-vision: {e}') from None
        text = ''.join(getattr(b, 'text', '') for b in msg.content if getattr(b, 'type', None) == 'text')
        usage = {'input_tokens': msg.usage.input_tokens, 'output_tokens': msg.usage.output_tokens}
        return LLMResponse(text=text, model=spec.model_id, provider=spec.provider,
                           latency_s=time.time() - t0, usage=usage, via_proxy=up)

    if spec.api_style == 'responses':
        from openai import APIError
        client = _openai_client(up)
        content = [{'type': 'input_text', 'text': user_prompt}]
        for (b64, mt) in imgs:
            content.append({'type': 'input_image', 'image_url': f'data:{mt};base64,{b64}'})
        kwargs = {'model': spec.model_id, 'input': [{'role': 'user', 'content': content}],
                  'max_output_tokens': max_tokens}
        if system_prompt:
            kwargs['instructions'] = system_prompt
        eo = _openai_effort(eff)
        if eo:
            kwargs['reasoning'] = {'effort': eo}
        try:
            resp = client.responses.create(timeout=timeout, **kwargs)
        except APIError as e:
            raise LLMError(f'openai-vision: {e}') from None
        text = getattr(resp, 'output_text', '') or ''
        return LLMResponse(text=text, model=spec.model_id, provider=spec.provider,
                           latency_s=time.time() - t0, via_proxy=up)

    if spec.api_style == 'google':
        import base64 as _b64
        from google.genai.types import GenerateContentConfig, Part
        from google.genai import errors as gerr
        client = _google_client(up)
        parts = [Part.from_bytes(data=_b64.b64decode(b64), mime_type=mt) for (b64, mt) in imgs]
        parts.append(user_prompt)
        tc = _google_thinking(eff)
        mtok = max(max_tokens, 16000) if tc is not None else max_tokens
        cfg_kwargs = {'max_output_tokens': mtok, 'temperature': temperature}
        if system_prompt:
            cfg_kwargs['system_instruction'] = system_prompt
        if tc is not None:
            cfg_kwargs['thinking_config'] = tc
        try:
            resp = client.models.generate_content(
                model=spec.model_id, contents=parts, config=GenerateContentConfig(**cfg_kwargs))
        except gerr.APIError as e:
            raise LLMError(f'google-vision: {e}') from None
        text = ''
        cands = getattr(resp, 'candidates', None) or []
        if cands:
            _content = getattr(cands[0], 'content', None)
            for part in (getattr(_content, 'parts', None) or []):
                if not getattr(part, 'thought', False):
                    text += getattr(part, 'text', '') or ''
        um = getattr(resp, 'usage_metadata', None)
        usage = {'prompt_tokens': getattr(um, 'prompt_token_count', None),
                 'output_tokens': getattr(um, 'candidates_token_count', None)} if um else {}
        return LLMResponse(text=text, model=spec.model_id, provider=spec.provider,
                           latency_s=time.time() - t0, usage=usage, via_proxy=up)

    raise LLMError(f'call_vision unsupported for api_style={spec.api_style} ({model_name})')


# ----------------------------------------------------------------------------
# Structured JSON output (appended). schema = a pydantic BaseModel subclass.
# Native structured mode per channel + pydantic validation + repair-retry.
# call()/call_vision() stay unchanged.
# ----------------------------------------------------------------------------
@dataclass
class StructuredResponse:
    parsed: object                 # validated pydantic instance
    model: str = ''
    provider: str = ''
    latency_s: float = 0.0
    usage: dict = field(default_factory=dict)
    raw_text: str = ''
    n_repairs: int = 0
    via_proxy: bool = False


def _strip_fences(t):
    t = (t or '').strip()
    if t.startswith('```'):
        t = t.split('\n', 1)[1] if '\n' in t else t[3:]
        if t.rstrip().endswith('```'):
            t = t.rstrip()[:-3]
    return t.strip()


def _structured_once(spec, user_prompt, system_prompt, schema, max_tokens,
                     temperature, eff, timeout, up):
    """One structured call. Returns (obj_or_none, raw_text, usage, dt).
    obj is a validated `schema` instance only when the SDK parses natively."""
    import json as _json, time as _time
    t0 = _time.time()
    if spec.api_style == 'anthropic':
        from anthropic import APIError
        client = _anthropic_client(up)
        tool = {'name': 'emit', 'description': 'Return the result in this schema.',
                'input_schema': schema.model_json_schema()}
        kwargs = {'model': spec.model_id, 'max_tokens': max(max_tokens, 4000),
                  'messages': [{'role': 'user', 'content': user_prompt}],
                  'tools': [tool], 'tool_choice': {'type': 'tool', 'name': 'emit'}}
        if system_prompt:
            kwargs['system'] = system_prompt
        try:
            msg = client.messages.create(timeout=timeout, **kwargs)
        except APIError as e:
            raise LLMError(f'anthropic-json: {e}') from None
        data = None
        for b in msg.content:
            if getattr(b, 'type', None) == 'tool_use':
                data = b.input
        usage = {'input_tokens': msg.usage.input_tokens, 'output_tokens': msg.usage.output_tokens}
        return None, _json.dumps(data), usage, _time.time() - t0
    if spec.api_style == 'responses':
        from openai import APIError
        client = _openai_client(up)
        kwargs = {'model': spec.model_id,
                  'max_output_tokens': max(max_tokens, 16000) if eff else max_tokens,
                  'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': user_prompt}]}]}
        if system_prompt:
            kwargs['instructions'] = system_prompt
        if eff:
            kwargs['reasoning'] = {'effort': _openai_effort(eff)}
        try:
            resp = client.responses.parse(timeout=timeout, text_format=schema, **kwargs)
        except APIError as e:
            raise LLMError(f'openai-json: {e}') from None
        obj = getattr(resp, 'output_parsed', None)
        u = getattr(resp, 'usage', None)
        usage = {'input_tokens': getattr(u, 'input_tokens', None),
                 'output_tokens': getattr(u, 'output_tokens', None)} if u else {}
        return obj, getattr(resp, 'output_text', '') or '', usage, _time.time() - t0
    if spec.api_style == 'google':
        from google.genai.types import GenerateContentConfig
        from google.genai import errors as gerr
        client = _google_client(up)
        cfg = {'response_mime_type': 'application/json', 'response_schema': schema,
               'max_output_tokens': max(max_tokens, 16000) if eff else max_tokens,
               'temperature': temperature}
        tc = _google_thinking(eff)
        if tc is not None:
            cfg['thinking_config'] = tc
        if system_prompt:
            cfg['system_instruction'] = system_prompt
        try:
            resp = client.models.generate_content(model=spec.model_id, contents=user_prompt,
                                                   config=GenerateContentConfig(**cfg))
        except gerr.APIError as e:
            raise LLMError(f'google-json: {e}') from None
        obj = getattr(resp, 'parsed', None)
        um = getattr(resp, 'usage_metadata', None)
        usage = {'prompt_tokens': getattr(um, 'prompt_token_count', None),
                 'output_tokens': getattr(um, 'candidates_token_count', None)} if um else {}
        raw = ''
        for c in (getattr(resp, 'candidates', None) or []):
            cc = getattr(c, 'content', None)
            for p in (getattr(cc, 'parts', None) or []):
                if not getattr(p, 'thought', False):
                    raw += getattr(p, 'text', '') or ''
        return obj, raw, usage, _time.time() - t0
    from openai import APIError
    client = _openai_client(up, base_url=spec.base_url)
    schema_hint = ('Return ONLY a single JSON object that conforms to this JSON schema '
                   '(no markdown fences, no prose):\n' + _json.dumps(schema.model_json_schema()))
    messages = []
    messages.append({'role': 'system', 'content': (system_prompt + '\n\n' + schema_hint) if system_prompt else schema_hint})
    messages.append({'role': 'user', 'content': user_prompt})
    eh = {'HTTP-Referer': 'https://scinex.local', 'X-Title': 'scinex'} if spec.provider == 'openrouter' else None
    try:
        resp = client.chat.completions.create(model=spec.model_id, messages=messages,
            max_tokens=max(max_tokens, 8000), temperature=temperature, timeout=timeout,
            response_format={'type': 'json_object'}, extra_headers=eh)
    except APIError as e:
        raise LLMError(f'chat-json ({spec.provider}): {e}') from None
    txt = resp.choices[0].message.content or ''
    usage = {}
    if resp.usage:
        usage = {'prompt_tokens': resp.usage.prompt_tokens, 'completion_tokens': resp.usage.completion_tokens}
    return None, txt, usage, _time.time() - t0


def call_json(model_name, user_prompt, schema, *, system_prompt=None,
              max_tokens=4000, temperature=0.0, timeout=300,
              reasoning_effort='medium', use_proxy=None, max_repair=1) -> StructuredResponse:
    """Structured output -> StructuredResponse(.parsed = validated `schema` instance).
    schema: a pydantic BaseModel subclass. Native structured mode per channel
    (anthropic forced-tool / openai json_schema / google response_schema / chat json_object),
    then pydantic validation with up to `max_repair` correction retries."""
    import json as _json
    from pydantic import ValidationError
    if model_name not in MODELS:
        raise LLMError(f'unknown model {model_name!r}')
    spec = MODELS[model_name]
    up = spec.use_proxy if use_proxy is None else use_proxy
    if up and not LLM_PROXY:
        raise LLMError('proxy requested but LLM_PROXY unset')
    eff = reasoning_effort if spec.reasoning else None
    prompt = user_prompt; last_err = None; total = {}; raw = ''; t0 = time.time()
    for attempt in range(max_repair + 1):
        obj, raw, usage, dt = _structured_once(spec, prompt, system_prompt, schema,
                                               max_tokens, temperature, eff, timeout, up)
        for k, v in (usage or {}).items():
            if isinstance(v, (int, float)): total[k] = total.get(k, 0) + v
        try:
            validated = obj if (obj is not None and isinstance(obj, schema)) \
                else schema.model_validate(_json.loads(_strip_fences(raw)))
            return StructuredResponse(parsed=validated, model=spec.model_id, provider=spec.provider,
                                      latency_s=time.time() - t0, usage=total, raw_text=raw,
                                      n_repairs=attempt, via_proxy=up)
        except (ValueError, ValidationError) as e:
            last_err = e
            prompt = (user_prompt + '\n\nYour previous response was invalid for the schema:\n'
                      + str(e)[:300] + '\nReturn ONLY corrected JSON conforming to the schema.')
    raise LLMError(f'call_json: validation failed after {max_repair} repair(s): {str(last_err)[:200]}; raw={raw[:160]!r}')
