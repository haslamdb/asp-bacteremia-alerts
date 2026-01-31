# HAI Classification: Institutional Bias Mitigation

This document describes AEGIS's approach to mitigating institutional bias in HAI classification training and its implications for multi-site deployment.

## The Problem

Different hospitals may interpret NHSN criteria differently:
- Some are "generous" in calling secondary BSI based on clinical diagnosis alone
- Some accept less-documented MBI-LCBI criteria
- Some have institutional norms that diverge from literal NHSN interpretation

If we train on CCHMC's historical IP decisions, we risk encoding CCHMC-specific interpretations that may not transfer to other institutions.

## Architectural Protection

AEGIS is designed to separate **fact extraction** from **classification**:

```
┌─────────────────────────────────────────────────────────────────┐
│  SUBJECTIVE (varies by institution)     OBJECTIVE (NHSN rules)  │
├─────────────────────────────────────────────────────────────────┤
│  "Is this really MBI-LCBI?"             "Does this MEET the     │
│  "Should we call this secondary?"        NHSN criteria for      │
│                   ↓                       MBI-LCBI?"             │
│            IP judgment                          ↓                │
│            (trainable bias)              Deterministic rules     │
│                                          (auditable, portable)   │
└─────────────────────────────────────────────────────────────────┘
```

### What We Train

The LLM is trained to **extract facts**, not make classifications:
- "Is mucositis documented?" → Yes, Grade 2 (per oncology note 01/14)
- "Is an alternate source mentioned?" → Yes, UTI (per ID consult)
- "Does the team think this is a contaminant?" → Notes suggest treating

### What We Don't Train

The LLM is **never** asked to output:
- "Is this a CLABSI?" → Classification is done by rules engine
- "MBI-LCBI: Yes" → Rules engine applies NHSN criteria

This separation means the core extraction model is portable. The rules engine can be configured for different institutional norms.

## Implemented Mitigations

### 1. Strictness Levels (IMPLEMENTED)

The rules engine supports configurable strictness:

```python
from hai_src.rules.clabsi_engine import CLABSIRulesEngine, StrictnessLevel

# For CDC benchmarking / external validation
engine = CLABSIRulesEngine(strictness=StrictnessLevel.NHSN_STRICT)

# For daily operations (default)
engine = CLABSIRulesEngine(strictness=StrictnessLevel.NHSN_MODERATE)

# To match historical CCHMC practice
engine = CLABSIRulesEngine(strictness=StrictnessLevel.PERMISSIVE)
```

| Strictness | Secondary BSI | MBI-LCBI | Use Case |
|------------|---------------|----------|----------|
| `nhsn_strict` | Culture-confirmed only | DEFINITE MBI docs | CDC comparison, external audit |
| `nhsn_moderate` | DEFINITE/PROBABLE with organism match | DEFINITE/PROBABLE | Daily operations |
| `permissive` | Clinical diagnosis accepted | POSSIBLE accepted | Match historical IP practice |

### 2. Discrepancy Logging (IMPLEMENTED)

When AEGIS classification differs from historic IP classification:

```python
from hai_src.rules.discrepancy_logger import check_and_log_discrepancy

# After classification
check_and_log_discrepancy(
    candidate_id="abc123",
    aegis_classification=result.classification.value,
    historic_ip_classification="secondary_bsi",  # What IP called it
    aegis_reasoning=result.reasoning,
    strictness_level="nhsn_moderate",
)
```

Discrepancies are logged with:
- **type**: upgrade (AEGIS stricter), downgrade (AEGIS more lenient), reclassify
- **reasoning**: Why AEGIS made its decision
- **nhsn_criteria_applied**: Which specific NHSN rules were applied

Statistics available:
```python
from hai_src.rules.discrepancy_logger import DiscrepancyLogger

logger = DiscrepancyLogger()
stats = logger.get_discrepancy_stats()
# {
#   "total_discrepancies": 47,
#   "by_type": {"upgrade": 12, "downgrade": 28, "reclassify": 7},
#   "upgrade_rate_pct": 25.5,
#   "downgrade_rate_pct": 59.6,
# }
```

## Future Work

### TODO: Gold Standard Dataset

Create a separate dataset of 50-100 cases adjudicated strictly by NHSN criteria:

1. **Select complex cases**: MBI-LCBI candidates, borderline secondary BSI, etc.
2. **Apply literal NHSN criteria**: Follow CDC guidance documents exactly
3. **Document discrepancies**: Where CCHMC IP called it differently, note why
4. **Use for validation**: Test rules engine against this gold standard

Schema suggestion:
```python
@dataclass
class GoldStandardCase:
    case_id: str
    patient_mrn: str
    culture_date: date
    organism: str

    # Historic classification
    cchmc_ip_classification: str  # What CCHMC IP called it
    cchmc_reviewer: str
    cchmc_review_date: date

    # Gold standard classification
    nhsn_strict_classification: str  # What literal NHSN says
    nhsn_criteria_applied: list[str]  # ["LCBI-1", "MBI-LCBI-2a"]

    # Discrepancy analysis (if different)
    discrepancy_reason: str | None
    # e.g., "UTI was not microbiologically confirmed per NHSN secondary BSI criteria"
```

### TODO: CDC Benchmark Testing

Validate the rules engine against published CDC/NHSN materials:

1. **Find CDC case studies**: NHSN training materials, audit examples
2. **Encode as test cases**: Patient scenario → expected classification
3. **Run AEGIS in `nhsn_strict` mode**: Compare outputs
4. **Document any mismatches**: May indicate rules engine bugs or CDC interpretation issues

Example test structure:
```python
@pytest.mark.parametrize("scenario,expected", [
    # From CDC NHSN training module
    ("cdc_clabsi_case_study_1", CLABSIClassification.CLABSI),
    ("cdc_mbi_lcbi_example_3", CLABSIClassification.MBI_LCBI),
    ("cdc_secondary_bsi_example_2", CLABSIClassification.SECONDARY_BSI),
])
def test_cdc_benchmark(scenario, expected):
    extraction, structured_data = load_cdc_scenario(scenario)
    result = classify_clabsi(
        extraction,
        structured_data,
        strictness=StrictnessLevel.NHSN_STRICT,
    )
    assert result.classification == expected
```

## Commercialization Implications

When deploying AEGIS to other institutions:

```
┌─────────────────────────────────────────────────────────────────┐
│                    AEGIS Deployment Model                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Core (portable):                                                │
│  ├── Extraction model (trained on clinical facts)               │
│  ├── NHSN rules engine (deterministic, auditable)               │
│  └── Benchmarked against CDC validation                         │
│                                                                  │
│  Configurable (per institution):                                 │
│  ├── Strictness level                                           │
│  ├── Local guidelines integration                               │
│  └── Organism/threshold overrides                               │
│                                                                  │
│  Optional fine-tuning:                                           │
│  └── Site-specific extraction model for local note formats      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

Key selling points:
1. **Portable core**: Extraction model works across institutions
2. **Configurable strictness**: Match their practice or audit to CDC standard
3. **Auditable**: Every classification has documented reasoning
4. **Calibratable**: Discrepancy logs show where AEGIS differs from their practice

## References

- NHSN Patient Safety Component Manual (2024), Chapter 4
- CDC Bloodstream Infection (BSI) Surveillance Training
- NHSN CLABSI Case Studies and FAQ
- Chua KP, et al. (2019). Classification of ICD-10-coded antibiotic prescribing

---

*Last updated: January 2026*
