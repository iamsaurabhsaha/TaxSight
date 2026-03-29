# AI Tax Prep Assistant

Privacy-first AI tax preparation tool with BYOK (Bring Your Own Key) LLM support. Estimates your US federal and state taxes through a conversational interview, with document parsing and what-if scenario modeling.

> **DISCLAIMER**: This tool provides tax estimates for informational purposes only. It is NOT professional tax advice and should NOT be used for official tax filing. Consult a qualified tax professional for your specific situation.

## Features

- **Guided Tax Interview** - Conversational step-by-step walkthrough of your tax situation
- **Document Ingestion** - Upload W-2s, 1099s with OCR + AI vision extraction
- **Smart Cross-Referencing** - Flags missing documents and inconsistencies
- **Tax Estimation** - Federal + all 50 states with detailed breakdowns
- **Deduction & Credit Finder** - Surfaces deductions and credits you might qualify for
- **What-If Scenarios** - Compare "what if I contribute to an IRA?" scenarios
- **Plain-English Explanations** - AI explains every calculation in simple terms
- **PDF Export** - Clean summary report with disclaimers
- **BYOK LLM** - Use Claude, OpenAI, Gemini, or Ollama (local/private)
- **Privacy First** - All data stored locally in SQLite on your machine

## Installation

### Prerequisites

- Python 3.11+
- An API key for Claude, OpenAI, or Gemini (or Ollama for local models)
- Optional: Tesseract OCR (`brew install tesseract`) for document scanning

### Setup

```bash
# Clone the repo
git clone https://github.com/iamsaurabhsaha/ai-tax-prep.git
cd ai-tax-prep

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"

# Configure your API key
cp .env.example .env
# Edit .env and add your API key
```

### Environment Variables

Edit `.env` with your preferred provider:

```bash
# LLM Provider: "anthropic", "openai", "gemini", "ollama"
TAX_PREP_LLM_PROVIDER=anthropic

# API Keys (only the one for your chosen provider is needed)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...

# For Ollama (local models)
# OLLAMA_BASE_URL=http://localhost:11434
```

## Usage

### Quick Start

```bash
# 1. Test your LLM connection
tax-prep config test

# 2. Create a session
tax-prep session create --name "my-taxes" --year 2025

# 3. Start the interview (run in terminal, not through another tool)
tax-prep interview --name "my-taxes"

# 4. Calculate your taxes
tax-prep calculate --name "my-taxes"

# 5. Generate a PDF report
tax-prep report --name "my-taxes"
```

### All Commands

#### Session Management
```bash
tax-prep session create --name "2025-taxes" --year 2025
tax-prep session list
tax-prep session delete --name "2025-taxes"
```

#### Configuration
```bash
tax-prep config show      # Show current provider and settings
tax-prep config test      # Test LLM connection
```

#### Tax Interview
```bash
tax-prep interview --name "2025-taxes"
```

During the interview, you can use these commands:
- `/help` - Show available commands
- `/status` - Show progress and collected data
- `/back` - Go to the previous step
- `/skip` - Skip optional steps
- `/quit` - Save and exit (resume later)

#### Document Upload
```bash
# Upload a tax document (auto-detects type)
tax-prep docs upload w2.png --session "2025-taxes"

# Specify document type
tax-prep docs upload 1099.pdf --session "2025-taxes" --type 1099_nec

# List uploaded documents
tax-prep docs list --session "2025-taxes"

# Cross-reference documents for issues
tax-prep docs check --session "2025-taxes"
```

Supported document types: `w2`, `1099_nec`, `1099_int`, `1099_div`, `1099_b`, `1099_r`

#### Tax Calculation
```bash
# Calculate tax estimate
tax-prep calculate --name "2025-taxes"

# What-if scenarios
tax-prep what-if --name "2025-taxes" --scenario "ira_contribution=7000"
tax-prep what-if --name "2025-taxes" --scenario "charitable_donation=5000"
tax-prep what-if --name "2025-taxes" --scenario "use_itemized=true"
```

#### PDF Report
```bash
tax-prep report --name "2025-taxes"
tax-prep report --name "2025-taxes" --output my_report.pdf
```

## Architecture

```
src/ai_tax_prep/
  cli/           # Typer CLI commands
  core/          # Interview engine, tax profile, session management
  llm/           # LiteLLM client, prompts, guardrails, context management
  documents/     # OCR, LLM vision, document parsing and schemas
  tax/           # Tax calculation engine, PolicyEngine adapter, deductions
  export/        # PDF report generation
  db/            # SQLAlchemy models, database, CRUD
  config/        # Application settings
```

### Key Design Decisions

- **LLM for understanding, deterministic code for math** - The AI handles conversation, document parsing, and explanations. Tax calculations use coded formulas with real IRS brackets.
- **State machine interview** - Ensures every required field is collected without skipping or hallucinating.
- **Auto-save** - Progress is saved to SQLite after every step.
- **Strict guardrails** - Prompt injection detection, input validation, uncertainty flagging, disclaimers everywhere.

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| CLI | Typer + Rich |
| LLM | LiteLLM (Claude, OpenAI, Gemini, Ollama) |
| Tax Engine | Built-in calculator + PolicyEngine (optional) |
| Database | SQLite + SQLAlchemy |
| OCR | Tesseract (optional) |
| PDF | fpdf2 |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/ tests/
```

## License

AGPL-3.0 - See [LICENSE](LICENSE) for details.

This means: free to use, modify, and distribute. If you host this as a web service, you must share your source code.
