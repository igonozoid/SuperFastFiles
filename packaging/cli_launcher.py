"""Ponto de entrada da linha de comando `sff` (executável de console, PyInstaller)."""
import sys

from superfastfiles.cli import main

if __name__ == "__main__":
    sys.exit(main())
