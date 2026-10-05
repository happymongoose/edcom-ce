#!/usr/bin/env bash
# Docker CLI driver: mount the checkout at its identical host path.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS="$ROOT/.build/security-scan"
mkdir -p "$REPORTS" "$ROOT/.build/trivy-cache"
SCANNER="aquasec/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c"
# Update once, then use the same database for every image in this run.
docker run --rm -v "$ROOT/.build/trivy-cache:/root/.cache/trivy" "$SCANNER" image --download-db-only
images=("${API_IMAGE:-edcom/api:hardened-amd64}" "${DB_IMAGE:-edcom/database:hardened-amd64}"
        "${PROXY_IMAGE:-edcom/proxy:security-amd64}" "${SMTP_IMAGE:-edcom/smtprelay:hardened-amd64}"
        "${SCREENSHOT_IMAGE:-edcom/screenshot:hardened-amd64}"
        "${CACHE_IMAGE:-redis:7.2-alpine@sha256:29e8589c3f9ba699b5f7aa4b3c7733c58852a3626439e619aa0ee78de08c6ca0}")
names=(api database proxy smtprelay screenshot redis)
for i in "${!images[@]}"; do
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$ROOT/.build/trivy-cache:/root/.cache/trivy" -v "$REPORTS:/reports" "$SCANNER" \
    image --image-src docker --scanners vuln --skip-db-update --skip-version-check \
    --timeout 10m --format json --output "/reports/${names[$i]}.json" "${images[$i]}"
done
docker run --rm -i --network none -v "$REPORTS:/reports:ro" --entrypoint python "${images[0]}" - <<'PYSCAN'
import collections, json, pathlib, sys
critical = 0
for path in sorted(pathlib.Path('/reports').glob('*.json')):
    report = json.loads(path.read_text())
    counts = collections.Counter(v['Severity'] for r in report.get('Results', [])
                                 for v in r.get('Vulnerabilities', []))
    critical += counts['CRITICAL']
    print(path.stem, report['Metadata']['ImageID'], report['Metadata'].get('OS'), dict(counts))
sys.exit(bool(critical))
PYSCAN
