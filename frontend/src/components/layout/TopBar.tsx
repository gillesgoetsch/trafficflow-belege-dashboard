import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Moon, Search, Sun, LogOut, UserCircle } from "lucide-react";
import { api } from "../../lib/api";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { useUi } from "../../store/ui";
import { useAuth } from "../../store/auth";
import { useNavigate } from "react-router-dom";
import type { Organization } from "../../types";

export function TopBar() {
  const { theme, toggleTheme, setPaletteOpen, selectedOrgId, setSelectedOrgId } = useUi();
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const navigate = useNavigate();

  const { data: orgs } = useQuery<Organization[]>({
    queryKey: ["orgs"],
    queryFn: () => api("/organizations"),
  });

  useEffect(() => {
    if (orgs && orgs.length > 0 && !selectedOrgId) {
      setSelectedOrgId(orgs[0].id);
    }
  }, [orgs, selectedOrgId, setSelectedOrgId]);

  return (
    <header className="h-14 shrink-0 border-b border-border bg-card/80 backdrop-blur z-20 flex items-center px-3 sm:px-4 gap-3">
      <button
        onClick={() => setPaletteOpen(true)}
        className="group flex-1 max-w-md flex items-center gap-2 h-9 px-3 rounded-md border border-input text-sm text-muted-foreground hover:text-foreground hover:border-ring transition-colors"
      >
        <Search className="h-4 w-4" />
        <span>Search or jump…</span>
        <span className="ml-auto text-[10px] tracking-wide opacity-60">
          <kbd className="px-1 py-0.5 rounded bg-muted">⌘K</kbd>
        </span>
      </button>

      <div className="hidden md:block w-56">
        <Select
          value={selectedOrgId ? String(selectedOrgId) : undefined}
          onValueChange={(v) => setSelectedOrgId(parseInt(v))}
        >
          <SelectTrigger>
            <SelectValue placeholder="All organizations" />
          </SelectTrigger>
          <SelectContent>
            {(orgs ?? []).map((o) => (
              <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="toggle theme">
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon"><UserCircle className="h-5 w-5" /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuLabel className="truncate">{user?.email}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => navigate("/settings/account")}>Account & security</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => navigate("/onboarding")}>Onboarding wizard</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={async () => { await logout(); navigate("/login"); }}>
            <LogOut className="h-4 w-4 mr-2" /> Logout
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
