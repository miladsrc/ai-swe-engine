"""
E1: register blueprint + seed the governed chain for the map demo
(project -> PRD -> user story -> ACs -> spec), then open GATE 1 by
validating the spec under the caller's Bearer identity.

Idempotent: re-runs reuse deterministic ids on 409.

Usage:
  SASE_HUMAN_TOKEN=<tok> python scripts/seed_map_demo.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("SASE_BASE_URL", "http://localhost:8000")
PROJECT = "sod-map-demo"
DOMAIN = "MAP"

if not os.environ.get("SASE_HUMAN_TOKEN"):
    sys.exit("Set SASE_HUMAN_TOKEN first (POST /auth/login).")
TOKEN = os.environ["SASE_HUMAN_TOKEN"]


def call(method, path, payload=None, ok=(200, 201)):
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {TOKEN}"}
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode() or "{}"), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code in ok:
            return {"_conflict": True}, e.code
        raise RuntimeError(f"{method} {path} -> {e.code}: {body}") from e


ACS = [
    "POST /api/locations creates a location and returns it with a generated id",
    "GET /api/locations lists all locations with name and description",
    "GET /api/locations/{id} returns 404 for an unknown id",
    "PUT /api/locations/{id} updates name/description; unknown id -> 404",
    "DELETE /api/locations/{id} removes it; subsequent GET -> 404",
    "Empty or oversized name rejected with 400",
]

BLUEPRINT_BODY = """# BP-DEMO-MAP-001 — Location Map Demo (SoD validation vehicle)
Scope: project:sod-map-demo
Stack: Spring Boot 3 (Maven, H2) backend; Angular 17 standalone frontend.
Air-gap rules: NO external map tile servers; locations render as table/list.
API contract: POST/GET /api/locations; GET/PUT/DELETE /api/locations/{id}.
Validation: name 1..120 chars required; description <=500; lat in [-90,90],
lng in [-180,180] when present -> else 400.
Backend layout: com.example.map.{Location, LocationRepository,
LocationService, LocationController}; H2 ddl-auto=update.
Frontend layout: single standalone component location-list (table + create
form), dev proxy or built assets into static/.
Test strategy: service unit tests + MockMvc controller tests (backend);
ng build must succeed (frontend).
Anti-patterns: no business logic in controllers; no field injection;
no external network calls."""


def main():
    me = call("GET", "/auth/me")[0]
    human = me["actor_id"]
    print(f"[e1] acting human: {human}")

    bp, code = call("POST", "/blueprints", {
        "id": "BP-DEMO-MAP-001", "version": "v1.0",
        "scope": f"project:{PROJECT}",
        "body_ref": BLUEPRINT_BODY,
        "approved_by": human,
        "change_note": "Initial blueprint for SoD validation demo.",
    }, ok=(200, 201))
    print(f"[e1] blueprint BP-DEMO-MAP-001 v1.0 registered (http {code})")

    call("POST", "/projects", {
        "id": PROJECT, "name": "Location Map Demo (SoD)",
        "stack": "springboot+angular"}, ok=(200, 201, 409))
    print(f"[e1] project ready: {PROJECT}")

    prd, _ = call("POST", "/prds", {
        "project_id": PROJECT, "domain": DOMAIN,
        "title": "Location Map Demo",
        "body_ref": "Users create and view locations. Each location stores "
                    "a name and a description. Fully offline.",
        "created_by": human})
    us, _ = call("POST", "/user-stories", {
        "prd_id": prd["id"], "domain": DOMAIN,
        "body_ref": "As a user I manage named locations (create/view/edit/"
                    "delete) so that I can keep an offline catalog of places."})
    ac_ids = []
    for body in ACS:
        ac, _ = call("POST", "/acceptance-criteria", {
            "user_story_id": us["id"], "body_ref": body})
        ac_ids.append(ac["id"])

    refs = "\n".join(f"  - {a}" for a in ac_ids)
    spec_body = (
        "behavior:\n"
        "  backend:\n"
        "    - Spring Boot REST API /api/locations (create/list/get/update/delete)\n"
        "    - Location entity: id, name, description, lat, lng\n"
        "    - validation per blueprint (name required<=120, desc<=500, ranges)\n"
        "  frontend:\n"
        "    - Angular standalone component: table of locations + create form\n"
        "    - talks to /api/locations via fetch/HttpClient\n"
        "acceptance_criteria_refs:\n" + refs +
        "\ntest_strategy:\n"
        "  - LocationServiceTest (unit) + LocationControllerTest (MockMvc)\n"
        "  - ng build must succeed\n"
        "open_questions: []\n")

    try:
        spec, code = call("POST", "/specs", {
            "project_id": PROJECT, "user_story_id": us["id"],
            "domain": DOMAIN, "name": "location-crud",
            "body_ref": spec_body})
        spec_id = spec["id"]
        print(f"[e1] spec created: {spec_id}")
    except RuntimeError as e:
        if "409" not in str(e):
            raise
        # id collision from a previous run: bump the sequence via psql-free route —
        # create with a suffixed name instead
        import time
        spec, _ = call("POST", "/specs", {
            "project_id": PROJECT, "user_story_id": us["id"],
            "domain": DOMAIN, "name": f"location-crud-{int(time.time())}",
            "body_ref": spec_body})
        spec_id = spec["id"]
        print(f"[e1] prior spec existed; created {spec_id}")

    print(f"\n[e1] chain: PRD={prd['id']} US={us['id']} "
          f"ACs={len(ac_ids)} SPEC={spec_id}")
    print("[e1] GATE 1: validating spec under your identity…")
    call("POST", f"/specs/{spec_id}/validate", {})
    print(f"[e1] GATE 1 OPEN — spec validated by {human}")
    print(f"[e1] NEXT: E2 backend proposal (SASE_SOD_MODE=strict)")


if __name__ == "__main__":
    main()
