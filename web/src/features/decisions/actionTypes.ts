import {
  Clock,
  FileText,
  Fuel,
  Handshake,
  HardHat,
  ListOrdered,
  type LucideIcon,
  Megaphone,
  MegaphoneOff,
  Shuffle,
  SlidersHorizontal,
  Tag,
  Truck,
  Wrench,
  Zap,
} from "lucide-react";
import type { ProposalSummary } from "@/lib/api";
import { plainIds } from "@/lib/names";

type ActionType = ProposalSummary["action_type"];

export interface ActionMark {
  label: string;
  Icon: LucideIcon;
}

const MARK: Record<ActionType, ActionMark> = {
  set_event_type: { label: "Event type", Icon: Tag },
  preposition_crews: { label: "Crew pre-position", Icon: HardHat },
  reoptimise_within_envelope: { label: "Crew re-plan", Icon: Shuffle },
  stage_crews_small: { label: "Crew staging", Icon: HardHat },
  mutual_aid_request: { label: "Mutual aid", Icon: Handshake },
  cross_domain_priority: { label: "Restoration order", Icon: ListOrdered },
  boil_water_notice: { label: "Boil-water notice", Icon: Megaphone },
  lift_boil_water_notice: { label: "Lift a notice", Icon: MegaphoneOff },
  field_resource_order: { label: "Resource order", Icon: Truck },
  publish_global_etr: { label: "Restoration estimate", Icon: Clock },
  work_order_draft: { label: "Work order", Icon: Wrench },
  sitrep_draft: { label: "Situation report", Icon: FileText },
  policy_change: { label: "Policy setting", Icon: SlidersHorizontal },
};

const RESOURCE: Record<string, ActionMark> = {
  fuel: { label: "Fuel truck", Icon: Fuel },
  potable_water_tanker: { label: "Water tanker", Icon: Truck },
  mobile_generator: { label: "Portable generator", Icon: Zap },
};

const GENERATOR_HOOKUP: ActionMark = { label: "Generator hookup", Icon: Zap };

/** The plain name and icon of what a decision does; a resource order names the resource when the card says which,
 * and a priority decision that puts a generator on a station is a generator hookup. */
export function actionMark(action: ActionType, params?: Record<string, unknown> | null): ActionMark {
  if (action === "cross_domain_priority" && typeof params?.generator_id === "string") return GENERATOR_HOOKUP;
  if (action === "field_resource_order") {
    const kind = params?.resource_kind;
    const resource = typeof kind === "string" ? RESOURCE[kind] : undefined;
    if (resource) return resource;
  }
  return MARK[action];
}

const DARK_SECTION = /\bAMI section FDR-[A-Z]+-(\d+)-S(\d+)\b/g;
const FEEDER_SECTION = /\bFDR-[A-Z]+-(\d+)-S(\d+)\b/g;
const VEHICLE = /\b(?:FTK|WTK|MGEN)-([A-Z]+)(?:-(\d+))?\b/g;

const capitalised = (word: string): string => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();

/** A server title with its identifiers in words: "AMI section FDR-AIK-2231-S3" reads as "meter section 3 of feeder 2231", "MGEN-HALBERD-500" as "Halberd", "FTK-WREN-3" as "Wren 3"; the rest by `plainIds`. */
export const decisionTitle = (title: string): string =>
  plainIds(
    title
      .replace(DARK_SECTION, "meter section $2 of feeder $1")
      .replace(FEEDER_SECTION, "feeder $1, section $2")
      .replace(VEHICLE, (id, name: string, n?: string) =>
        id.startsWith("MGEN") || n === undefined ? capitalised(name) : `${capitalised(name)} ${n}`,
      ),
  );
