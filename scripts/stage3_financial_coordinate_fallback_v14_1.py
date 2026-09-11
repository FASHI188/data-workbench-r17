#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal

import stage3_financial_coordinate_fallback_v14 as base14


def _choose_triplet_v14_1(candidates: dict[str, list[dict]]):
    """Allow repeated consolidated continuation-title anchors across one block.

    The V14.1c diagnostic proved that the authority gate is row-local role/period:
    each selected A/L/E row must bind to GROUP or DUAL_GROUP_PARENT and to the
    current group numeric column.  Requiring all three rows to share one literal
    title *page* is too strict because official multi-page balance sheets repeat
    `合并资产负债表（续）` on continuation pages.

    Safety remains fail-closed through: row role gate, special-scope rejection,
    current-group column gate, <=9-page balance span, <=9-page role-anchor span,
    x-column proximity and unchanged A=L+E tolerance.
    """
    valid = []
    for assets in candidates.get("TOTAL_ASSETS", []):
        for liabilities in candidates.get("TOTAL_LIABILITIES", []):
            for equity in candidates.get("TOTAL_EQUITY", []):
                trio = (assets, liabilities, equity)
                roles = {x.get("statement_role") for x in trio}
                if not roles or not roles.issubset({"GROUP", "DUAL_GROUP_PARENT"}):
                    continue

                page_span = max(x["page"] for x in trio) - min(x["page"] for x in trio)
                if page_span > base14.MAX_PAGE_SPAN:
                    continue

                anchors = [int(x["statement_anchor_page"]) for x in trio]
                anchor_span = max(anchors) - min(anchors)
                if anchor_span > base14.MAX_PAGE_SPAN:
                    continue

                x_spread = max(x["x"] for x in trio) - min(x["x"] for x in trio)
                if x_spread > base14.MAX_X_SPREAD:
                    continue

                rel = abs(assets["value"] - (liabilities["value"] + equity["value"])) / max(
                    abs(assets["value"]),
                    abs(liabilities["value"] + equity["value"]),
                    Decimal("1"),
                )
                if rel > base14.IDENTITY_TOLERANCE:
                    continue

                strength = sum(int(x["alias_strength"]) for x in trio)
                score = (
                    rel,
                    x_spread,
                    page_span,
                    anchor_span,
                    min(anchors),
                    -strength,
                )
                valid.append((
                    score,
                    {
                        "TOTAL_ASSETS": assets,
                        "TOTAL_LIABILITIES": liabilities,
                        "TOTAL_EQUITY": equity,
                    },
                    {
                        "identity_relative_error": str(rel),
                        "identity_residual_cny": str(abs(assets["value"] - (liabilities["value"] + equity["value"]))),
                        "x_spread": str(x_spread),
                        "page_span": page_span,
                        "statement_anchor_page": min(anchors),
                        "statement_anchor_pages": anchors,
                        "statement_role": "+".join(sorted(roles)),
                        "statement_title": " | ".join(dict.fromkeys(str(x.get("statement_title") or "") for x in trio)),
                    },
                ))

    if not valid:
        return None, None
    valid.sort(key=lambda item: item[0])
    _, chosen, meta = valid[0]
    return chosen, meta


base14._choose_triplet = _choose_triplet_v14_1
validated_coordinate_balance_sheet = base14.validated_coordinate_balance_sheet
