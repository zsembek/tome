import { useState } from "react";
import { BookOpen } from "lucide-react";
import { auth, AuthStatus } from "../lib/api";
import { Button, Input } from "./ui";

export function Login({ status, onAuthed }: { status: AuthStatus; onAuthed: () => void }) {
  const bootstrap = status.needs_bootstrap;
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [pass2, setPass2] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setErr("");
    if (!email.trim() || !pass) { setErr("Enter email and password"); return; }
    if (bootstrap) {
      if (pass.length < 8) { setErr("Password must be at least 8 characters"); return; }
      if (pass !== pass2) { setErr("Passwords do not match"); return; }
    }
    setBusy(true);
    try {
      if (bootstrap) await auth.bootstrap(email.trim(), pass);
      else await auth.login(email.trim(), pass);
      onAuthed();
    } catch (e: any) {
      setErr(e.message || "Sign-in failed");
    } finally { setBusy(false); }
  }

  return (
    <div className="h-full flex items-center justify-center">
      <div className="w-80 card space-y-3">
        <div className="flex items-center gap-2 justify-center mb-1">
          <BookOpen className="w-6 h-6 text-acc" />
          <span className="font-semibold tracking-wide text-lg">TOME</span>
        </div>
        <h2 className="text-center font-medium">
          {bootstrap ? "Create the first administrator" : "Sign in"}
        </h2>
        {bootstrap && <p className="muted text-xs text-center">No users yet — set up an administrator account.</p>}
        <Input placeholder="email" value={email} autoFocus
               onChange={(e) => setEmail(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && !bootstrap && submit()} />
        <Input type="password" placeholder="password" value={pass}
               onChange={(e) => setPass(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && !bootstrap && submit()} />
        {bootstrap && (
          <Input type="password" placeholder="repeat password" value={pass2}
                 onChange={(e) => setPass2(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && submit()} />
        )}
        {err && <div className="text-red-400 text-sm">{err}</div>}
        <Button primary className="w-full" onClick={submit}>
          {busy ? "…" : bootstrap ? "Create & sign in" : "Sign in"}
        </Button>
      </div>
    </div>
  );
}
