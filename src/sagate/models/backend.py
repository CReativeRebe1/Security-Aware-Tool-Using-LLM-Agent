"""HF backend: transformers + bitsandbytes nf4 + PEFT (ARCHITECTURE.md §5.8). One model in memory serves the
agent (adapters disabled) and the gate (adapter on); prompted vs learned gates differ only by the adapter.

torch / transformers are imported lazily so CPU-only code (rules, metrics, case building) never needs them.
"""

from __future__ import annotations

import contextlib
from typing import Sequence


def _lcp(a: Sequence[int], b: Sequence[int]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _set_4bit_compute_dtype(model, dtype) -> int:
    """Pre-quantised checkpoints (unsloth/*-bnb-4bit) save bnb_4bit_compute_dtype=bfloat16, and transformers keeps the
    saved config even when another is passed. T4s have no bf16, so every 4-bit matmul ran emulated (~10x slower
    prefill, NB00). Set the layers' compute dtype and dequantisation dtype directly. Returns #layers changed."""
    try:
        from bitsandbytes.nn import Linear4bit
    except ImportError:
        return 0
    n = 0
    for m in model.modules():
        if isinstance(m, Linear4bit) and m.compute_dtype != dtype:
            m.compute_dtype = dtype
            qs = getattr(m.weight, "quant_state", None)
            if qs is not None:
                qs.dtype = dtype
            n += 1
    return n


class HFBackend:
    def __init__(
        self,
        model_id: str,
        revision: str | None = None,
        compute_dtype: str = "float16",
        cache_dir: str | None = None,
        adapters: dict[str, str] | None = None,
        device_map: str | dict = "auto",
        load_in_4bit: bool | None = None,
        enable_thinking: bool = False,
        max_input_tokens: int | None = None,
    ):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.model_id = model_id
        self.enable_thinking = enable_thinking
        self.max_input_tokens = max_input_tokens
        self.long_inputs = 0
        dtype = getattr(torch, compute_dtype)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision, cache_dir=cache_dir)
        kw = {"revision": revision, "cache_dir": cache_dir, "torch_dtype": dtype}
        if torch.cuda.is_available():
            kw["device_map"] = device_map
            if load_in_4bit is None:
                load_in_4bit = "bnb-4bit" not in model_id.lower() and "awq" not in model_id.lower() and \
                    any(s in model_id.lower() for s in ("8b", "14b", "32b"))
            if load_in_4bit:
                from transformers import BitsAndBytesConfig
                kw["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=dtype,
                    bnb_4bit_use_double_quant=True)
        else:
            kw["torch_dtype"] = torch.float32       # CPU smoke tests with small models
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
        if torch.cuda.is_available():
            self.n_recast = _set_4bit_compute_dtype(self.model, dtype)
        self.model.eval()
        self.device = next(self.model.parameters()).device
        self.peft = False
        self.active_adapter: str | None = None
        for name, path in (adapters or {}).items():
            self.load_adapter(name, path)
        self._reset_cache()

    # --- adapters -------------------------------------------------------------------------------------
    def load_adapter(self, name: str, path: str) -> None:
        if not self.peft:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, path, adapter_name=name)
            self.peft = True
        else:
            self.model.load_adapter(path, adapter_name=name)
        self.model.eval()
        self._reset_cache()

    def use_adapter(self, name: str | None) -> None:
        if name == self.active_adapter:
            return
        if name is not None:
            if not self.peft or name not in self.model.peft_config:
                raise KeyError(f"adapter {name!r} not loaded")
            self.model.set_adapter(name)
        self.active_adapter = name
        self._reset_cache()

    def _adapter_ctx(self):
        if self.peft and self.active_adapter is None:
            return self.model.disable_adapter()
        return contextlib.nullcontext()

    # --- text ---------------------------------------------------------------------------------------------
    def chat_prefix(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        return self.tokenizer.apply_chat_template(
            messages, tools=tools, tokenize=False, add_generation_prompt=True,
            enable_thinking=self.enable_thinking)

    def encode(self, text: str) -> list[int]:
        return self.tokenizer(text, add_special_tokens=False)["input_ids"]

    # --- scoring with KV-cache reuse ---------------------------------------------------------------------
    def _reset_cache(self) -> None:
        self._cache = None
        self._cache_ids: list[int] = []
        self._last_logits = None

    def _forward(self, ids: list[int]):
        from transformers import DynamicCache

        if self._cache is None:
            self._cache = DynamicCache()
        t = self.torch.tensor([ids], device=self.device)
        with self._adapter_ctx():
            out = self.model(input_ids=t, past_key_values=self._cache, use_cache=True)
        self._cache = out.past_key_values
        return out.logits[0].float()

    def _advance_to(self, prefix_ids: list[int]) -> None:
        """Make the cache hold exactly prefix_ids, with logits of its last position in _last_logits."""
        if self._cache_ids == prefix_ids and self._last_logits is not None:
            return
        keep = min(_lcp(self._cache_ids, prefix_ids), len(prefix_ids) - 1)
        if self._cache is not None and keep > 0:
            self._cache.crop(keep)
        else:
            self._reset_cache()
            keep = 0
        logits = self._forward(prefix_ids[keep:])
        self._cache_ids = list(prefix_ids)
        self._last_logits = logits[-1]

    def score(self, prefix: str, continuations: Sequence[str]) -> list[float]:
        """Sum log P(continuation | prefix) per continuation, tokenising prefix+continuation jointly."""
        torch = self.torch
        full = [self.encode(prefix + c) for c in continuations]
        common = min(_lcp(full[0], f) for f in full)
        common = min(common, min(len(f) for f in full) - 1)
        if self.max_input_tokens and common > self.max_input_tokens:
            self.long_inputs += 1
        with torch.inference_mode():
            self._advance_to(full[0][:common])
            base_lp = torch.log_softmax(self._last_logits, -1)
            scores = []
            for f in full:
                tail = f[common:]
                s = float(base_lp[tail[0]])
                if len(tail) > 1:
                    logits = self._forward(tail[:-1])
                    lp = torch.log_softmax(logits, -1)
                    s += float(lp[torch.arange(len(tail) - 1), torch.tensor(tail[1:], device=lp.device)].sum())
                    self._cache.crop(common)
                scores.append(s)
        return scores

    # --- generation -----------------------------------------------------------------------------------
    PREFILL_CHUNK = 1024

    def _prefill(self, ids: list[int]):
        """KV cache for `ids`, built in PREFILL_CHUNK pieces. On a T4, SDPA has no flash kernel and materialises the
        full heads x L x L attention matrix: one-shot prefill of a 12-16k-token agent conversation needs ~16 GB
        (NB01 OOM on workspace tasks that read whole files). Chunks keep it at heads x chunk x L."""
        from transformers import DynamicCache

        cache = DynamicCache()
        for i in range(0, len(ids), self.PREFILL_CHUNK):
            t = self.torch.tensor([ids[i:i + self.PREFILL_CHUNK]], device=self.device)
            self.model(input_ids=t, past_key_values=cache, use_cache=True, logits_to_keep=1)
        return cache

    def generate(self, prefix: str, max_new_tokens: int = 512, stop: Sequence[str] = ()) -> str:
        torch = self.torch
        raw = self.encode(prefix)
        ids = torch.tensor([raw], device=self.device)
        with torch.inference_mode(), self._adapter_ctx():
            kw = {"past_key_values": self._prefill(raw[:-1])} if len(raw) > self.PREFILL_CHUNK else {}
            out = self.model.generate(
                input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=max_new_tokens,
                do_sample=False, temperature=None, top_p=None, top_k=None,
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id, **kw)
        text = self.tokenizer.decode(out[0, ids.shape[1]:], skip_special_tokens=False)
        for tok in ("<|im_end|>", "<|endoftext|>"):
            text = text.split(tok)[0]
        for s in stop:
            if s in text:
                text = text.split(s)[0] + s
        return text

    def generate_chat(self, messages: list[dict], tools: list[dict] | None = None, max_new_tokens: int = 512) -> str:
        return self.generate(self.chat_prefix(messages, tools=tools), max_new_tokens=max_new_tokens)


def backend_from_config(cfg, adapters: dict[str, str] | None = None, model_id: str | None = None) -> HFBackend:
    m = cfg["model"]
    hf_cache = cfg.path("hf_cache")
    return HFBackend(
        model_id=model_id or m["base_id"],
        revision=m.get("revision"),
        compute_dtype=m.get("compute_dtype", "float16"),
        cache_dir=str(hf_cache) if hf_cache else None,
        adapters=adapters,
        enable_thinking=m.get("enable_thinking", False),
        max_input_tokens=m.get("max_input_tokens"),
    )
