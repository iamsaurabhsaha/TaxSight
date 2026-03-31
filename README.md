# TaxSight

Privacy-first AI tax preparation tool with BYOK (Bring Your Own Key) LLM support. Estimates your US federal and state taxes through a conversational interview, with document parsing and what-if scenario modeling.

> **DISCLAIMER**: This tool provides tax estimates for informational purposes only. It is NOT professional tax advice and should NOT be used for official tax filing. Consult a qualified tax professional for your specific situation.

## Features

- **Document-First Flow** - Upload all your W-2s, 1099s, 1098-E in one go and get your tax estimate in seconds
- **Consolidated 1099 Support** - Automatically extracts all sections (1099-B, 1099-DIV, 1099-INT) from brokerage consolidated forms
- **Smart Document Handling** - Auto-classifies documents, skips supplemental W-2s, cross-references for inconsistencies
- **Accurate Tax Calculation** - Real 2025 federal tax brackets, qualified dividend rates (0%/15%/20%), NJ/NY/CA state brackets
- **Income Phaseout Logic** - Student loan interest deduction phaseout, Roth IRA (code J) handling, prior-year 1099-R (code P) filtering
- **What-If Scenarios** - Interactive: "What if I contribute $7,000 to an IRA?" with instant tax impact
- **Detailed Breakdown** - Shows every step: income, adjustments, deductions, federal tax, state tax, withholding, refund/owed
- **PDF Reports** - One-click PDF generation with full breakdown and disclaimers
- **BYOK LLM** - Use Claude, OpenAI, Gemini, or Ollama (fully local/private)
- **Privacy Conscious** - Data stored locally in SQLite. Honest about what goes to the AI provider.
- **No Unnecessary PII** - Never asks for SSN, name, address, DOB. Only: filing status, state, age bracket (65+), dependents.
- **Strict Guardrails** - Prompt injection detection, input validation, SSN blocking, disclaimers everywhere

## Quick Start

```bash
# Clone and install
git clone https://github.com/iamsaurabhsaha/TaxSight.git
cd TaxSight
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure (copy and add your API key)
cp .env.example .env
# Edit .env: set TAX_PREP_LLM_PROVIDER and your API key

# Test connection
taxsight config test

# Run it
taxsight session create --name "my-taxes" --year 2025
taxsight interview --name "my-taxes"
```

## How It Works

1. **Answer 3 questions**: Filing status, state, 65+?
2. **Upload documents**: Paste all file paths at once — PDFs and images supported
3. **Review extracted data**: Confirm what was parsed, fix anything wrong
4. **2 more questions**: Dependents? Standard or itemized deduction?
5. **Get your results**: Full breakdown with federal/state tax, refund/owed, effective rate
6. **Optional**: Generate PDF report, explore what-if scenarios

### Example Session

```
$ taxsight interview --name "my-taxes"

Welcome to TaxSight for TAX YEAR 2025!
What's your filing status? Single

Which state? NJ
Are you 65 or older? no

[paste all document paths]
Processed 7 document(s) successfully.

Does this look correct? yes
Do you have any dependents? no
Standard deduction or itemized? auto

╭──────── Tax Estimate Breakdown ────────╮
│ INCOME                                 │
│   Wages (W-2):        $211,259.19      │
│   Interest:           $245.90          │
│   Dividends:          $554.39          │
│   Total Gross Income: $212,059.48      │
│                                        │
│ FEDERAL TAX                            │
│   Income Tax:         $40,108.65       │
│                                        │
│ STATE TAX (NJ)                         │
│   State Income Tax:   $10,602.97       │
│                                        │
│ RESULT                                 │
│   Federal Owed:       $1,824.56        │
│   State Refund:       $2,474.62        │
│   >>> TOTAL REFUND: $650.06 <<<        │
│   Effective Tax Rate: 23.9%            │
╰────────────────────────────────────────╯

Would you like to generate a PDF report? yes
Would you like to explore what-if scenarios? yes
  ira_contribution=7000 → Tax savings: $1,680
```

## Configuration

Edit `.env` with your preferred provider:

```bash
# LLM Provider: "anthropic", "openai", "gemini", "ollama"
TAX_PREP_LLM_PROVIDER=anthropic

# API Keys (only the one for your chosen provider is needed)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...

# For Ollama (fully local, no cloud)
# TAX_PREP_LLM_PROVIDER=ollama
# TAX_PREP_MODEL=ollama/gemma3:12b
# OLLAMA_BASE_URL=http://localhost:11434
```

## All Commands

```bash
# Session management
taxsight session create --name "2025-taxes" --year 2025
taxsight session list
taxsight session delete --name "2025-taxes"

# Configuration
taxsight config show
taxsight config test

# Interview (interactive)
taxsight interview --name "2025-taxes"

# Direct calculation (if profile already populated)
taxsight calculate --name "2025-taxes"

# What-if scenarios
taxsight what-if --name "2025-taxes" --scenario "ira_contribution=7000"

# PDF report
taxsight report --name "2025-taxes"
taxsight report --name "2025-taxes" --output my_report.pdf

# Document management
taxsight docs upload w2.png --session "2025-taxes"
taxsight docs list --session "2025-taxes"
taxsight docs check --session "2025-taxes"

# Debug mode
taxsight --verbose interview --name "2025-taxes"
taxsight --debug calculate --name "2025-taxes"
```

## Supported Documents

| Document | What's Extracted |
|---|---|
| **W-2** | Wages, federal/state withholding, SS/Medicare taxes |
| **1099-NEC** | Nonemployee compensation |
| **1099-INT** | Interest income |
| **1099-DIV** | Ordinary and qualified dividends |
| **1099-B** | Proceeds, cost basis, gain/loss |
| **1099-R** | Retirement distributions (handles Roth code J, prior year code P) |
| **1098-E** | Student loan interest |
| **Consolidated 1099** | Auto-extracts all sections from brokerage statements |

## Tax Logic

- **2025 federal brackets** for Single, MFJ, MFS, HOH
- **Qualified dividends** taxed at 0%/15%/20% preferential rates
- **Student loan interest phaseout** at $85K-$100K (single) / $170K-$200K (MFJ)
- **Roth IRA (code J)** treated as $0 taxable (return of contributions)
- **Supplemental W-2s** auto-detected and skipped
- **Real state brackets** for NJ, NY, CA (others at estimated rates)
- **Self-employment tax** with SS wage base, Medicare, additional Medicare
- **Child Tax Credit** with age < 17 check

## Architecture

```
src/ai_tax_prep/
  cli/           # Typer CLI commands (interview, calculate, report, docs)
  core/          # Interview engine (state machine), tax profile, sessions
  llm/           # LiteLLM client, prompts, guardrails, context management
  documents/     # PDF text extraction, LLM vision, consolidated 1099 parser
  tax/           # Deterministic tax engine, deduction finder, what-if
  export/        # PDF report generation with fpdf2
  db/            # SQLAlchemy models (6 tables), SQLite
  config/        # BYOK settings management
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| CLI | Typer + Rich |
| LLM | LiteLLM (Claude, OpenAI, Gemini, Ollama) |
| Tax Engine | Built-in deterministic calculator (2025 brackets) |
| PDF Parsing | PyMuPDF |
| Database | SQLite + SQLAlchemy |
| OCR | Tesseract (optional) |
| PDF Export | fpdf2 |
| Tests | pytest (83 unit + 116 UAT scenarios) |

## Development

```bash
pip install -e ".[dev]"
pytest                    # Run unit tests
ruff check src/ tests/    # Lint
```

## License

AGPL-3.0 - See [LICENSE](LICENSE) for details.

Free to use, modify, and distribute. If you host this as a web service, you must share your source code.

## Feedback

For feedback or questions: [linkedin.com/in/iamsaurabhsaha](https://www.linkedin.com/in/iamsaurabhsaha/)
