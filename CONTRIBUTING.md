# Contributing

1. Fork the repository
2. Create a new branch (`feature/your-feature`)
3. Commit your changes with clear messages
4. Push to your fork and submit a pull request

**Ideas for contribution:**

- Adding more distros or mirrors
- Implementing Prometheus metrics endpoint
- Slack or Matrix notification integration
- Disk cleanup or retention policies

## Maintenance notes

When making changes to the fetch logic or features:

- Update `README.md` to reflect new functionality
- Test the script in a controlled environment before deployment
- Ensure log parsing works correctly for ratio checks
- Verify regex patterns match all intended torrent names (e.g., Ubuntu variants)
- Ratio checking is per ISO type (e.g., `installer-amd64`) rather than per distro
