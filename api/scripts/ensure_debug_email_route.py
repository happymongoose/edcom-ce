import argparse
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

JsonObj = Dict[str, Any]


DEBUG_BACKEND_NAME = "Automation Debug Log"
DEBUG_ROUTE_NAME = "Automation Debug Log Route"


def utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def route_payload(debug_backend_id: str) -> JsonObj:
    return {
        "usedefault": False,
        "rules": [
            {
                "default": True,
                "domaingroup": "",
                "splits": [
                    {
                        "policy": debug_backend_id,
                        "pct": 100,
                    }
                ],
            }
        ],
    }


def describe_routes(db, route_ids: List[str]) -> List[JsonObj]:
    oldcid = db.get_cid()
    db.set_cid(None)
    try:
        routes = []
        for route_id in route_ids:
            route = db.routes.get(route_id)
            if route is None:
                routes.append(
                    {
                        "id": route_id,
                        "name": "(missing)",
                        "published": False,
                    }
                )
            else:
                routes.append(
                    {
                        "id": route["id"],
                        "name": route.get("name", ""),
                        "cid": route.get("cid"),
                        "published": route.get("published") is not None,
                    }
                )
        return routes
    finally:
        db.set_cid(oldcid)


def describe_routes_with_planned(
    db, route_ids: List[str], planned_route_id: str, owner_cid: str
) -> List[JsonObj]:
    descriptions_by_id = {route["id"]: route for route in describe_routes(db, route_ids)}
    descriptions_by_id[planned_route_id] = {
        "id": planned_route_id,
        "name": DEBUG_ROUTE_NAME,
        "cid": owner_cid,
        "published": True,
    }
    return [descriptions_by_id[route_id] for route_id in route_ids]


def find_named(wrapper, name: str) -> Optional[JsonObj]:
    return wrapper.find_one({"name": name})


def ensure_debug_backend(db, owner_cid: str, apply: bool) -> Tuple[Optional[str], str]:
    oldcid = db.get_cid()
    db.set_cid(owner_cid)
    try:
        backend = find_named(db.debug_email_backends, DEBUG_BACKEND_NAME)
        if backend is not None:
            return backend["id"], "found"

        if not apply:
            return None, "would create"

        backend_id = db.debug_email_backends.add(
            {
                "name": DEBUG_BACKEND_NAME,
                "created": utcnow(),
                "dev_helper": "ensure_debug_email_route",
            }
        )
        return backend_id, "created"
    finally:
        db.set_cid(oldcid)


def route_matches(route: JsonObj, debug_backend_id: str) -> bool:
    expected = route_payload(debug_backend_id)
    published = route.get("published")
    return (
        route.get("usedefault") == expected["usedefault"]
        and route.get("rules") == expected["rules"]
        and published is not None
        and published.get("usedefault") == expected["usedefault"]
        and published.get("rules") == expected["rules"]
        and not route.get("dirty", False)
    )


def ensure_debug_route(
    db, owner_cid: str, debug_backend_id: Optional[str], apply: bool
) -> Tuple[Optional[str], str]:
    oldcid = db.get_cid()
    db.set_cid(owner_cid)
    try:
        route = find_named(db.routes, DEBUG_ROUTE_NAME)
        if debug_backend_id is None:
            if route is not None:
                return route["id"], "would update existing debug route"
            return None, "would create"

        payload = route_payload(debug_backend_id)
        now = utcnow()
        if route is None:
            if not apply:
                return None, "would create"

            route_id = db.routes.add(
                {
                    "name": DEBUG_ROUTE_NAME,
                    "modified": now,
                    "dirty": False,
                    "dev_helper": "ensure_debug_email_route",
                    **payload,
                    "published": payload.copy(),
                }
            )
            return route_id, "created"

        if route_matches(route, debug_backend_id):
            return route["id"], "found"

        if not apply:
            return route["id"], "would update existing debug route"

        db.routes.patch(
            route["id"],
            {
                "modified": now,
                "dirty": False,
                **payload,
                "published": payload.copy(),
            },
        )
        return route["id"], "updated existing debug route"
    finally:
        db.set_cid(oldcid)


def patch_company_routes(
    db,
    customer_id: str,
    current_routes: List[str],
    debug_route_id: str,
    make_debug_only: bool,
    apply: bool,
) -> Tuple[List[str], str]:
    if make_debug_only:
        final_routes = [debug_route_id]
        action = "would replace with debug route only"
    elif debug_route_id in current_routes:
        final_routes = list(current_routes)
        action = "already assigned"
    else:
        final_routes = list(current_routes) + [debug_route_id]
        action = "would append debug route"

    if apply:
        action = action.replace("would ", "")
        if final_routes != current_routes:
            oldcid = db.get_cid()
            db.set_cid(None)
            try:
                db.companies.patch(customer_id, {"routes": final_routes})
            finally:
                db.set_cid(oldcid)

    return final_routes, action


def restore_sql(customer_id: str, routes: List[str]) -> str:
    payload = json.dumps({"routes": routes})
    return (
        "update companies "
        "set data = data || '%s'::jsonb "
        "where id = '%s';" % (payload.replace("'", "''"), customer_id.replace("'", "''"))
    )


def print_routes(title: str, routes: List[JsonObj]) -> None:
    print(title)
    if not routes:
        print("  (none)")
        return
    for route in routes:
        published = "published" if route.get("published") else "unpublished"
        cid = route.get("cid")
        cid_text = " cid=%s" % cid if cid else ""
        print("  - %s | %s | %s%s" % (route["id"], route["name"], published, cid_text))


def run(args: argparse.Namespace) -> int:
    from api.shared.db import open_db

    apply = args.apply

    with open_db() as db:
        db.set_cid(None)
        customer = db.companies.get(args.cid)
        if customer is None:
            raise SystemExit("Customer/account not found: %s" % args.cid)

        customer_name = customer.get("name", "")
        owner_cid = customer.get("cid") or customer["id"]
        current_routes = list(customer.get("routes") or [])

        print("Mode: %s" % ("APPLY" if apply else "DRY RUN"))
        if args.make_debug_only:
            print("DEV/TEST ACTION: --make-debug-only requested")
        print("Target customer/account: %s | %s" % (customer["id"], customer_name))
        print("Route/backend owner cid: %s" % owner_cid)
        print_routes("Current assigned routes:", describe_routes(db, current_routes))

        backend_id, backend_action = ensure_debug_backend(db, owner_cid, apply)
        print(
            "Debug backend: %s | %s"
            % (backend_action, backend_id or "(new id will be created on apply)")
        )

        route_id, route_action = ensure_debug_route(db, owner_cid, backend_id, apply)
        print(
            "Debug route: %s | %s"
            % (route_action, route_id or "(new id will be created on apply)")
        )

        route_id_for_assignment = route_id or "(new debug route id on apply)"

        final_routes, assignment_action = patch_company_routes(
            db,
            customer["id"],
            current_routes,
            route_id_for_assignment,
            args.make_debug_only,
            apply,
        )
        print("Assignment: %s" % assignment_action)
        print_routes(
            "Final assigned routes:",
            describe_routes_with_planned(
                db, final_routes, route_id_for_assignment, owner_cid
            ),
        )

        if args.make_debug_only:
            print("Previous assigned route IDs:")
            print("  %s" % json.dumps(current_routes))
            print("Manual restore SQL:")
            print("  %s" % restore_sql(customer["id"], current_routes))

        if apply:
            print("Changes applied.")
        else:
            print("No changes made. Re-run with --apply to make these changes.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ensure a dev/testing debug email backend and route is assigned to a selected customer."
    )
    parser.add_argument("--cid", required=True, help="Customer/account company id to modify.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag the script only prints a dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode. This is the default and is accepted for clarity.",
    )
    parser.add_argument(
        "--make-debug-only",
        action="store_true",
        help=(
            "DEV/TEST ONLY: replace the selected customer's assigned routes with only "
            "the debug route. Does not delete routes."
        ),
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply cannot be used together")
    if args.make_debug_only and not args.apply:
        print("--make-debug-only requested in dry-run mode; no route assignment will be changed.")

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
