"""Entry point so that ``python main.py <cmd>`` also works."""

from valutatrade_hub.cli.interface import main

if __name__ == "__main__":
    raise SystemExit(main())
