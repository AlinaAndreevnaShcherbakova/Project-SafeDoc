import React from "react";
import Badge from "react-bootstrap/Badge";
import Container from "react-bootstrap/Container";
import Nav from "react-bootstrap/Nav";
import Navbar from "react-bootstrap/Navbar";
import { LogOut } from "lucide-react";
import { NavLink } from "react-router-dom";
import AppButton from "./ui/AppButton";

export default function AppNavbar({ isSuperadmin, user, onLogout }) {
  const roleLabel = isSuperadmin
    ? "Суперадминистратор"
    : user?.role === "access_manager"
      ? "Менеджер доступа"
      : "Пользователь";

  return (
    <Navbar bg="dark" variant="dark" expand="lg" className="mb-3">
      <Container fluid="lg">
        <Navbar.Brand>SafeDoc</Navbar.Brand>
        <Navbar.Toggle aria-controls="main-nav" />
        <Navbar.Collapse id="main-nav">
          <Nav className="me-auto">
            <Nav.Link as={NavLink} to="/profile">
              Личный кабинет
            </Nav.Link>
            <Nav.Link as={NavLink} to="/documents">
              Хранилище файлов
            </Nav.Link>
            <Nav.Link as={NavLink} to="/requests">
              Заявки
            </Nav.Link>
            {isSuperadmin && (
              <Nav.Link as={NavLink} to="/users">
                Пользователи
              </Nav.Link>
            )}
          </Nav>
          <div className="d-flex align-items-center gap-2">
            <Badge bg="secondary">{roleLabel}</Badge>
            <span className="text-light small">{user?.login || "Профиль"}</span>
            <AppButton size="sm" variant="outline" icon={LogOut} onClick={onLogout}>Выйти</AppButton>
          </div>
        </Navbar.Collapse>
      </Container>
    </Navbar>
  );
}
