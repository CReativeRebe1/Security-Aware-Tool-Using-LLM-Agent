"""Hugging Face backend: transformers + bitsandbytes nf4 + PEFT.

One model in memory serves the task agent (adapters disabled) and every LLM gate (prompted = no adapter, learned =
a LoRA adapter), so prompted and learned gates differ only by the adapter. torch/transformers are imported
lazily: the CPU-only parts of the package never need them.

Scoring reuses the KV cache: consecutive gate prompts share the system prompt, and the candidates of one field
share everything before the value, so a gate decision costs about one prefill plus a few short forward passes.
"""

from __future__ import annotations

import contextlib
from typing import Sequence


def common_prefix(a: Sequence[int], b: Sequence[int]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class HFBackend:
    def __init__(self, model_id: str, cache_dir: str | None = None, compute_dtype: str = "float16",
                 enable_thinking: bool = False, max_input_tokens: int | None = None,
                 adapters: dict[str, str] | None = None, device_map: str | dict = "auto"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.model_id = model_id
        self.enable_thinking = enable_thinking
        self.max_input_tokens = max_input_tokens
        self.long_inputs = 0
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
        kw: dict = {"cache_dir": cache_dir}
        if torch.cuda.is_available():
            kw["torch_dtype"] = getattr(torch, compute_dtype)
            kw["device_map"] = device_map
            # pre-quantised checkpoints carry their own quantization_config; quantise large fp checkpoints on load
            if "bnb" not in model_id.lower() and any(s in model_id.lower() for s in ("8b", "14b", "32b")):
                from transformers import BitsAndBytesConfig
                kw["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=getattr(torch, compute_dtype))
        else:
            kw["torch_dtype"] = torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
        self.model.eval()
        self.device = next(self.model.parameters()).device
        self.has_peft = False
        self.active_adapter: str | None = None
        for name, path in (adapters or {}).items():
            self.load_adapter(name, path)
        self._reset()

    # --- adapters --------------------------------------------------------------------------------------------
    def load_adapter(self, name: str, path: str) -> None:
        if not self.has_peft:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, path, adapter_name=name)
            self.has_peft = True
        else:
            self.model.load_adapter(path, adapter_name=name)
        self.model.eval()
        self._reset()

    def use_adapter(self, name: str | None) -> None:
        if name == self.active_adapter:
            return
        if name is not None:
            if not self.has_peft or name not in self.model.peft_config:
                raise KeyError(f"adapter {name!r} is not loaded")
            self.model.set_adapter(name)
        self.active_adapter = name
        self._reset()

    def _adapter_off(self):
        if self.has_peft and self.active_adapter is None:
            return self.model.disable_adapter()
        return contextlib.nullcontext()

    # --- text ------------------------------------------------------------------------------------------------
    def chat_prefix(self, messages: list[dict], tools: list[dict] | None = None) -> str:
        return self.tokenizer.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=True,
                                                  enable_thinking=self.enable_thinking)

    def encode(self, text: str) -> list[int]:
        return self.tokenizer(text, add_special_tokens=False)["input_ids"]

    # --- scoring with KV-cache reuse ---------------------------------------------------------------------------
    def _reset(self) -> None:
        self._cache = None
        self._ids: list[int] = []
        self._last = None

    def _forward(self, ids: list[int]):
        from transformers import DynamicCache

        if self._cache is None:
            self._cache = DynamicCache()
        x = self.torch.tensor([ids], device=self.device)
        with self._adapter_off():
            out = self.model(input_ids=x, past_key_values=self._cache, use_cache=True)
        self._cache = out.past_key_values
        return out.logits[0].float()

    def _hold(self, ids: list[int]) -> None:
        """Make the cache hold exactly `ids`, with the logits of its last position in self._last."""
        if ids == self._ids and self._last is not None:
            return
        keep = min(common_prefix(self._ids, ids), len(ids) - 1)
        if self._cache is not None and keep > 0:
            self._cache.crop(keep)
        else:
            self._reset()
            keep = 0
        self._last = self._forward(ids[keep:])[-1]
        self._ids = list(ids)

    def score(self, prefix: str, continuations: Sequence[str]) -> list[float]:
        """log P(continuation | prefix) for each continuation. Prefix and continuation are tokenised together, and
        scoring starts where the candidates' token sequences diverge, so merges at the boundary are handled."""
        torch = self.torch
        full = [self.encode(prefix + c) for c in continuations]
        shared = min(common_prefix(full[0], f) for f in full)
        shared = min(shared, min(len(f) for f in full) - 1)
        if self.max_input_tokens and shared > self.max_input_tokens:
            self.long_inputs += 1
        out = []
        with torch.inference_mode():
            self._hold(full[0][:shared])
            base = torch.log_softmax(self._last, -1)
            for f in full:
                tail = f[shared:]
                s = float(base[tail[0]])
                if len(tail) > 1:
                    lp = torch.log_softmax(self._forward(tail[:-1]), -1)
                    idx = torch.tensor(tail[1:], device=lp.device)
                    s += float(lp[torch.arange(len(tail) - 1, device=lp.device), idx].sum())
                    self._cache.crop(shared)
                out.append(s)
        return out

    # --- generation ------------------------------------------------------------------------------------------
    def generate(self, prefix: str, max_new_tokens: int = 512, stop: Sequence[str] = ()) -> str:
        torch = self.torch
        ids = torch.tensor([self.encode(prefix)], device=self.device)
        with torch.inference_mode(), self._adapter_off():
            gen = self.model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                                      max_new_tokens=max_new_tokens, do_sample=False, temperature=None, top_p=None,
                                      top_k=None, pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
        text = self.tokenizer.decode(gen[0, ids.shape[1]:], skip_special_tokens=False)
        for end in ("<|im_end|>", "<|endoftext|>"):
            text = text.split(end)[0]
        for s in stop:
            if s in text:
                text = text.split(s)[0] + s
        return text

    def generate_chat(self, messages: list[dict], tools: list[dict] | None = None, max_new_tokens: int = 512) -> str:
        return self.generate(self.chat_prefix(messages, tools=tools), max_new_tokens=max_new_tokens)


def load_backend(cfg, model_id: str | None = None, adapters: dict[str, str] | None = None) -> HFBackend:
    m = cfg["model"]
    cache = cfg.path("hf_cache")
    return HFBackend(model_id or m["base_id"], cache_dir=str(cache) if cache else None,
                     compute_dtype=m.get("compute_dtype", "float16"), enable_thinking=m.get("enable_thinking", False),
                     max_input_tokens=m.get("max_input_tokens"), adapters=adapters)
