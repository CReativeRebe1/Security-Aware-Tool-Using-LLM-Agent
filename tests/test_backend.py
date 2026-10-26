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
