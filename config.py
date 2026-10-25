"""Fionix product configuration.

This file is intentionally in the project root because it contains deployment
values (OAuth client, external links, repository).  Replace secrets in your
private deployment; do not publish a real client secret in a public repository.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Microsoft Entra ID / consumer OAuth
# ---------------------------------------------------------------------------
# Public Prism Launcher client ID (no client secret; desktop public client).
CLIENT_ID = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"
CLIENT_SECRET = ""
REDIRECT_URL = "http://localhost"

# "common" supports personal Microsoft accounts and work/school accounts.
MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
MICROSOFT_SCOPE = "XboxLive.signin offline_access"

# ---------------------------------------------------------------------------
# External links
# ---------------------------------------------------------------------------
DONATE_URL = "https://www.donationalerts.com/r/fioorange"
GITHUB_REPO = ""
GITHUB_API_URL = "https://api.github.com"
CURSEFORGE_API_KEY = ""
CURSEFORGE_CONSOLE_URL = "https://console.curseforge.com/"
MINECRAFT_APP_REGISTRATION_URL = "https://aka.ms/AppRegInfo"
LITTLESKIN_REGISTER_URL = "https://littleskin.cn/auth/register"
ELYBY_REGISTER_URL = "https://ely.by/register"
CHATGPT_URL = "https://chatgpt.com/"
