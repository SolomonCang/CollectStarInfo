import { useCallback, useEffect, useState } from "react";
import {
  changePassword as changePasswordRequest,
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
} from "../api";

export function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getCurrentUser()
      .then((result) => setUser(result.user))
      .catch((caught) => {
        if (caught.status !== 401) setError(caught.message);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (credentials) => {
    setError("");
    setLoading(true);
    try {
      const result = await loginRequest(credentials);
      setUser(result.user);
      return result.user;
    } catch (caught) {
      setError(caught.message);
      throw caught;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    setError("");
    try {
      await logoutRequest();
    } finally {
      setUser(null);
    }
  }, []);

  const changePassword = useCallback(async (payload) => {
    setError("");
    await changePasswordRequest(payload);
    const result = await getCurrentUser();
    setUser(result.user);
  }, []);

  return { user, loading, error, login, logout, changePassword };
}
