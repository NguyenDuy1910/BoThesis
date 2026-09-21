#!/usr/bin/env python3
"""Seed local full-access accounts through identity and RBAC services."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env", override=False)

from bothesis.db.engine import get_session_factory
from bothesis.db.models import Tenant
from bothesis.services import (
    ACTIVE_STATUS,
    PLATFORM_ADMIN_ROLE,
    TENANT_ADMIN_ROLE,
    IdentityNotFoundError,
)
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.identity_access.passwords import PasswordCredentialService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService


DEFAULT_PASSWORD = "19102003"
DEFAULT_WORKSPACE_CODE = "FinxWorkspace"


@dataclass(frozen=True, slots=True)
class SeedAccount:
    email: str
    username: str
    display_name: str


SEED_ACCOUNTS = (
    SeedAccount("admin1@gamil.com", "sample-admin-1", "Sample Admin 1"),
    SeedAccount("admin2@gamil.com", "sample-admin-2", "Sample Admin 2"),
    SeedAccount("admin3@gamil.com", "sample-admin-3", "Sample Admin 3"),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed three full-access local test accounts."
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Password for newly created accounts (default: %(default)s)",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Replace passwords for existing sample accounts too.",
    )
    return parser.parse_args()


async def _active_tenants(
    session: AsyncSession, identity: IdentityStoreService
) -> list[Tenant]:
    tenants = list(
        await session.scalars(
            select(Tenant).where(Tenant.status == ACTIVE_STATUS).order_by(Tenant.code)
        )
    )
    if tenants:
        return tenants
    return [
        await identity.create_tenant(
            DEFAULT_WORKSPACE_CODE,
            "Sample Workspace",
        )
    ]


async def seed_accounts(*, password: str, reset_password: bool) -> list[dict[str, object]]:
    """Create or elevate deterministic local accounts in one transaction."""

    factory = get_session_factory()
    async with factory.begin() as session:
        identity = IdentityStoreService(session)
        assignments = RoleAssignmentService(session)
        await identity.sync_system_roles()
        tenants = await _active_tenants(session, identity)
        results: list[dict[str, object]] = []

        for account in SEED_ACCOUNTS:
            created = False
            password_reset = False
            try:
                user = await identity.get_user_by_email(
                    account.email, include_inactive=True
                )
                if not user.status:
                    await identity.set_user_status(user.id, True)
                if reset_password:
                    user.password_hash = PasswordCredentialService.hash(password)
                    await session.flush()
                    password_reset = True
            except IdentityNotFoundError:
                user = await identity.create_user(
                    account.email,
                    username=account.username,
                    display_name=account.display_name,
                    password_hash=PasswordCredentialService.hash(password),
                )
                created = True

            await assignments.ensure_platform_role(user.id, PLATFORM_ADMIN_ROLE)
            for tenant in tenants:
                await identity.assign_membership(user.id, tenant.id)
                await assignments.ensure_tenant_role(
                    user_id=user.id,
                    tenant_id=tenant.id,
                    role_code=TENANT_ADMIN_ROLE,
                    created_by_user_id=user.id,
                )
            results.append(
                {
                    "email": account.email,
                    "created": created,
                    "password_reset": password_reset,
                    "workspace_count": len(tenants),
                }
            )
    return results


async def _main() -> None:
    args = _parse_args()
    results = await seed_accounts(
        password=args.password,
        reset_password=args.reset_password,
    )
    for result in results:
        password_state = "reset" if result["password_reset"] else "preserved"
        if result["created"]:
            password_state = "created"
        print(
            f"{result['email']}: {password_state}; "
            f"platform_admin + tenant_admin in {result['workspace_count']} workspace(s)"
        )


if __name__ == "__main__":
    asyncio.run(_main())
