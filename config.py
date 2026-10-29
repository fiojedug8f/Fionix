"""Fionix product configuration.

This file is intentionally in the project root because it contains deployment
values (OAuth client, external links, repository).  Replace secrets in your
private deployment; do not publish a real client secret in a public repository.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Microsoft Entra ID / consumer OAuth
# ---------------------------------------------------------------------------
# Public desktop client: no secret is shipped.  Replace with your own app
# registration (see INSTRUCTIONS.md) and request Minecraft Services approval.
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
GITHUB_REPO = "fiojedug8f/Fionix"
GITHUB_API_URL = "https://api.github.com"
# Прокси-воркер CurseForge (подставляет серверный x-api-key). Публичный адрес.
CURSEFORGE_API_KEY = "https://lingering-tree-24a5.fiojedug8f.workers.dev/"
CURSEFORGE_CONSOLE_URL = "https://console.curseforge.com/"
# Optional: set your Discord application id to enable Rich Presence.
DISCORD_CLIENT_ID = "1564404438888874124"
MINECRAFT_APP_REGISTRATION_URL = "https://aka.ms/AppRegInfo"
LITTLESKIN_REGISTER_URL = "https://littleskin.cn/auth/register"
ELYBY_REGISTER_URL = "https://ely.by/register"
CHATGPT_URL = "https://chatgpt.com/"
