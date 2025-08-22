# Multi-Service Architecture Refactor

## Goals

Restructure the HCA Validation Tools project to support multiple independent services with separate deployment strategies while maintaining a shared core library.

- **Service Independence**: Each service can be built, tested, and deployed independently
- **Dependency Isolation**: Services have separate dependency management (lightweight Lambda vs heavy Fargate)
- **Shared Core Logic**: Common validation logic, schemas, and utilities are reused across services
- **Clean Deployment**: Each service has its own containerization and deployment configuration

## Target Directory Structure

```
hca-validation-tools/
├── shared/                          # Core shared library
│   ├── pyproject.toml              # Minimal core dependencies
│   ├── src/hca_validation/         # Shared validation logic
│   │   ├── __init__.py
│   │   ├── schema/                 # LinkML schemas
│   │   ├── schema_utils/           # Schema utilities
│   │   ├── validator/              # Core validation logic
│   │   └── data_dictionary/        # Data dictionary generation
│   └── tests/                      # Core library tests
├── services/
│   ├── entry-sheet-lambda/         # Lambda service
│   │   ├── pyproject.toml          # Lambda-specific dependencies
│   │   ├── src/
│   │   │   └── lambda_handler.py   # Lambda entry point
│   │   └── tests/                  # Service-specific tests
│   └── h5ad-validator-fargate/     # Fargate service
│       ├── pyproject.toml          # Fargate-specific dependencies
│       ├── src/
│       │   └── validator_service.py # Fargate service entry point
│       └── tests/                  # Service-specific tests
├── deployment/
│   ├── entry-sheet-validator/      # Lambda deployment (current)
│   │   ├── Dockerfile
│   │   ├── build.sh
│   │   └── config.yaml
│   └── h5ad-validator/             # Fargate deployment (planned)
│       ├── Dockerfile
│       ├── build.sh
│       └── task-definition.json
├── data_dictionaries/              # Generated JSON data dictionaries (checked in)
├── tests/                          # Integration tests
└── docs/                          # Documentation
```

## Design Decisions

### **Shared Core Library**

- **Rationale**: Avoid code duplication for common validation logic
- **Dependencies**: Minimal set (LinkML, pydantic, basic utilities)
- **Distribution**: Path dependency for local development, internal package for production
- **Location**: `shared/src/hca_validation/` maintains existing import structure

### **Service-Specific Dependencies**

- **Lambda Service**: Lightweight dependencies only (gspread, google-api-client)
- **Fargate Service**: Heavy scientific stack (scanpy, anndata, scipy, numpy)
- **Isolation**: Each service manages its own `pyproject.toml` and virtual environment
- **Build Process**: Services include shared library as path dependency

### **Deployment Structure**

- **Service-Named Directories**: `deployment/{service-name}/` not `deployment/{platform}/`
- **Self-Contained**: Each deployment directory contains all artifacts for that service
- **No Terraform**: Infrastructure managed in separate repository
- **Container-Based**: Both Lambda and Fargate use Docker containers

### **Code Organization**

- **Existing Code Migration**: Current `src/hca_validation/` moves to `shared/src/hca_validation/`
- **Service Code**: New service-specific code in `services/{service}/src/`
- **Import Compatibility**: Shared library maintains existing import paths
- **Test Structure**: Core tests in `shared/tests/`, service tests in `services/{service}/tests/`

### **Build and Development**

- **No Root pyproject.toml**: Each service manages its own dependencies independently (simpler than Poetry workspaces)
- **Path Dependencies**: Services reference shared library via `{path = "../../shared", develop = true}`
- **Independent Builds**: Each service can be built and tested independently
- **Shared Development**: Core library changes affect all services
- **CI/CD**: Separate build pipelines for each service

### **Migration Strategy**

- **Phase 1**: Restructure deployment directories (✅ completed for entry-sheet-validator)
- **Phase 2**: Create shared library structure
- **Phase 3**: Extract service-specific code
- **Phase 4**: Create h5ad-validator Fargate service
- **Phase 5**: Update build processes and documentation
