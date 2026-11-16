import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getApiKey, setApiKey } from "./api.js";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [agent, setAgent] = useState(null);
  const [loading, setLoading] = useState(Boolean(getApiKey()));

  const refresh = useCallback(async () => {
    try {
      setAgent(await api.me());
    } catch {
      setApiKey(null);
      setAgent(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (getApiKey()) refresh(); }, [refresh]);

  const login = async (key) => {
    setApiKey(key.trim());
    setLoading(true);
    await refresh();
    if (!getApiKey()) throw new Error("That API key was not accepted.");
  };
  const logout = () => { setApiKey(null); setAgent(null); };

  return <AuthContext.Provider value={{ agent, loading, login, logout, refresh }}>{children}</AuthContext.Provider>;
}
