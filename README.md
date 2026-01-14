# IronClad Compliance

**Automate, Align, and Secure Compliance for the Modern Enterprise**

IronClad Compliance is a Compliance-as-Code platform that automates compliance management with real-time auditing, gap assessment, and AI-powered remediation guidance.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    IronClad Compliance                          │
├─────────────────────────────────────────────────────────────────┤
│  Workflow 1: Framework Update Checker (Quarterly)               │
│  - Monitors AICPA, NIST, PCI SSC, HHS for updates               │
│  - Auto-generates PRs when changes detected                     │
├─────────────────────────────────────────────────────────────────┤
│  Workflow 2: Compliance Assessment Engine                       │
│  - Ingests client evidence                                      │
│  - Maps evidence to framework controls                          │
│  - Calls IronCityIT/consensus-engine for AI analysis            │
│  - Generates readiness reports                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  IronCityIT/consensus-engine (Central AI Authority)             │
│  - 15 AI models with weighted voting                            │
│  - Claude/GPT weighted higher (1.5x/1.3x)                       │
│  - Returns consensus severity + remediation                     │
└─────────────────────────────────────────────────────────────────┘
```

## Supported Frameworks

| Framework | Version | Status |
|-----------|---------|--------|
| SOC 2 (TSC) | 2017 | ✅ Active |
| NIST CSF | 2.0 | 🔜 Planned |
| PCI-DSS | 4.0 | 🔜 Planned |
| HIPAA | Current | 🔜 Planned |

## Usage

### Run Compliance Assessment

```bash
gh workflow run "Compliance Assessment" \
  -R IronCityIT/ironclad-compliance \
  -f client_id=CLIENT_ID \
  -f framework=soc2 \
  -f evidence_path=gs://ironclad-evidence/CLIENT_ID/
```

### Check Framework Updates (Manual Trigger)

```bash
gh workflow run "Framework Update Checker" \
  -R IronCityIT/ironclad-compliance
```

## Repository Structure

```
ironclad-compliance/
├── .github/workflows/
│   ├── framework-update-checker.yml    # Quarterly update checks
│   └── compliance-assessment.yml       # Main assessment workflow
├── frameworks/
│   ├── soc2-2017.json                  # SOC 2 Trust Service Criteria
│   └── framework-versions.json         # Version tracking
├── scripts/
│   ├── check_framework_updates.py      # Framework document parser
│   ├── assess_controls.py              # Control assessment logic
│   ├── generate_report.py              # PDF report generation
│   └── store_results.py                # Firestore/GCS storage
├── templates/
│   └── assessment_report.html          # Report template
└── docs/
    └── control-mapping.md              # Cross-framework mappings
```

## Dependencies

- **IronCityIT/consensus-engine** - Central AI analysis (reusable workflow)
- Firebase/Firestore - Results storage
- GCS - Evidence and report storage

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Passed to consensus-engine |
| `OPENROUTER_API_KEY` | Passed to consensus-engine |
| `GEMINI_API_KEY` | Passed to consensus-engine |
| `GCS_BUCKET` | Evidence storage bucket |
| `FIREBASE_PROJECT_ID` | Firestore project |

## License

Proprietary - Iron City IT Advisors
