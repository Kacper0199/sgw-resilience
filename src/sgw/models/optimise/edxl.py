"""EDXL-RM shaped mutual-aid request for a course of action.

A JSON rendering of the OASIS EDXL-RM 1.0 `RequestResource` message (element names kept: MessageID,
SentDateTime, MessageContentType, IncidentInformation, ContactInformation, ResourceInformation with Resource,
AssignmentInformation/Quantity/MeasuredQuantity and ScheduleInformation). It mirrors the RMAG/EMAC resource
package (type, count, period, cost) named in the DOE mutual-assistance drop-in. It is not schema-validated
XML; a gateway to a real mutual-assistance portal would serialise it. Asset risk rankings are never included
(R04 adoption A3: share requests, ETAs and staging sites, never risk rankings).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from sgw.models.optimise.saa import Solve
from sgw.models.optimise.scenarios import Context

TYPE_LIST_URN = "urn:sgw:resource-type:electric-distribution"
CREW_TYPE = "overhead-line-crew-group"


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def message_id(ctx: Context, plan_id: str, res: Solve) -> str:
    body = f"{ctx.scenario}|{ctx.advisory}|{plan_id}|{res.y.tolist()}".encode()
    adv = ctx.advisory.replace("+", "P")
    return f"RM-{ctx.scenario.upper()}-{adv}-{plan_id}-{hashlib.sha256(body).hexdigest()[:8]}"


def request_resource(
    ctx: Context, plan_id: str, res: Solve, *, incident_id: str, sent: datetime, usd_per_person_day: float
) -> dict[str, Any] | None:
    """One ResourceInformation element per yard with early mutual aid; None when nothing is requested."""
    if int(res.y.sum()) == 0:
        return None
    elements: list[dict[str, Any]] = []
    arrival = sent + timedelta(hours=ctx.ma_median_h)
    for i, yard in enumerate(ctx.geo.yards):
        groups = int(res.y[i])
        if groups == 0:
            continue
        persons = groups * ctx.ma_group_size
        location = {
            "LocationDescription": yard.yard_id,
            "TargetArea": {"Point": {"lat": yard.lat, "lon": yard.lon}},
        }
        elements.append(
            {
                "ResourceInfoElementID": f"{plan_id}-{yard.yard_id}",
                "Resource": {
                    "Name": "Mutual-aid overhead line crew group",
                    "TypeStructure": {"Value": CREW_TYPE, "ValueListURN": TYPE_LIST_URN},
                    "Description": f"crew group of {ctx.ma_group_size} lineworkers with bucket trucks",
                },
                "AssignmentInformation": {
                    "Quantity": {"MeasuredQuantity": {"Amount": groups, "UnitOfMeasure": "crew group"}},
                    "AnticipatedFunction": "distribution restoration after landfall",
                    "PriceQuote": {
                        "PricingInformation": "per lineworker-day, display estimate",
                        "Amount": round(persons * usd_per_person_day),
                        "Currency": "USD",
                        "Period": "day",
                    },
                },
                "ScheduleInformation": [
                    {"ScheduleType": "RequestedArrival", "DateTime": _iso(arrival), "Location": location},
                    {"ScheduleType": "EstimatedArrival", "DateTime": _iso(arrival), "Location": location},
                ],
            }
        )
    return {
        "MessageID": message_id(ctx, plan_id, res),
        "SentDateTime": _iso(sent),
        "MessageContentType": "RequestResource",
        "MessageDescription": (
            f"Pre-landfall mutual-aid request, {plan_id}, advisory {ctx.advisory}; released only after T3 "
            "approval (command + logistics)"
        ),
        "IncidentInformation": [{"IncidentID": incident_id, "IncidentDescription": f"{ctx.scenario} replay"}],
        "ContactInformation": [{"ContactRole": "Requester", "ContactDescription": "SGW Logistics Section"}],
        "ResourceInformation": elements,
    }
