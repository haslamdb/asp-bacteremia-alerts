# LLM Optimization TODO

## Problem
- Current: ~85 seconds per note with llama3.3:70b
- Real HAI cases have 20-30 notes = 28-42 minutes per case
- Antibiotic indications: 100+ orders/day = impractical for LLM

## Action Items

### 1. HAI Detection - Optimize LLM Usage
- [ ] **Concatenate notes into single prompt** instead of N separate LLM calls
- [ ] **Pre-filter note types** - only send relevant notes (progress notes, ID consults, not dietary/PT)
- [ ] **Truncate intelligently** - extract sections mentioning lines, cultures, infections
- [ ] **Consider batch processing** - run classification as nightly job, not real-time

### 2. Antibiotic Indications - Skip LLM
- [ ] Keep ICD-10 Chua classification as primary (instant)
- [ ] Remove or disable LLM extraction for indication monitoring
- [ ] Optional: LLM fallback only for "N" or "U" cases flagged for human review

### 3. Guideline Adherence - Tiered LLM Approach
Currently uses llama3.3:70b for clinical impression extraction (febrile infant risk stratification).

- [ ] **Switch to qwen2.5:7b for triage** - faster initial pass for clinical appearance
- [ ] **Tiered approach like HAI** - use 7B for quick classification, escalate to 70B only when needed
- [ ] **Add training data capture** - update review system to collect expert corrections
- [ ] **Capture override reasons** - when clinician disagrees with LLM appearance assessment
- [ ] **Track extraction errors** - did model miss key findings (lethargy, mottling, poor feeding)?

### 4. Module LLM Strategy

| Module | Primary Method | LLM Role |
|--------|---------------|----------|
| HAI Detection | LLM extraction | **Primary** (tiered: 7B triage, 70B full) |
| Antibiotic Indications | ICD-10 + LLM syndrome | **Primary** (collecting training data) |
| Guideline Adherence | LLM clinical impression | **TODO** (needs tiered approach) |
| Drug-Bug Mismatch | Rule-based susceptibility | None needed |
| Surgical Prophylaxis | CPT/procedure rules | None needed |

## Performance Baseline (2026-01-24)
- llama3.3:70b on RTX A5000 + A6000 (tensor parallel)
- ~85 sec/note for CLABSI classification
- ~30 sec/note for CDI classification
- Model size: 42GB split across both GPUs

## Date Created
2026-01-24
