import { Link } from "react-router";
import { VerifyPanel } from "@/features/after-action/VerifyPanel";

export function AuditTab() {
  return (
    <div className="flex max-w-[820px] flex-col gap-4 px-8 pb-8">
      <p className="m-0 text-[14px] text-ink-2">
        Check that nothing in the audit log was changed after the fact. Who did what is in the{" "}
        <Link to="/after-action?tab=timeline" className="text-blue-ink underline underline-offset-2">
          after-action timeline
        </Link>
        .
      </p>
      <VerifyPanel />
    </div>
  );
}
