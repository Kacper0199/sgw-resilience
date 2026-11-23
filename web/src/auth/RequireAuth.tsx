import { Navigate, Outlet, useLocation } from "react-router";
import { PhaseProvider } from "@/lib/PhaseProvider";
import { OpsStreamProvider } from "@/sse/OpsStreamProvider";
import { useMe } from "./useSession";

export function RequireAuth() {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) {
    return (
      <div role="status" className="grid h-full place-items-center text-[13px] text-muted">
        Signing you in…
      </div>
    );
  }
  if (!me.data) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return (
    <OpsStreamProvider key={me.data.user_id}>
      <PhaseProvider>
        <Outlet />
      </PhaseProvider>
    </OpsStreamProvider>
  );
}
