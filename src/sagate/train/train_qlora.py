"""QLoRA SFT for the learned gates (ARCHITECTURE.md §6): one adapter per condition, resumable.

LoRA r=16, alpha=32, dropout 0.05 on all linear projections of the nf4 base; fp16 compute (T4); loss on the
assistant JSON only; max length 2,048 (longer examples are dropped and counted); batch 1 x grad-accum 16;
lr 2e-4 cosine; 2 epochs; gradient checkpointing; a checkpoint every 100 steps, resumed from the latest one.

The prompt is the gate's own chat prefix (models.backend.HFBackend.chat_prefix: Qwen3 template, thinking off)
and the target is the decoder's JSON skeleton, tokenised jointly exactly as EnumDecoder scores it. The adapter is
saved as a plain PEFT adapter in <out>/adapters/<condition>, so inference never depends on the trainer.
Trainer: transformers Trainer + PEFT (default) or Unsloth (`train.trainer: unsloth`, same hyper-parameters).

  python -m sagate.train.train_qlora --condition b5_qlora_4way --sft outputs/sft/b5_qlora_4way.jsonl
  python -m sagate.train.train_qlora ... --model-id Qwen/Qwen3-0.6B --max-steps 20      # smoke test
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from ..config import load_condition, load_config
from ..data.loaders import read_jsonl
from ..manifest import write_manifest
from ..models.backend import _lcp, _set_4bit_compute_dtype

IGNORE = -100


def end_token(tok) -> str:
    return "<|im_end|>" if "<|im_end|>" in tok.get_vocab() else tok.eos_token


def tokenize_rows(tok, rows: list[dict], max_length: int, enable_thinking: bool = False) -> tuple[list[dict], dict]:
    """[{input_ids, labels}] with the prompt masked out; examples over max_length are dropped (and counted)."""
    end = end_token(tok)
    out, lengths, dropped = [], [], []
    for r in rows:
        prefix = tok.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=True,
                                         enable_thinking=enable_thinking)
        ids = tok(prefix + r["target"] + end, add_special_tokens=False)["input_ids"]
        n_prompt = _lcp(tok(prefix, add_special_tokens=False)["input_ids"], ids)
        lengths.append(len(ids))
        if len(ids) > max_length:
            dropped.append(r["case_id"])
            continue
        out.append({"input_ids": ids, "labels": [IGNORE] * n_prompt + ids[n_prompt:]})
    stats = {"examples": len(rows), "kept": len(out), "dropped_over_max_length": len(dropped),
             "dropped_ids": dropped[:50], "median_tokens": statistics.median(lengths) if lengths else 0,
             "max_tokens": max(lengths, default=0), "train_tokens": sum(len(x["input_ids"]) for x in out)}
    return out, stats


class Collator:
    """Left padding, so every row's target sits at the end and only the last `logits_to_keep` positions need
    logits: at 3.8k tokens the full-vocabulary logits (+ fp32 upcast and gradient) cost ~6 GB, the 30-token
    target a few MB."""

    def __init__(self, pad_id: int):
        self.pad_id = pad_id

    def __call__(self, batch: list[dict]) -> dict:
        import torch

        n = max(len(b["input_ids"]) for b in batch)
        pad = [n - len(b["input_ids"]) for b in batch]
        ids = [[self.pad_id] * p + b["input_ids"] for p, b in zip(pad, batch)]
        labels = [[IGNORE] * p + b["labels"] for p, b in zip(pad, batch)]
        mask = [[0] * p + [1] * len(b["input_ids"]) for p, b in zip(pad, batch)]
        keep = max(sum(t != IGNORE for t in b["labels"]) for b in batch)
        pos = [[0] * p + list(range(len(b["input_ids"]))) for p, b in zip(pad, batch)]   # RoPE ignores padding
        return {"input_ids": torch.tensor(ids), "labels": torch.tensor(labels), "attention_mask": torch.tensor(mask),
                "position_ids": torch.tensor(pos), "logits_to_keep": torch.tensor(keep)}


def completion_loss(model, inputs: dict, num_items_in_batch=None):
    """Causal-LM loss on the target tokens only, computing logits for the last `logits_to_keep` + 1 positions."""
    import torch

    labels = inputs.pop("labels")
    keep = int(inputs.pop("logits_to_keep"))
    out = model(**inputs, logits_to_keep=keep + 1, use_cache=False)
    logits = out.logits[:, :-1].float()                 # position j predicts token j + 1
    tgt = labels[:, -keep:].to(logits.device)
    loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), tgt.reshape(-1),
                                             ignore_index=IGNORE, reduction="sum")
    n = num_items_in_batch if num_items_in_batch is not None else (tgt != IGNORE).sum()
    return loss / n, out


def _quantise(model_id: str, load_in_4bit: bool | None, cuda: bool) -> bool:
    """Same rule as HFBackend: pre-quantised checkpoints load as 4-bit; large fp16 checkpoints are quantised."""
    if not cuda:
        return False
    if load_in_4bit is not None:
        return load_in_4bit
    m = model_id.lower()
    return "bnb-4bit" in m or any(s in m for s in ("8b", "14b", "32b"))


def load_peft_model(model_id: str, tcfg: dict, mcfg: dict, cache_dir: str | None, seed: int,
                    load_in_4bit: bool | None = None, trainer: str = "peft"):
    import torch

    dtype = getattr(torch, mcfg.get("compute_dtype", "float16"))
    lora = tcfg["lora"]
    cuda = torch.cuda.is_available()
    if trainer == "unsloth":
        from unsloth import FastLanguageModel

        model, tok = FastLanguageModel.from_pretrained(model_name=model_id, max_seq_length=tcfg["max_length"],
                                                       dtype=dtype, load_in_4bit=True, cache_dir=cache_dir)
        model = FastLanguageModel.get_peft_model(
            model, r=lora["r"], lora_alpha=lora["alpha"], lora_dropout=lora["dropout"],
            target_modules=lora["target_modules"], bias="none", use_gradient_checkpointing="unsloth",
            random_state=seed)
        return model, tok

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(model_id, revision=mcfg.get("revision"), cache_dir=cache_dir)
    q = _quantise(model_id, load_in_4bit, cuda)
    kw = {"revision": mcfg.get("revision"), "cache_dir": cache_dir,
          "torch_dtype": dtype if cuda else torch.float32}
    if cuda:
        kw["device_map"] = {"": 0}
        if q and "bnb-4bit" not in model_id.lower():
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=dtype,
                                                           bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
    if cuda:
        _set_4bit_compute_dtype(model, dtype)        # pre-quantised checkpoints save bf16 compute (no bf16 on T4)
    model.config.use_cache = False
    if q:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                                gradient_checkpointing_kwargs={"use_reentrant": False})
    else:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=lora["r"], lora_alpha=lora["alpha"], lora_dropout=lora["dropout"],
                                             target_modules=lora["target_modules"], bias="none",
                                             task_type="CAUSAL_LM"))
    return model, tok


def train(condition: str, sft_path: str, cfg_path: str | None = None, out: str | None = None,
          model_id: str | None = None, max_steps: int | None = None, load_in_4bit: bool | None = None,
          trainer: str | None = None) -> Path:
    cfg = load_config(cfg_path)
    tcfg, mcfg = cfg["train"], cfg["model"]
    trainer = trainer or tcfg.get("trainer", "peft")
    if trainer == "unsloth":
        import unsloth  # noqa: F401  (must be imported before transformers to patch it)
    import torch
    from torch.utils.data import Dataset
    from transformers import Trainer, TrainingArguments, set_seed
    from transformers.trainer_utils import get_last_checkpoint

    cond = load_condition(condition)
    model_id = model_id or mcfg["base_id"]
    root = Path(out) if out else cfg.outputs_dir
    adapter_dir = root / "adapters" / cond.name
    ckpt_dir = root / "checkpoints" / cond.name
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    set_seed(cfg["seed"])
    hf_cache = cfg.path("hf_cache")

    rows = [r for r in read_jsonl(sft_path)]
    bad = {r["condition"] for r in rows} - {cond.name}
    if bad:
        raise ValueError(f"{sft_path} holds SFT rows for {sorted(bad)}, not {cond.name}")
    model, tok = load_peft_model(model_id, tcfg, mcfg, str(hf_cache) if hf_cache else None, cfg["seed"],
                                 load_in_4bit, trainer)
    examples, stats = tokenize_rows(tok, rows, tcfg["max_length"], mcfg.get("enable_thinking", False))
    print(json.dumps({k: v for k, v in stats.items() if k != "dropped_ids"}), flush=True)

    class _DS(Dataset):
        def __len__(self):
            return len(examples)

        def __getitem__(self, i):
            return examples[i]

    cuda = torch.cuda.is_available()
    args = TrainingArguments(
        output_dir=str(ckpt_dir),
        per_device_train_batch_size=tcfg["batch_size"],
        gradient_accumulation_steps=tcfg["grad_accum"],
        learning_rate=tcfg["lr"],
        lr_scheduler_type=tcfg.get("scheduler", "cosine"),
        warmup_ratio=tcfg.get("warmup_ratio", 0.03),
        num_train_epochs=tcfg["epochs"],
        max_steps=max_steps or -1,
        max_grad_norm=tcfg.get("max_grad_norm", 0.3),
        fp16=cuda and mcfg.get("compute_dtype", "float16") == "float16",
        bf16=cuda and mcfg.get("compute_dtype") == "bfloat16",
        gradient_checkpointing=trainer != "unsloth",
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=tcfg.get("logging_steps", 10),
        save_steps=tcfg.get("save_steps", 100),
        save_total_limit=2,
        report_to=[],
        seed=cfg["seed"],
        remove_unused_columns=False,
        dataloader_num_workers=0,
    )
    class _Trainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            loss, out = completion_loss(model, dict(inputs), num_items_in_batch)
            return (loss, out) if return_outputs else loss

    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    tr = _Trainer(model=model, args=args, train_dataset=_DS(), data_collator=Collator(pad))
    last = get_last_checkpoint(str(ckpt_dir))
    if last:
        print(f"resuming from {last}", flush=True)
    t0 = time.time()
    result = tr.train(resume_from_checkpoint=last)
    model.save_pretrained(str(adapter_dir))
    summary = {"condition": cond.name, "model_id": model_id, "trainer": trainer, "sft": str(sft_path),
               **stats, "train_loss": result.training_loss, "global_step": result.global_step,
               "runtime_s": time.time() - t0, "resumed_from": last, "log_history": tr.state.log_history}
    (adapter_dir / "train_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    write_manifest(adapter_dir / "manifest.json", cfg,
                   extra={"stage": "train_qlora", "condition": cond.__dict__, "model_id": model_id,
                          "trainer": trainer})
    print(f"{cond.name}: loss {result.training_loss:.4f} after {result.global_step} steps "
          f"({(time.time() - t0) / 60:.1f} min) -> {adapter_dir}", flush=True)
    return adapter_dir


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--condition", required=True)
    ap.add_argument("--sft", required=True, help="outputs/sft/<condition>.jsonl from train.build_sft")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None, help="root for adapters/ and checkpoints/ (default: <outputs>)")
    ap.add_argument("--model-id", default=None, help="override model.base_id (small model for smoke tests)")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--load-in-4bit", action="store_true", default=None, help="force nf4 (e.g. small-model smoke)")
    ap.add_argument("--trainer", choices=["peft", "unsloth"], default=None)
    a = ap.parse_args(argv)
    train(a.condition, a.sft, a.config, a.out, a.model_id, a.max_steps, a.load_in_4bit, a.trainer)


if __name__ == "__main__":
    main()
