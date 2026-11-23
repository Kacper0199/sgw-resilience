import { Link } from "react-router";
import { useMe } from "@/auth/useSession";
import { crewName } from "@/lib/names";
import { crewStatusLabel } from "./dispatch";
import { useCrewList } from "./useCrews";

/** The crews assigned to a decision, on its pane: one quiet line, nothing when no crew is assigned. */
export function AssignedCrews({ caseId }: { caseId: string }) {
  const me = useMe().data;
  const crews = (useCrewList().data ?? []).filter(
    (c) => c.assignment?.target_kind === "decision" && c.assignment.target_id === caseId,
  );
  if (crews.length === 0) return null;
  return (
    <p className="m-0 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[13px]" data-testid="assigned-crews">
      <span className="font-semibold text-ink-2">Crews</span>
      {crews.map((c) => (
        <span key={c.crew_id} className="inline-flex items-baseline gap-1.5">
          <Link to={`/crews?crew=${encodeURIComponent(c.crew_id)}`} className="text-blue-ink hover:underline">
            {crewName(c.crew_id)}
          </Link>
          <span className="text-muted">{crewStatusLabel(c, me?.function)}</span>
        </span>
      ))}
    </p>
  );
}
