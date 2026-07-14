"""
Example ScreenSystem.risk_rules / login_macro payloads.

These belong in per-system DB config (驭屏系统管理), not in engine code.
Copy into a system's risk_rules / login_macro JSON fields as needed.
"""

# Example: site that shows an IP/security interstitial before login.
XHS_LIKE_RISK_RULES = {
    "block_url_substrings": ["website-login/error", "error_code=300012"],
    "block_body_hints": ["ip存在风险", "安全限制", "切换可靠网络", "300012"],
    "block_error_code": "300012",
    "block_message": "检测到当前网络存在风险，登录被拦截",
    "recovery_hint": "关闭 VPN/代理，改用手机热点，并确认 entry_url 指向真实登录页",
    "t3_labels": [],
}

# Example SMS login macro (selectors are site-specific; keep out of perceive/act).
SMS_LOGIN_MACRO_EXAMPLE = {
    "steps": [
        {"action": "goto", "value": "", "wait_ms": 800},
        {"action": "click", "selector": "input[type='checkbox']", "wait_ms": 300},
        {"action": "fill", "selector": "input[type='tel']", "value": "{{username}}"},
        {"action": "click", "selector": "button:has-text('获取验证码')", "wait_ms": 500},
        {
            "action": "wait_for_otp",
            "selector": "input[placeholder*='验证码']",
            "submit_selector": "button:has-text('登录')",
            "prompt": "请输入短信验证码",
            "wait_ms": 500,
        },
    ]
}
