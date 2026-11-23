import {
  BookOpenText,
  ClipboardCheck,
  CloudLightning,
  Droplets,
  FileText,
  Gauge,
  HardHat,
  HeartPulse,
  History,
  type LucideIcon,
  MapIcon,
  MessageCircle,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router";
import type { AnswerLink } from "../../agent-panel/types";

const BY_PATH: readonly (readonly [RegExp, LucideIcon])[] = [
  [/^\/map/, MapIcon],
  [/^\/water/, Droplets],
  [/^\/crews/, HardHat],
  [/^\/forecast/, CloudLightning],
  [/^\/readiness/, Gauge],
  [/^\/after-action/, History],
  [/^\/brief/, FileText],
  [/^\/health/, HeartPulse],
  [/^\/admin/, Settings2],
  [/^\/notifications/, MessageCircle],
  [/^\/help|^\/glossary/, BookOpenText],
  [/^\/audit|^\/safety/, ShieldCheck],
  [/^\/(decisions|\?|$)/, ClipboardCheck],
];

export const iconForHref = (href: string): LucideIcon =>
  BY_PATH.find(([re]) => re.test(href))?.[1] ?? FileText;

/** Only a path inside the platform is a link; anything else the server might send stays out. */
export const isInternal = (href: string): boolean => /^\/(?!\/)/.test(href);

export const CHIP =
  "inline-flex h-8 max-w-full items-center gap-1.5 rounded-full border border-hair-strong bg-surface px-3 text-left text-[13px] leading-none transition-colors duration-120 hover:bg-blue-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:opacity-45";

/** Pages the answer sends the reader to: chips that open inside the app. The server already left out what the role cannot open. */
export function AnswerLinks({ links }: { links: readonly AnswerLink[] }) {
  const shown = links.filter((l) => isInternal(l.href));
  if (shown.length === 0) return null;
  return (
    <ul
      aria-label="Open in the platform"
      className="m-0 flex list-none flex-wrap gap-2 p-0"
      data-testid="answer-links"
    >
      {shown.map((l) => {
        const Icon = iconForHref(l.href);
        return (
          <li key={`${l.href}|${l.label}`} className="min-w-0 max-w-full">
            <Link to={l.href} className={`${CHIP} font-medium text-blue-ink`} data-testid="answer-link">
              <Icon aria-hidden className="size-3.5 shrink-0 text-muted" strokeWidth={1.75} />
              <span className="truncate">{l.label}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
