import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import { useUi } from "../../store/ui";
import { Inbox, LayoutDashboard, ListChecks, Settings, UploadCloud, Building2, Mailbox, ShieldCheck, Users, Plug, Sparkles } from "lucide-react";

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const navigate = useNavigate();

  const go = (path: string) => { setOpen(false); navigate(path); };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh] data-[state=open]:animate-fade-in"
    >
      <div className="absolute inset-0 bg-background/70 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-xl mx-4 rounded-xl border border-border bg-card shadow-2xl overflow-hidden">
        <Command className="w-full">
          <div className="flex items-center px-3 border-b border-border">
            <Sparkles className="h-4 w-4 text-muted-foreground mr-2" />
            <Command.Input
              placeholder="Type a command or search..."
              className="flex-1 h-12 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-[400px] overflow-auto p-2 text-sm">
            <Command.Empty className="px-3 py-6 text-center text-muted-foreground">No results.</Command.Empty>
            <Command.Group heading="Navigate">
              <Item icon={<LayoutDashboard className="h-4 w-4" />} onSelect={() => go("/")}>Dashboard <kbd>g d</kbd></Item>
              <Item icon={<Inbox className="h-4 w-4" />} onSelect={() => go("/inbox")}>Inbox <kbd>g i</kbd></Item>
              <Item icon={<ListChecks className="h-4 w-4" />} onSelect={() => go("/review")}>Review queue <kbd>g r</kbd></Item>
              <Item icon={<UploadCloud className="h-4 w-4" />} onSelect={() => go("/upload")}>Upload receipt <kbd>g u</kbd></Item>
              <Item icon={<Settings className="h-4 w-4" />} onSelect={() => go("/settings/organizations")}>Settings <kbd>g s</kbd></Item>
            </Command.Group>
            <Command.Group heading="Settings">
              <Item icon={<Building2 className="h-4 w-4" />} onSelect={() => go("/settings/organizations")}>Organizations</Item>
              <Item icon={<Mailbox className="h-4 w-4" />} onSelect={() => go("/settings/mailboxes")}>Mailboxes</Item>
              <Item icon={<ShieldCheck className="h-4 w-4" />} onSelect={() => go("/settings/providers")}>Providers & rules</Item>
              <Item icon={<Users className="h-4 w-4" />} onSelect={() => go("/settings/clients")}>Sub-clients</Item>
              <Item icon={<Plug className="h-4 w-4" />} onSelect={() => go("/settings/connectors")}>Connectors</Item>
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
