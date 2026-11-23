import { Moon, Sun, TriangleAlert } from "lucide-react";
import { type FormEvent, lazy, Suspense, useEffect, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { useTheme } from "@/app/layout/useTheme";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { loginErrorMessage } from "./loginError";
import { PasswordField } from "./PasswordField";
import { SgwMark } from "./SgwMark";
import { UserIdField } from "./UserIdField";
import { useAuthConfig, useLogin, useMe } from "./useSession";
import "./login.css";

const DemoPasswordNote = lazy(() => import("./PersonChooser").then((m) => ({ default: m.DemoPasswordNote })));

export function LoginPage() {
  const me = useMe();
  const config = useAuthConfig();
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const [theme, toggleTheme] = useTheme();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [chooserOpen, setChooserOpen] = useState(false);
  const [picks, setPicks] = useState(0);
  const [missing, setMissing] = useState<string | null>(null);
  const submitRef = useRef<HTMLButtonElement>(null);
  const demo = config.data?.demo_mode === true;
  const demoPassword = (demo && config.data?.demo_password) || null;

  useEffect(() => {
    if (picks === 0) return;
    if (demoPassword) submitRef.current?.focus();
    else document.getElementById("password")?.focus();
  }, [picks, demoPassword]);

  if (me.data && !login.isPending && !location.state?.switching) return <Navigate to={from} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!userId.trim() || !password) {
      setMissing(userId.trim() ? "Enter your password." : "Choose a person or enter a user ID.");
      document.getElementById(userId.trim() ? "password" : "user-id")?.focus();
      return;
    }
    login.mutate(
      { user_id: userId.trim(), password },
      { onSuccess: () => navigate(from, { replace: true }) },
    );
  };
  const pick = (id: string) => {
    setUserId(id);
    setPassword(demoPassword ?? "");
    setMissing(null);
    login.reset();
    setPicks((n) => n + 1);
  };
  const failure = missing ?? loginErrorMessage(login.error);
  const describedBy =
    [failure && "login-error", demoPassword && "demo-note"].filter(Boolean).join(" ") || undefined;

  return (
    <div className="lg-root">
      <div className="lg-glow" aria-hidden>
        <i className="lg-navy" />
        <i className="lg-blue" />
        <i className="lg-teal" />
        <i className="lg-violet" />
      </div>
      <header className="relative flex justify-end px-6 py-4 max-[520px]:px-3 max-[520px]:py-2">
        <TooltipProvider>
          <IconButton
            label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            icon={theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
            onClick={toggleTheme}
            tooltipSide="bottom"
            className="size-10 rounded-full text-ink-2 hover:bg-surface-3"
          />
        </TooltipProvider>
      </header>
      <main className="relative flex flex-1 flex-col items-center px-4 pb-6">
        <div className="mt-[min(2vh,16px)] text-center max-[520px]:mt-0">
          <SgwMark className="mx-auto mb-3.5 size-[60px] max-[520px]:size-[52px]" />
          <p className="m-0 text-[14px] leading-[1.43] font-semibold tracking-[0.01em] text-ink-2">
            SGW Resilience
          </p>
          <h1 className="m-0 mt-[18px] text-[34px] leading-[1.18] font-semibold tracking-[-0.02em] max-[520px]:text-[28px]">
            Sign in
          </h1>
          <p className="m-0 mt-2 text-[16px] leading-normal text-ink-2">
            One decision queue for power and water during a storm.
          </p>
        </div>
        <form
          onSubmit={submit}
          aria-label="Sign in"
          noValidate
          className="lg-card relative mt-7 w-full max-w-[440px] rounded-2xl border border-hair bg-surface p-7 max-[520px]:mt-5 max-[520px]:rounded-[14px] max-[520px]:p-5"
        >
          <div className="flex flex-col gap-4">
            <UserIdField
              value={userId}
              onChange={(v) => {
                setUserId(v);
                setMissing(null);
              }}
              demo={demo}
              invalid={failure !== null}
              chooserOpen={chooserOpen}
              onChooserOpenChange={setChooserOpen}
              onPick={pick}
            />
            <PasswordField
              value={password}
              onChange={(v) => {
                setPassword(v);
                setMissing(null);
              }}
              invalid={failure !== null}
              describedBy={describedBy}
            />
          </div>
          {failure && (
            <p
              id="login-error"
              role="alert"
              className="m-0 mt-3 flex items-start gap-2 text-[13px] leading-[1.35] font-medium text-crit"
            >
              <TriangleAlert className="size-4 shrink-0" aria-hidden />
              {failure}
            </p>
          )}
          <Button
            ref={submitRef}
            type="submit"
            variant="primary"
            loading={login.isPending}
            className="mt-5 h-11 w-full rounded-lg text-[14px]"
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </Button>
          {demoPassword && (
            <Suspense fallback={<p className="m-0 mt-2.5 min-h-4" />}>
              <DemoPasswordNote id="demo-note" password={demoPassword} />
            </Suspense>
          )}
          <p className="m-0 mt-5 border-t border-hair pt-4 text-center text-xs leading-[1.33] text-muted">
            {demo ? "Demo users and synthetic data. " : ""}Actions are recorded in the audit log.
          </p>
        </form>
        {demo && (
          <div className="mt-5 flex justify-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-hair bg-surface px-3 py-1.5 text-xs leading-[1.33] text-ink-2">
              <i className="size-1.5 shrink-0 rounded-full bg-blue" aria-hidden />
              Replay of Hurricane Helene, 23 Sep – 6 Oct 2024, synthetic SGW data
            </span>
          </div>
        )}
      </main>
    </div>
  );
}
