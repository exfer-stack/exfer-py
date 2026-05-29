"""Param-dict builders shared by :class:`Client` and :class:`AsyncClient`.

Each method's wire shape lives in exactly one place here so the sync and
async clients can't drift on parameter names or default-omission rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .types import HtlcRole, HtlcState

__all__ = [
    "_addr_paginated_params",
    "_htlc_list_params",
    "_htlc_lock_params",
    "_payment_uri_params",
    "_simulate_transfer_params",
]


def _htlc_lock_params(
    from_: str,
    receiver: str,
    hash_lock: str,
    timeout: int,
    amount: int,
    fee: int | None,
    fee_rate: int | None,
    max_fee: int | None,
) -> dict[str, Any]:
    """Shape shared by ``htlc_lock`` and ``simulate_htlc_lock``."""
    if fee is not None and fee_rate is not None:
        raise ValueError("`fee` and `fee_rate` are mutually exclusive")
    params: dict[str, Any] = {
        "from": from_,
        "receiver": receiver,
        "hash_lock": hash_lock,
        "timeout": timeout,
        "amount": amount,
    }
    if fee is not None:
        params["fee"] = fee
    if fee_rate is not None:
        params["fee_rate"] = fee_rate
    if max_fee is not None:
        params["max_fee"] = max_fee
    return params


def _simulate_transfer_params(
    from_: str,
    outputs: list[Mapping[str, Any]],
    fee: int | None,
    fee_rate: int | None,
    max_fee: int | None,
) -> dict[str, Any]:
    """Shape shared by simulate-side caller plumbing.

    ``outputs`` is forwarded as-is — walletd validates each entry's
    ``to`` / ``amount`` shape. Empty or 16+-entry lists are surfaced as
    server-side ``InvalidParams`` rather than client-side guards.
    """
    if fee is not None and fee_rate is not None:
        raise ValueError("`fee` and `fee_rate` are mutually exclusive")
    params: dict[str, Any] = {"from": from_, "outputs": list(outputs)}
    if fee is not None:
        params["fee"] = fee
    if fee_rate is not None:
        params["fee_rate"] = fee_rate
    if max_fee is not None:
        params["max_fee"] = max_fee
    return params


def _payment_uri_params(
    address: str,
    amount: int | None,
    memo: str | None,
    hash_lock: str | None,
    timeout: int | None,
    label: str | None,
) -> dict[str, Any]:
    """Shape for ``payment_uri_encode``. Unset fields are omitted from
    the wire dict so the receiver's `Option<T>` deserializers see
    explicit ``None``.
    """
    params: dict[str, Any] = {"address": address}
    if amount is not None:
        params["amount"] = amount
    if memo is not None:
        params["memo"] = memo
    if hash_lock is not None:
        params["hash_lock"] = hash_lock
    if timeout is not None:
        params["timeout"] = timeout
    if label is not None:
        params["label"] = label
    return params


def _htlc_list_params(
    role: HtlcRole | None,
    state: HtlcState | list[HtlcState] | None,
    since_height: int | None,
    address: str | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    """Shape for ``htlc_list``. ``state`` accepts either a single state
    string or a list — walletd's deserializer handles both via an
    untagged enum, so we forward whatever the caller gave.
    """
    params: dict[str, Any] = {}
    if role is not None:
        params["role"] = role
    if state is not None:
        params["state"] = state
    if since_height is not None:
        params["since_height"] = since_height
    if address is not None:
        params["address"] = address
    if limit is not None:
        params["limit"] = limit
    if cursor is not None:
        params["cursor"] = cursor
    return params


def _addr_paginated_params(
    address: str,
    contract_hash: str | None,
    since_height: int | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    """Shape shared by ``list_settlements`` and ``get_address_history``."""
    params: dict[str, Any] = {"address": address}
    if contract_hash is not None:
        params["contract_hash"] = contract_hash
    if since_height is not None:
        params["since_height"] = since_height
    if limit is not None:
        params["limit"] = limit
    if cursor is not None:
        params["cursor"] = cursor
    return params
