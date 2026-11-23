import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FUNCTION_LABEL } from "@/auth/personas";
import type { components } from "@/contracts/api.gen";
import { ApiError, get, post } from "@/lib/api";
import { crewName } from "@/lib/names";
import type { CrewItem } from "./types";

export type CrewTarget = components["schemas"]["CrewTarget"];
export type CrewAction = NonNullable<CrewItem["actions"]>[number];
export type BlockReason = components["schemas"]["BlockReason"];
export type CrewMove = components["schemas"]["CrewMoveRequest"]["move"];
type Result = components["schemas"]["CrewDispatchResult"];

const path = (crewId: string, rest: string) => `/api/crews/${encodeURIComponent(crewId)}/${rest}`;

export const dispatchApi = {
  targets: () => get<CrewTarget[]>("/api/crews/targets"),
  assign: (crewId: string, target: Pick<CrewTarget, "kind" | "target_id">) =>
    post<Result>(path(crewId, "assignments"), { target_kind: target.kind, target_id: target.target_id }),
  sign: (crewId: string, decision: "approve" | "reject", reason?: string) =>
    post<Result>(path(crewId, "assignment/sign"), { decision, reason: reason ?? null }),
  withdraw: (crewId: string) => post<Result>(path(crewId, "assignment/withdraw")),
  move: (crewId: string, move: CrewMove, blockReason?: BlockReason) =>
    post<Result>(path(crewId, "status"), { move, block_reason: blockReason ?? null }),
};

export const BLOCK_REASON: Record<BlockReason, string> = {
  road_closed: "Road closed",
  wind_above_bucket_limit: "Wind too strong for bucket trucks",
  safety_hold: "Safety hold",
  awaiting_material: "Waiting for material",
  awaiting_switching: "Waiting for switching",
};

const STATUS_LABEL: Record<CrewItem["status"], string> = {
  available: "Available",
  staged: "Staged",
  enroute: "On the way",
  onsite: "On site",
  blocked: "Blocked",
  done: "Done",
  off_shift: "Off shift",
};

/** The one plain status a person reads: a pending sign-off or a signed assignment shows before the field status. */
export function crewStatusLabel(c: CrewItem, viewerFunction?: string): string {
  const a = c.assignment;
  if (c.status === "blocked") return STATUS_LABEL.blocked;
  if (a?.state === "proposed")
    return a.required_function === viewerFunction
      ? "Waiting for you"
      : `Waiting for ${FUNCTION_LABEL[a.required_function]}`;
  if (a?.state === "assigned" && c.status === "available") return "Assigned";
  return STATUS_LABEL[c.status];
}

export const MENU_LABEL: Record<CrewAction, string> = {
  assign: "Assign…",
  sign: "Sign assignment",
  reject: "Reject assignment",
  withdraw: "Withdraw assignment",
  enroute: "Mark on the way",
  onsite: "Mark on site",
  staged: "Mark staged",
  block: "Mark blocked…",
  unblock: "Clear block",
  release: "Release crew",
};

export const useCrewTargets = (enabled: boolean) =>
  useQuery({ queryKey: ["crews", "targets"], queryFn: dispatchApi.targets, enabled });

function failure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "You can't do that with this crew.";
    if (error.status === 409) return "The crew changed. Check it and try again.";
    return error.message;
  }
  return "That didn't work. Try again.";
}

type Command =
  | { kind: "assign"; target: CrewTarget }
  | { kind: "reject"; note: string }
  | { kind: "sign" | "withdraw" | "enroute" | "onsite" | "staged" | "unblock" | "release" }
  | { kind: "block"; reason: BlockReason };

function run(crewId: string, cmd: Command): Promise<Result> {
  switch (cmd.kind) {
    case "assign":
      return dispatchApi.assign(crewId, cmd.target);
    case "sign":
      return dispatchApi.sign(crewId, "approve");
    case "reject":
      return dispatchApi.sign(crewId, "reject", cmd.note);
    case "withdraw":
      return dispatchApi.withdraw(crewId);
    case "block":
      return dispatchApi.move(crewId, "blocked", cmd.reason);
    default:
      return dispatchApi.move(crewId, cmd.kind);
  }
}

function confirmation(crewId: string, cmd: Command): string {
  const crew = crewName(crewId);
  switch (cmd.kind) {
    case "assign":
      return `${crew} assigned to ${cmd.target.label}. Waiting for sign-off.`;
    case "sign":
      return `Signed. ${crew} is assigned.`;
    case "reject":
      return `Rejected. ${crew} stays available.`;
    case "withdraw":
      return "Assignment withdrawn.";
    case "block":
      return `${crew} marked blocked: ${BLOCK_REASON[cmd.reason].toLowerCase()}.`;
    case "unblock":
      return `Block cleared for ${crew}.`;
    case "release":
      return `${crew} released and available.`;
    default:
      return `${crew} marked ${MENU_LABEL[cmd.kind].replace("Mark ", "")}.`;
  }
}

/** Every dispatch change: the server decides, the roster and the decision pane refetch, a toast confirms. */
export function useDispatch(crewId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (cmd: Command) => run(crewId, cmd),
    onSuccess: (_res, cmd) => toast.success(confirmation(crewId, cmd)),
    onError: (error) => toast.error(failure(error)),
    onSettled: () => qc.invalidateQueries({ queryKey: ["crews"] }),
  });
}
