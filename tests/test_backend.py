import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from sagate.models.backend import HFBackend  # noqa: E402


class _Tok:
    """Whitespace-separated token ids, so a random tiny model needs no tokenizer files."""
    pad_token_id, eos_token_id = 0, 1

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [int(x) for x in text.split()]}

    def decode(self, ids, skip_special_tokens=False):
        return " ".join(map(str, ids.tolist()))


def test_chunked_prefill_matches_one_shot(monkeypatch):
    """Long agent prompts are prefilled in chunks (T4 OOM fix); greedy output must not change."""
    torch.manual_seed(0)
    cfg = transformers.Qwen3Config(vocab_size=512, hidden_size=64, intermediate_size=128, num_hidden_layers=3,
                                   num_attention_heads=4, num_key_value_heads=2, head_dim=16)
    b = HFBackend.__new__(HFBackend)
    b.torch, b.model, b.tokenizer, b.device = torch, transformers.Qwen3ForCausalLM(cfg).eval(), _Tok(), "cpu"
    b.peft, b.active_adapter = False, None
    prompt = " ".join(str(int(x)) for x in torch.randint(2, 512, (130,), generator=torch.Generator().manual_seed(1)))
    monkeypatch.setattr(HFBackend, "PREFILL_CHUNK", 10 ** 9)
    one_shot = b.generate(prompt, max_new_tokens=20)
    monkeypatch.setattr(HFBackend, "PREFILL_CHUNK", 32)
    assert b.generate(prompt, max_new_tokens=20) == one_shot


def test_completion_loss_matches_full_loss():
    """Training computes logits for the target positions only (T4 memory); the loss must equal HF's full loss."""
    from sagate.train.train_qlora import IGNORE, Collator, completion_loss

    torch.manual_seed(0)
    cfg = transformers.Qwen3Config(vocab_size=300, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                                   num_attention_heads=4, num_key_value_heads=2, head_dim=8)
    model = transformers.Qwen3ForCausalLM(cfg).eval()
    rows = [{"input_ids": list(range(5, 45)), "labels": [IGNORE] * 33 + list(range(38, 45))},
            {"input_ids": list(range(7, 27)), "labels": [IGNORE] * 15 + list(range(22, 27))}]
    for row in rows:
        b = Collator(0)([row])
        full = model(input_ids=b["input_ids"], labels=b["labels"]).loss
        loss, _ = completion_loss(model, dict(b))
        assert torch.allclose(loss, full, atol=1e-5)
    # left-padded batch: same per-token loss as the rows on their own
    b = Collator(0)(rows)
    loss, _ = completion_loss(model, dict(b))
    n = [sum(t != IGNORE for t in r["labels"]) for r in rows]
    singles = [completion_loss(model, dict(Collator(0)([r])))[0] for r in rows]
    assert torch.allclose(loss, (singles[0] * n[0] + singles[1] * n[1]) / sum(n), atol=1e-5)
