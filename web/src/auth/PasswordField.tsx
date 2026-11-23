import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Props {
  value: string;
  onChange: (value: string) => void;
  invalid: boolean;
  describedBy?: string;
}

export function PasswordField({ value, onChange, invalid, describedBy }: Props) {
  const [shown, setShown] = useState(false);
  const Icon = shown ? EyeOff : Eye;
  return (
    <div>
      <Label htmlFor="password" className="mb-1.5 block text-[13px] leading-[1.35] font-semibold">
        Password
      </Label>
      <div className="relative">
        <Input
          id="password"
          name="password"
          type={shown ? "text" : "password"}
          autoComplete="current-password"
          value={value}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          onChange={(e) => onChange(e.target.value)}
          className="h-11 border-(--login-line) px-3 pe-[84px] text-[15px] hover:border-muted focus-visible:border-blue aria-invalid:shadow-[inset_0_0_0_1px_var(--crit)]"
          required
        />
        <button
          type="button"
          aria-label={shown ? "Hide password" : "Show password"}
          onClick={() => setShown((s) => !s)}
          className="absolute inset-y-0 end-0 inline-flex h-11 items-center gap-1.5 rounded-e-lg px-3 text-[13px] font-semibold text-blue-ink hover:bg-blue-soft"
        >
          <Icon className="size-4" aria-hidden />
          {shown ? "Hide" : "Show"}
        </button>
      </div>
    </div>
  );
}
