import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Inbox,
  ListChecks,
  UploadCloud,
  Building2,
  Mailbox,
  ShieldCheck,
  Users,
  UsersRound,
  Plug,
  UserCircle,
  Receipt,
  Route as RouteIcon,
} from "lucide-react";
import { cn } from "../../lib/utils";

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard", end: true },
  { to: "/inbox", icon: Inbox, label: "Inbox" },
  { to: "/review", icon: ListChecks, label: "Review" },
  { to: "/upload", icon: UploadCloud, label: "Upload" },
];

const SETTINGS = [
  { to: "/settings/organizations", icon: Building2, label: "Organizations" },
  { to: "/settings/mailboxes", icon: Mailbox, label: "Mailboxes" },
  { to: "/settings/providers", icon: ShieldCheck, label: "Providers" },
  { to: "/settings/routing", icon: RouteIcon, label: "Org routing" },
  { to: "/settings/clients", icon: Users, label: "Sub-Clients" },
  { to: "/settings/connectors", icon: Plug, label: "Connectors" },
  { to: "/settings/users", icon: UsersRound, label: "Users" },
  { to: "/settings/account", icon: UserCircle, label: "Account" },
];

export function Sidebar() {
  return (
    <aside className="w-60 shrink-0 border-r border-border bg-card hidden md:flex md:flex-col">
      <div className="h-14 flex items-center gap-2 px-4 border-b border-border">
        <div className="h-7 w-7 rounded bg-primary/15 text-primary flex items-center justify-center">
          <Receipt className="h-4 w-4" />
        </div>
        <div className="font-semibold tracking-tight">Belege-Hub</div>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
        {NAV.map((n) => (
          <Item key={n.to} {...n} />
        ))}
        <div className="pt-4 pb-1 px-2 text-[10px] uppercase tracking-wider text-muted-foreground">Settings</div>
        {SETTINGS.map((n) => (
          <Item key={n.to} {...n} />
        ))}
      </nav>
      <div className="p-3 text-[11px] text-muted-foreground border-t border-border">
        <kbd className="px-1 py-0.5 rounded bg-muted text-[10px]">⌘K</kbd> commands ·
        <kbd className="px-1 py-0.5 rounded bg-muted text-[10px] ml-1">g i</kbd> inbox
      </div>
    </aside>
  );
}

function Item({ to, icon: Icon, label, end }: { to: string; icon: any; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "group flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors",
          isActive && "bg-accent text-foreground"
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
    </NavLink>
  );
}
