import { useCan } from "@/auth/usePermissions";
import { MODULES, type ModuleDef } from "../modules";

/** The modules this person can open: Admin only for those the API lets read it. */
export function useNavModules(): readonly ModuleDef[] {
  const admin = useCan("admin");
  return admin ? MODULES : MODULES.filter((m) => m.key !== "admin");
}
