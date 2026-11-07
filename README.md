# multi-tenant-kit

[![PyPI version](https://img.shields.io/pypi/v/trysac-multi-tenant-kit)](https://pypi.org/project/trysac-multi-tenant-kit/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-multi-tenant-kit)](LICENSE)
[![CI](https://github.com/Trysac/u144-multi-tenant-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u144-multi-tenant-kit/actions/workflows/ci.yml)

Row-level multi-tenancy helpers: contextvar tenant scope, exact Postgres RLS policy SQL, transaction-local tenant binding and a WSGI tenant middleware

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-multi-tenant-kit
# or
uv add trysac-multi-tenant-kit
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import multi_tenant_kit

# normalize() trims surrounding whitespace and lower-cases the text.
print(multi_tenant_kit.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    multi_tenant_kit.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
