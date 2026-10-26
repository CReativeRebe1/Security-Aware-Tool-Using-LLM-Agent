"""secgate: provenance- and authority-aware runtime security gate for tool-using LLM agents."""

import os

# The package uses PyTorch only; keep transformers from importing a TensorFlow install that may be present.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

__version__ = "0.1.0"
