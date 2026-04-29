from __future__ import annotations


ROLE_PERMISSIONS = {
    "guest": {
        "name": "访客",
        "permissions": ["view_public"],
    },
    "user": {
        "name": "普通用户",
        "permissions": ["view_public", "view_detail", "manage_own_watchlist"],
    },
    "researcher": {
        "name": "研究员",
        "permissions": ["view_public", "view_detail", "manage_own_watchlist", "save_review", "run_backtest", "manage_model"],
    },
    "admin": {
        "name": "管理员",
        "permissions": ["view_public", "view_detail", "manage_own_watchlist", "save_review", "run_backtest", "manage_model", "view_audit"],
    },
    "auditor": {
        "name": "审计员",
        "permissions": ["view_public", "view_detail", "view_audit"],
    },
}


def normalize_role(role: str | None) -> str:
    if role in ROLE_PERMISSIONS:
        return role
    return "admin"


def has_permission(role: str | None, permission: str) -> bool:
    normalized = normalize_role(role)
    return permission in ROLE_PERMISSIONS[normalized]["permissions"]


def roles_payload(current_role: str | None = None) -> dict[str, object]:
    role = normalize_role(current_role)
    return {
        "current_role": role,
        "current_role_name": ROLE_PERMISSIONS[role]["name"],
        "roles": [
            {"role": key, "name": value["name"], "permissions": value["permissions"]}
            for key, value in ROLE_PERMISSIONS.items()
        ],
    }
