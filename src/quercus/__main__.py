"""Permite invocar `python -m quercus` diretamente."""

import sys

from quercus.main import main

if __name__ == "__main__":
    sys.exit(main())
