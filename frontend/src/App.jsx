import React from "react";
import Container from "react-bootstrap/Container";
import Alert from "react-bootstrap/Alert";
import { Navigate, Route, Routes } from "react-router-dom";

import AppNavbar from "./components/AppNavbar";
import Loader from "./components/Loader";
import { useAuth } from "./context/AuthContext";
import DocumentsPage from "./pages/DocumentsPage";
import LoginPage from "./pages/LoginPage";
import ProfilePage from "./pages/ProfilePage";
import PublicLinkPage from "./pages/PublicLinkPage";
import RequestsPage from "./pages/RequestsPage";
import UsersPage from "./pages/UsersPage";

function ProtectedRoute({ children }) {
  //Защищенные страницы ждут завершения проверки cookie перед редиректом на вход.
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return <Loader />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

function SuperadminRoute({ children }) {
  //Раздел управления пользователями открыт только пользователю с флагом суперадмина.
  const { user } = useAuth();
  if (!user?.is_superadmin) {
    return <Alert variant="warning">Раздел доступен только суперадмину.</Alert>;
  }
  return children;
}

export default function App() {
  const { isAuthenticated, user, logout, loading } = useAuth();

  if (loading) {
    return <Loader />;
  }

  if (!isAuthenticated) {
    return (
      <Container className="pb-4">
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/links/public/:token" element={<PublicLinkPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Container>
    );
  }

  return (
    <>
      <Routes>
        <Route path="/links/public/:token" element={<PublicLinkPage />} />
        <Route
          path="*"
          element={
            <>
              <AppNavbar isSuperadmin={Boolean(user?.is_superadmin)} user={user} onLogout={logout} />
              <Container className="pb-4">
                <Routes>
                  <Route
                    path="/profile"
                    element={
                      <ProtectedRoute>
                        <ProfilePage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/documents"
                    element={
                      <ProtectedRoute>
                        <DocumentsPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/requests"
                    element={
                      <ProtectedRoute>
                        <RequestsPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/users"
                    element={
                      <ProtectedRoute>
                        <SuperadminRoute>
                          <UsersPage />
                        </SuperadminRoute>
                      </ProtectedRoute>
                    }
                  />
                  <Route path="*" element={<Navigate to="/profile" replace />} />
                </Routes>
              </Container>
            </>
          }
        />
      </Routes>
    </>
  );
}
