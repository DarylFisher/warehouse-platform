"""Permissions the platform checks. Built-in roles in kernel.roles grant them."""

from enum import StrEnum


class Permission(StrEnum):
    SITES_READ = "sites.read"
    SITES_WRITE = "sites.write"
    USERS_READ = "users.read"
    USERS_MANAGE = "users.manage"


ADMIN_ROLE = "admin"
