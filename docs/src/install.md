# Install

```bash
pip install exfer
```

That's it. `httpx` is the only runtime dependency.

## Requirements

- Python 3.9 – 3.13
- A running `exfer-walletd` (`>= 0.4.3`). If you don't have one yet, see
  the [walletd quick start](https://exfer-stack.github.io/exfer-walletd/quick-start.html).

## Verify

```python
import exfer
print(exfer.__version__)
```

Then probe a running walletd:

```python
from exfer import Client

with Client.from_datadir() as c:        # reads ~/.exfer-walletd/token
    print(c.healthz())                  # → True
```

## Optional: dev install

If you're hacking on the SDK itself:

```bash
git clone https://github.com/exfer-stack/exfer-py
cd exfer-py
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Next: [Quick start](./quick-start.md).
