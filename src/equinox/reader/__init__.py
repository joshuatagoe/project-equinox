"""The term reader (feat-10; D56-D58): a model reads markets into contract terms, code decides.

The brief allows matching that is "rule-based, heuristic, AI-assisted, or hybrid"; this is the
hybrid. For markets that no parser can read, a model fills in the same terms shape the Fed parsers
fill (`prompt.py`). Deterministic checks reject any reading the venue's own text doesn't support
(`checks.py`), and the terms rules that decide parser-read pairs decide these too (`run.py`). The
model never says whether two markets are the same bet. `client.py` holds the key, the API call
and the cache; `evals.py` scores the model against gold labels.
"""
