import {
  Activity,
  BellRing,
  BookOpenText,
  ClipboardCheck,
  CloudLightning,
  Droplets,
  FileText,
  Gauge,
  HardHat,
  HelpCircle,
  History,
  type LucideIcon,
  MapIcon,
  MessageSquareText,
  Settings,
} from "lucide-react";
import type { Module } from "@/contracts/vocab.gen";

export type NavGroup = "respond" | "inform" | "user";

export interface ModuleDef {
  key: Module | "notifications" | "help";
  label: string;
  path: string;
  icon: LucideIcon;
  group: NavGroup;
  summary: string;
}

export const MODULES: readonly ModuleDef[] = [
  {
    key: "decisions",
    label: "Decisions",
    path: "/",
    icon: ClipboardCheck,
    group: "respond",
    summary: "Open decisions and their deadlines.",
  },
  {
    key: "map",
    label: "Map",
    path: "/map",
    icon: MapIcon,
    group: "respond",
    summary: "Assets, storm track and county risk.",
  },
  {
    key: "forecast",
    label: "Forecast",
    path: "/forecast",
    icon: CloudLightning,
    group: "respond",
    summary: "Outage forecast, what changed, and what-ifs.",
  },
  {
    key: "crews",
    label: "Crews",
    path: "/crews",
    icon: HardHat,
    group: "respond",
    summary: "Crews, staging yards, and crew plans.",
  },
  {
    key: "water",
    label: "Water",
    path: "/water",
    icon: Droplets,
    group: "respond",
    summary: "Pressure, boil-water advisories, and sensor alerts.",
  },
  {
    key: "ask",
    label: "Ask AI",
    path: "/ask",
    icon: MessageSquareText,
    group: "inform",
    summary: "Ask about the storm response. Answers cite sources.",
  },
  {
    key: "brief",
    label: "Briefing",
    path: "/brief",
    icon: FileText,
    group: "inform",
    summary: "Current situation at a glance.",
  },
  {
    key: "after_action",
    label: "After-action",
    path: "/after-action",
    icon: History,
    group: "inform",
    summary: "What was decided, when, and by whom.",
  },
  {
    key: "health",
    label: "System health",
    path: "/health",
    icon: Activity,
    group: "inform",
    summary: "Data, models, AI activity, and stop controls.",
  },
  {
    key: "readiness",
    label: "Readiness",
    path: "/readiness",
    icon: Gauge,
    group: "inform",
    summary: "Pre-season checks with owners and due dates.",
  },
  {
    key: "notifications",
    label: "Notifications",
    path: "/notifications",
    icon: BellRing,
    group: "user",
    summary: "Alerts addressed to you.",
  },
  {
    key: "admin",
    label: "Admin",
    path: "/admin",
    icon: Settings,
    group: "user",
    summary: "Users, policies, integrations, and AI settings.",
  },
  {
    key: "help",
    label: "Help",
    path: "/help",
    icon: HelpCircle,
    group: "user",
    summary: "Definitions of the terms used here.",
  },
];

export const GROUP_LABEL: Record<NavGroup, string> = {
  respond: "Respond",
  inform: "Inform",
  user: "Your account",
};

/** The five entries of the bottom tab bar below 820 px; the rest sit under "More". */
export const TAB_BAR_KEYS: readonly ModuleDef["key"][] = ["decisions", "map", "water", "brief", "ask"];

export const HELP_ICON = BookOpenText;
