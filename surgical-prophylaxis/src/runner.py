"""
CLI runner for surgical prophylaxis module.

Usage:
    python -m src.runner --once            # Run one evaluation cycle
    python -m src.runner --once --dry-run  # Evaluate without creating alerts
    python -m src.runner --once --verbose  # Print detailed output
"""

from .monitor import main

if __name__ == "__main__":
    main()
