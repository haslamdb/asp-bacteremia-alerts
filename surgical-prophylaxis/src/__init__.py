"""
AEGIS Surgical Antimicrobial Prophylaxis Module

This module provides real-time monitoring and alerting for surgical antimicrobial
prophylaxis compliance. It evaluates adherence to evidence-based guidelines including:

- Indication appropriateness
- Agent selection
- Timing (within 60 min of incision)
- Weight-based dosing
- Intraoperative redosing
- Timely discontinuation (≤24h, ≤48h for cardiac)

The module integrates with the AEGIS alert store to generate SURGICAL_PROPHYLAXIS
alerts for non-compliant cases.
"""

__version__ = "1.0.0"
