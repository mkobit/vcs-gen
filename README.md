# vcs-gen

[![CI](https://github.com/mkobit/gitignore-gen/actions/workflows/ci.yml/badge.svg)](https://github.com/mkobit/gitignore-gen/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/pypi/pyversions/vcs-gen)](https://pypi.org/project/vcs-gen/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/mkobit/gitignore-gen)

A zero-dependency toolkit to compose configuration files for Git, JJ, and other VCS.

---

## Table of Contents
- [Why vcs-gen?](#why-vcs-gen)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
  - [The Pipeline](#the-pipeline)
  - [Domains](#domains)
- [Usage Examples](#usage-examples)
  - [Searching & Listing](#searching--listing)
  - [Generating & Dry-run](#generating--dry-run)
  - [Advanced Pipeline](#advanced-pipeline)
- [Interactive Selection](#interactive-selection)
- [Storage & Caching](#storage--caching)
- [Advanced Configuration](#advanced-configuration)

---

## Why vcs-gen?

Unlike other tools that simply fetch a single template, **vcs-gen** allows you to build a sophisticated pipeline of templates, local files, and literal text—all processed in strict left-to-right order.

- **Sequential Pipeline**: Compose multiple sources (GitHub, local dirs, archives) in a single command.
- **Multi-VCS Ready**: Built-in support for `.gitignore` (Git/JJ) and `.gitattributes`.
- **Zero Runtime Dependencies**: Single-file core using only the Python standard library.
- **High Integrity**: 100% test coverage and strict type safety.
- **Visual Feedback**: Search and preview templates with dry-run support.


## Development Setup

To ensure code quality before pushing, this repository uses Git config-based hooks. After cloning the repository, please run the following command to set up the hooks:

```bash
./setup_hooks.sh
```

## Installation

### Ephemeral usage (No install required)
```bash
# Set the script URL (or use directly)
SCRIPT_URL="https://gist.github.com/mkobit/gitignore-gen/raw/vcs_gen.py"
curl -sSfL $SCRIPT_URL | python3 - gitignore generate Python macOS --output .gitignore
```

### via uv (Recommended)
```bash
uvx vcs-gen gitignore generate Python
```

### via pip
```bash
pip install vcs-gen
```

## Quick Start

```bash
# 1. Search for your language
vcs-gen gitignore search python

# 2. Preview what would be generated
vcs-gen gitignore generate Python macOS --dry-run

# 3. Generate the file
vcs-gen gitignore generate Python macOS --output .gitignore
```

## Core Concepts

### The Pipeline
Arguments are processed in the order they appear. This allows you to switch sources, inject text, or include local files at specific points in the generated output.

### Domains
vcs-gen supports multiple "domains" for different VCS configuration files:
- `gitignore`: For `.gitignore` files.
- `gitattributes`: For `.gitattributes` files.

## Usage Examples

### Searching & Listing
```bash
# Search for templates (case-insensitive regex)
vcs-gen gitignore search '.*Go.*'

# List all available templates from the default repository
vcs-gen gitignore ls
```

### Generating & Dry-run
```bash
# Preview selection without writing any files
vcs-gen gitignore generate Python macOS --dry-run

# Generate a combined file for a typical project
vcs-gen gitignore generate Python macOS Windows --output .gitignore
```

### Advanced Pipeline
Interleave local templates with upstream ones, change repositories mid-command, or inject custom text:

```bash
vcs-gen gitignore generate \
  --repo github/gitignore Python macOS \
  --include-text "# Developer Customizations" \
  --local-dir ./my-templates Python \
  --include-text "# Extra Rules" \
  --include-local-file ./extra_rules.txt
```

## Interactive Selection
Combine with `fzf` for a powerful interactive experience:

```bash
vcs-gen gitignore generate $(vcs-gen gitignore ls | fzf --multi | awk '{print $1}')
```

## Storage & Caching
Repository archives (`.tar.gz`) are stored locally to avoid redundant downloads.
- Default: `$XDG_CACHE_HOME/vcs-gen` or `~/.cache/vcs-gen`.
- Fallback: `/tmp/vcs-gen`.

Refresh policy: By default, archives are cached for 7 days. Use `--refresh-period 0d` to force a redownload.

## Advanced Configuration

### Custom Repositories
You can point vcs-gen at any GitHub repository containing templates:

```bash
vcs-gen gitignore generate --repo my-org/custom-ignores MyTemplate
```

### Section Headers
By default, each included template is wrapped in headers. You can disable or customize them:

```bash
vcs-gen gitignore generate Python --no-include-section-header
```

---

*Note: This tool does not automatically purge old archives. To reclaim space, manually delete the cache directory.*
