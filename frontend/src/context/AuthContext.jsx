import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  //Состояние авторизации хранится централизованно, чтобы страницы не дублировали проверку профиля.
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function bootstrapAuth() {
      try {
        const { data } = await api.get("/auth/me");
        setUser(data);
      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    }

    bootstrapAuth();
  }, []);

  useEffect(() => {
    const interceptorId = api.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error?.response?.status === 401) {
          setUser(null);
        }
        return Promise.reject(error);
      }
    );

    return () => {
      api.interceptors.response.eject(interceptorId);
    };
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      isAuthenticated: Boolean(user),
      async refreshMe() {
        try {
          const { data } = await api.get("/auth/me");
          setUser(data);
        } catch {
          setUser(null);
        }
      },
      async login(loginValue, password) {
        //После установки cookie профиль запрашивается сразу, чтобы обновить роли и меню.
        await api.post("/auth/login", { login: loginValue, password });
        const me = await api.get("/auth/me");
        setUser(me.data);
      },
      async logout() {
        try {
          await api.post("/auth/logout");
        } catch {
          //Даже при сетевой ошибке выхода локальное состояние авторизации очищается.
        }
        setUser(null);
      },
    }),
    [user, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
