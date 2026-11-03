import { useEffect, useState } from "react";
import { settingsApi } from "../services/api";
import { useLive } from "../context/LiveContext";
import { useAction } from "./useApi";

/** Local editable copy of runtime settings with dirty tracking and a save that sends only changed keys. */
export function useSettings(keys) {
  const { toast } = useLive();
  const [server, setServer] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const { busy, run } = useAction(toast);

  const load = async () => {
    try {
      const s = await settingsApi.get();
      setServer(s);
      setForm(s);
      setError(null);
    } catch (e) { setError(e); }
  };
  useEffect(() => { load(); }, []);

  const changed = form && server ? keys.filter((k) => JSON.stringify(form[k]) !== JSON.stringify(server[k])) : [];
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const save = () => run("save", async () => {
    const s = await settingsApi.update(Object.fromEntries(changed.map((k) => [k, form[k]])));
    setServer(s);
    setForm(s);
  }, "Settings saved – applied to the running pipeline");
  const revert = () => setForm(server);

  return { form, set, save, revert, dirty: changed.length > 0, busy: busy === "save", error, reload: load };
}
