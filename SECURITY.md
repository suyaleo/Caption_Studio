# Security Policy

## Supported version

Security fixes are applied to the latest release line.

## Reporting

Use GitHub private vulnerability reporting. Do not open a public issue containing credentials, private infrastructure, personal media, or a working exploit. Include the affected version, impact and the smallest safe reproduction.

## Runtime data

- Uploaded media, subtitles, temporary audio, model caches and rendered videos are runtime data and must remain outside Git.
- Commit `.env.example`, never `.env` or API credentials.
- Browser-visible environment values are public information.
- Docker secrets must be supplied at runtime, never through build arguments or image layers.
