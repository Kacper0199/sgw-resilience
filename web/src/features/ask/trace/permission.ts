import { useMe } from "@/auth/useSession";
import type { Me } from "@/lib/api";

const TRACE_FUNCTIONS = new Set(["platform", "data", "audit"]);

/** Who sees how an answer was made: the platform admin, the data and models owner and the auditor. Everyone else keeps the folded step line. */
export const canSeeTrace = (me: Me | null | undefined): boolean =>
  me !== null && me !== undefined && TRACE_FUNCTIONS.has(me.function);

export const useCanSeeTrace = (): boolean => canSeeTrace(useMe().data);
