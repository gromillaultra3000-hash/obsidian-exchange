# Capabilities and Roles

Lumi v0.2 routes tasks by provider capabilities and roles instead of provider names.

## Capabilities

Each capability includes:

- `id`
- `title`
- `description`
- `category`
- `defaultWeight`
- `riskLevel`

View catalog:

```bash
curl http://localhost:8000/capabilities
```

## Roles

Each role includes:

- `roleId`
- `requiredCapabilities`
- `optionalCapabilities`
- `defaultPriority`
- permission flags such as `canApprove`, `canReject`, `canVeto`, `canFallback`

View roles:

```bash
curl http://localhost:8000/roles
```

## Role suggestion

```bash
curl -X POST http://localhost:8000/providers/{providerId}/suggest-roles
```

## Role fit

```bash
curl http://localhost:8000/providers/{providerId}/role-fit
```
