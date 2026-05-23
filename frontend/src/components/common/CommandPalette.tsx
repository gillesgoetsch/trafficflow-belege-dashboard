import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import { useUi } from "../../store/ui";
import { Inbox, LayoutDashboard, ListChecks, Settings, UploadCloud, Building2, Mailbox, ShieldCheck, Users, Plug, Receipt } from "lucide-react";

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const navigate = useNavigate();

  const go = (path: string) => { setOpen(false); navigate(path); };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Befehlspalette"
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh] data-[state=open]:animate-fade-in"
    >
      <div className="absolute inset-0 bg-background/70 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-xl mx-4 rounded-xl border border-border bg-card shadow-2xl overflow-hidden">
        <Command className="w-full">
          <div className="flex items-center px-3 border-b border-border">
            <Receipt className="h-4 w-4 text-muted-foreground mr-2" />
            <Command.Input
              placeholder="Befehl eingeben oder suchen…"
              className="flex-1 h-12 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-[400px] overflow-auto p-2 text-sm">
            <Command.Empty className="px-3 py-6 text-center text-muted-foreground">Keine Treffer.</Command.Empty>
            <Command.Group heading="Navigation">
              <Item icon={<LayoutDashboard className="h-4 w-4" />} onSelect={() => go("/")}>Übersicht <kbd>g d</kbd></Item>
              <Item icon={<Inbox className="h-4 w-4" />} onSelect={() => go("/inbox")}>Belege <kbd>g i</kbd></Item>
              <Item icon={<ListChecks className="h-4 w-4" />} onSelect={() => go("/review")}>Prüfung <kbd>g r</kbd></Item>
              <Item icon={<UploadCloud className="h-4 w-4" />} onSelect={() => go("/upload")}>Beleg hochladen <kbd>g u</kbd></Item>
              <Item icon={<Settings className="h-4 w-4" />} onSelect={() => go("/settings/organizations")}>Einstellungen <kbd>g s</kbd></Item>
            </Command.Group>
            <Command.Group heading="Einstellungen">
              <Item icon={<Building2 className="h-4 w-4" />} onSelect={() => go("/settings/organizations")}>Firmen</Item>
              <Item icon={<Mailbox className="h-4 w-4" />} onSelect={() => go("/settings/mailboxes")}>Postfächer</Item>
              <Item icon={<ShieldCheck className="h-4 w-4" />} onSelect={() => go("/settings/providers")}>Anbieter & Regeln</Item>
              <Item icon={<Users className="h-4 w-4" />} onSelect={() => go("/settings/clients")}>Mandanten</Item>
              <Item icon={<Plug className="h-4 w-4" />} onSelect={() => go("/settings/connectors")}>Connectoren</Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </Command.Dialog>
  );
}

function Item({ children, icon, onSelect }: { children: React.ReactNode; icon: React.ReactNode; onSelect: () => void }) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
    >
      {icon}
      <span className="flex-1 flex items-center justify-between">
        {children}
      </span>
    </Command.Item>
  );
}
