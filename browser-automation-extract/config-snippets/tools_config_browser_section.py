    "browser": {
        "name": "Browser Automation",
        "icon": "🌐",
        "providers": [
            {
                "name": "Nous Subscription (Browser Use cloud)",
                "tag": "Managed Browser Use billed to your subscription",
                "env_vars": [],
                "browser_provider": "browser-use",
                "requires_nous_auth": True,
                "managed_nous_feature": "browser",
                "override_env_vars": ["BROWSER_USE_API_KEY"],
                "post_setup": "agent_browser",
            },
            {
                "name": "Local Browser",
                "tag": "Free headless Chromium (no API key needed)",
                "env_vars": [],
                "browser_provider": "local",
                "post_setup": "agent_browser",
            },
            {
                "name": "Browserbase",
                "tag": "Cloud browser with stealth & proxies",
                "env_vars": [
                    {"key": "BROWSERBASE_API_KEY", "prompt": "Browserbase API key", "url": "https://browserbase.com"},
                    {"key": "BROWSERBASE_PROJECT_ID", "prompt": "Browserbase project ID"},
                ],
                "browser_provider": "browserbase",
                "post_setup": "agent_browser",
            },
            {
                "name": "Browser Use",
                "tag": "Cloud browser with remote execution",
                "env_vars": [
                    {"key": "BROWSER_USE_API_KEY", "prompt": "Browser Use API key", "url": "https://browser-use.com"},
                ],
                "browser_provider": "browser-use",
                "post_setup": "agent_browser",
            },
            {
                "name": "Firecrawl",
                "tag": "Cloud browser with remote execution",
                "env_vars": [
                    {"key": "FIRECRAWL_API_KEY", "prompt": "Firecrawl API key", "url": "https://firecrawl.dev"},
                ],
                "browser_provider": "firecrawl",
                "post_setup": "agent_browser",
            },
            {
                "name": "Camofox",
                "tag": "Local anti-detection browser (Firefox/Camoufox)",
                "env_vars": [
                    {"key": "CAMOFOX_URL", "prompt": "Camofox server URL", "default": "http://localhost:9377",
                     "url": "https://github.com/jo-inc/camofox-browser"},
                ],
                "browser_provider": "camofox",
                "post_setup": "camofox",
            },
        ],
    },
    "homeassistant": {
        "name": "Smart Home",
        "icon": "🏠",
        "providers": [
            {
                "name": "Home Assistant",
                "tag": "REST API integration",
                "env_vars": [
                    {"key": "HASS_TOKEN", "prompt": "Home Assistant Long-Lived Access Token"},
                    {"key": "HASS_URL", "prompt": "Home Assistant URL", "default": "http://homeassistant.local:8123"},
                ],
            },
        ],
    },
    "rl": {
        "name": "RL Training",
        "icon": "🧪",
        "requires_python": (3, 11),
        "providers": [
            {
                "name": "Tinker / Atropos",
                "tag": "RL training platform",
                "env_vars": [
                    {"key": "TINKER_API_KEY", "prompt": "Tinker API key", "url": "https://tinker-console.thinkingmachines.ai/keys"},
                    {"key": "WANDB_API_KEY", "prompt": "WandB API key", "url": "https://wandb.ai/authorize"},
                ],
                "post_setup": "rl_training",
            },
        ],
    },
}

# Simple env-var requirements for toolsets NOT in TOOL_CATEGORIES.
# Used as a fallback for tools like vision/moa that just need an API key.
TOOLSET_ENV_REQUIREMENTS = {
    "vision":     [("OPENROUTER_API_KEY",   "https://openrouter.ai/keys")],
    "moa":        [("OPENROUTER_API_KEY",   "https://openrouter.ai/keys")],
}


# ─── Post-Setup Hooks ─────────────────────────────────────────────────────────

def _run_post_setup(post_setup_key: str):
    """Run post-setup hooks for tools that need extra installation steps."""
    import shutil
    if post_setup_key in ("agent_browser", "browserbase"):
        node_modules = PROJECT_ROOT / "node_modules" / "agent-browser"
        if not node_modules.exists() and shutil.which("npm"):
            _print_info("    Installing Node.js dependencies for browser tools...")
            import subprocess
            result = subprocess.run(
                ["npm", "install", "--silent"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT)
            )
            if result.returncode == 0:
                _print_success("    Node.js dependencies installed")
            else:
                from hermes_constants import display_hermes_home
                _print_warning(f"    npm install failed - run manually: cd {display_hermes_home()}/hermes-agent && npm install")
