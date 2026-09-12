"""
Vercel serverless entry point for the DisasterData Weather API.

RECONSTRUCTED, NOT RECOVERED. The adapter and config that are actually
running in production were deployed from a local project and were never
committed, so this file was rebuilt from weather/api.py rather than
recovered from the live deployment. It has been verified locally. It has
NOT been verified against Vercel. Before trusting it as the production
config, either diff it against the deployed project or redeploy from this
file and confirm /health responds.

Why this shape: weather/api.py already defines the complete routing and
response contract as a BaseHTTPRequestHandler subclass. Vercel's Python
runtime invokes a module-level object named ``handler`` when it is a
BaseHTTPRequestHandler subclass, so the handler is reused verbatim rather
than reimplemented here. Reimplementing the routing in an ASGI wrapper
would create a second copy of the contract that could drift from
weather/api.py without anyone noticing, which is the failure mode this
project has already been bitten by more than once.

Routing note: vercel.json rewrites every path to this function, so
``self.path`` inside the handler is the ORIGINAL request path
(/health, /v1/weather/profile, and so on), which is exactly what
weather/api.py's do_GET already expects. Do not add a path-stripping
step here.
"""

from __future__ import annotations

import os
import sys

# Vercel executes this file with the project root on sys.path in most
# configurations, but not reliably in all of them. Adding the repository
# root explicitly makes the "import weather" below work the same way
# locally and in the deployed function.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from weather.api import WeatherApiHandler  # noqa: E402

handler = WeatherApiHandler
