# HCA Validation Tools

A collection of tools for validating and working with Human Cell Atlas (HCA) ingest data, including H5AD files and entry sheets.

## Overview

This repository contains multiple tools that work together to validate, document, and transfer data for HCA ingest:

- **H5AD Validator**: Validates H5AD (Hierarchical Data Format 5 with AnnData) files against HCA schemas
- **Entry Sheet Validator**: Validates entry sheets (spreadsheets) against HCA schemas
- **Data Dictionary Generator**: Creates data dictionaries from HCA schemas
- **Data Transfer Tools**: Copies and transforms data between entry sheets and H5AD files

## Project Structure

```
hca-validation-tools/
├── src/                  # Source code directory
│   └── hca_validation/    # Core package
│       ├── h5ad_validator/    # H5AD validation tool
│       ├── entry_sheet_validator/ # Entry sheet validation tool
│       ├── data_dictionary/   # Data dictionary generation tool
│       ├── data_transfer/     # Scripts for copying data
│       └── schema/            # Schema definitions
├── notebooks/             # Jupyter notebooks for testing and examples
└── tests/                 # Unit and integration tests
```

## Installation

This project uses Poetry for dependency management. To install:

```bash
# Clone the repository
git clone https://github.com/your-org/hca-validation-tools.git
cd hca-validation-tools

# Install with Poetry
poetry install
```

## Usage

Detailed usage instructions will be provided as the tools are developed.

## Development

### Setup Development Environment

```bash
# Install development dependencies
poetry install --with dev

# Activate the virtual environment
poetry shell
```

### Running Tests

```bash
pytest
```

## License

See the [LICENSE](LICENSE) file for details.