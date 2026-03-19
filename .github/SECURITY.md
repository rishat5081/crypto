# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| latest  | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email: rishat5081@gmail.com
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 5 business days
- **Fix/Patch**: Target within 14 days for critical issues

## Scope

This project handles market data analysis only. It does **not**:
- Store API keys or secrets in the repository
- Place real trading orders
- Handle user authentication or personal data

## Security Best Practices

- Never commit `.env` files or API credentials
- Use environment variables for sensitive configuration
- Keep dependencies updated via Dependabot
- Review all PRs before merging
