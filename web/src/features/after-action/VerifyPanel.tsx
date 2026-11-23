import { FlaskConical, Loader, ShieldCheck, ShieldX } from "lucide-react";
import { useMe } from "@/auth/useSession";
import { InfoTip, SourceLine } from "@/components/sgw";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { count } from "./format";
import type { AuditVerifyResult, TamperDemo } from "./types";
import { useTamperDemo, useVerify } from "./useAfterAction";

function failure(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Your role can't run this check.";
    if (err.status === 429) return `${err.message}. The last result still stands.`;
    if (err.status === 404 || err.status === 501) return "This check isn't available yet.";
  }
  return "The check couldn't run. Try again in a moment.";
}

type ChainFacts = Pick<AuditVerifyResult, "ok" | "checked_to_seq" | "first_bad_seq">;

function ResultLine({ result }: { result: ChainFacts }) {
  return result.ok ? (
    <p className="m-0 flex items-center gap-2 text-[14px] font-medium" data-testid="verify-result">
      <ShieldCheck className="size-4 shrink-0 text-ok" aria-hidden />
      The audit log passed its check. Every entry matches its fingerprint through entry{" "}
      {count(result.checked_to_seq)}.
    </p>
  ) : (
    <p className="m-0 flex items-center gap-2 text-[14px] font-medium text-crit" data-testid="verify-result">
      <ShieldX className="size-4 shrink-0" aria-hidden />
      The audit log fails its check. The first bad entry is {count(result.first_bad_seq ?? 0)}.
    </p>
  );
}

function ResultFacts({ result }: { result: AuditVerifyResult }) {
  const facts = [
    { label: "Checked through entry", value: count(result.checked_to_seq) },
    {
      label: "First bad entry",
      info: "first_bad_seq" as const,
      value: result.first_bad_seq === null ? "None" : count(result.first_bad_seq),
    },
    {
      label: "Independent check",
      info: "notary" as const,
      value: result.notary === "signed" ? "Confirmed" : "Not confirmed",
    },
    {
      label: "Last confirmed entry",
      value: result.signed_head_seq === null ? "None yet" : count(result.signed_head_seq),
    },
  ];
  return (
    <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-hair pt-3">
      {facts.map((f) => (
        <div key={f.label} className="min-w-0">
          <dt className="flex h-5 items-center gap-1 text-[12px] font-semibold text-muted">
            {f.label}
            {f.info && <InfoTip term={f.info} />}
          </dt>
          <dd className="m-0 text-[14px] font-medium tnum">{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function TamperResult({ demo }: { demo: TamperDemo }) {
  return (
    <div className="border-t border-hair pt-3" data-testid="tamper-result">
      <p className="m-0 flex items-center gap-2 text-[13px] font-semibold">
        <FlaskConical className="size-4 shrink-0 text-muted" aria-hidden />
        Test on a copy. The real audit log wasn't changed.
      </p>
      <p className="m-0 mt-1.5 text-[14px]">
        Entry <span className="tnum font-semibold">{count(demo.tampered_seq)}</span> was changed on the copy.
        The check fails at entry{" "}
        <span className="tnum font-semibold">{count(demo.result.first_bad_seq ?? demo.tampered_seq)}</span>.
        Entries from <span className="tnum">{count(demo.untrusted_from_seq)}</span> on wouldn't be trusted.
      </p>
    </div>
  );
}

/** Check the real audit log and, on request, show what tampering looks like on a copy. Shared by After-action and Admin. */
export function VerifyPanel({ known }: { known?: ChainFacts }) {
  const verify = useVerify();
  const tamper = useTamperDemo();
  const role = useMe().data?.function;
  const canTamper = role === "platform" || role === "audit";
  return (
    <div className="flex flex-col gap-3" data-testid="verify-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => verify.mutate()} disabled={verify.isPending}>
          {verify.isPending ? <Loader className="animate-spin" aria-hidden /> : <ShieldCheck aria-hidden />}
          {verify.isPending ? "Checking…" : "Check audit log"}
        </Button>
        <InfoTip term="verify_chain" />
        {canTamper && (
          <>
            <Button variant="secondary" onClick={() => tamper.mutate()} disabled={tamper.isPending}>
              <FlaskConical aria-hidden />
              Run tamper test
            </Button>
            <InfoTip term="tamper_demo" />
          </>
        )}
      </div>
      {!verify.data &&
        !verify.isPending &&
        !verify.isError &&
        (known ? (
          <div className="flex flex-col gap-1" data-testid="known-result">
            <ResultLine result={known} />
            <SourceLine>Result from the latest review. Run the check again for a fresh one.</SourceLine>
          </div>
        ) : (
          <SourceLine>Not checked yet. The check reads the whole audit log.</SourceLine>
        ))}
      {verify.isError && (
        <p role="alert" className="m-0 text-[13px] text-crit">
          {failure(verify.error)}
        </p>
      )}
      {verify.data && (
        <div className="flex flex-col gap-2" aria-live="polite">
          <ResultLine result={verify.data} />
          <ResultFacts result={verify.data} />
        </div>
      )}
      {tamper.isError && (
        <p role="alert" className="m-0 text-[13px] text-crit">
          {failure(tamper.error)}
        </p>
      )}
      {tamper.data && <TamperResult demo={tamper.data} />}
    </div>
  );
}
