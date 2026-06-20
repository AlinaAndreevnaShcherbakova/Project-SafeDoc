import React, { useState } from "react";
import Alert from "react-bootstrap/Alert";
import Card from "react-bootstrap/Card";
import Form from "react-bootstrap/Form";
import Stack from "react-bootstrap/Stack";
import { KeyRound, Save } from "lucide-react";

import { api } from "../api/client";
import { useToast } from "../components/notifications/ToastProvider";
import AppButton from "../components/ui/AppButton";
import PasswordInput from "../components/ui/PasswordInput";
import { useAuth } from "../context/AuthContext";

const fieldLabels = {
  surname: "Фамилия",
  name: "Имя",
  middle_name: "Отчество",
  email: "Email",
  current_password: "Текущий пароль",
  new_password: "Новый пароль",
};

function formatValidationError(detailItem) {
  if (!detailItem || typeof detailItem !== "object") {
    return "";
  }

  const location = Array.isArray(detailItem.loc)
    ? detailItem.loc.filter((part) => part !== "body").map(String)
    : [];
  const fieldName = location[location.length - 1];
  const label = fieldLabels[fieldName] || fieldName;

  if (fieldName === "new_password" && detailItem.type === "string_too_short") {
    return "Новый пароль должен содержать не менее 8 символов";
  }
  if (fieldName === "current_password" && detailItem.type === "string_too_short") {
    return "Текущий пароль должен содержать не менее 8 символов";
  }
  if (detailItem.type === "string_pattern_mismatch" && ["surname", "name", "middle_name"].includes(fieldName)) {
    return `${label} должно содержать только буквы`;
  }

  if (typeof detailItem.msg === "string" && detailItem.msg.trim()) {
    return fieldName ? `${label}: ${detailItem.msg}` : detailItem.msg;
  }

  return "";
}

function getErrorMessage(err, fallback) {
  const detail = err?.response?.data?.detail;

  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail.map(formatValidationError).filter(Boolean);
    if (messages.length > 0) {
      return messages.join(" ");
    }
  }

  return fallback;
}

export default function ProfilePage() {
  const { user, refreshMe } = useAuth();
  const toast = useToast();
  const [form, setForm] = useState({
    surname: user?.surname || "",
    name: user?.name || "",
    middle_name: user?.middle_name || "",
    department: user?.department || "",
    position: user?.position || "",
    email: user?.email || "",
  });

  const [pwd, setPwd] = useState({ current_password: "", new_password: "" });
  const [profileError, setProfileError] = useState("");
  const [passwordError, setPasswordError] = useState("");

  function setField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function saveProfile(event) {
    event.preventDefault();
    setProfileError("");
    setPasswordError("");

    try {
      await api.patch("/auth/me", {
        surname: form.surname,
        name: form.name,
        middle_name: form.middle_name || null,
        email: form.email,
      });
      await refreshMe();
      toast.success("Профиль успешно обновлен");
    } catch (err) {
      const message = getErrorMessage(err, "Не удалось обновить профиль");
      setProfileError(message);
      toast.error(message);
    }
  }

  async function changePassword(event) {
    event.preventDefault();
    setProfileError("");
    setPasswordError("");

    try {
      await api.post("/auth/change-password", pwd);
      setPwd({ current_password: "", new_password: "" });
      toast.success("Пароль успешно изменен");
    } catch (err) {
      const message = getErrorMessage(err, "Не удалось изменить пароль");
      setPasswordError(message);
      toast.error(message);
    }
  }

  return (
    <Stack gap={3}>
      <Card>
        <Card.Body>
          <Card.Title>Личный кабинет</Card.Title>
          <Form onSubmit={saveProfile} className="mx-auto" style={{ maxWidth: 460 }}>
            <div className="mb-2 fw-semibold">Личные данные</div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Фамилия</Form.Label>
              <Form.Control value={form.surname} onChange={(e) => setField("surname", e.target.value)} placeholder="Введите фамилию" required />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Имя</Form.Label>
              <Form.Control value={form.name} onChange={(e) => setField("name", e.target.value)} placeholder="Введите имя" required />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Отчество</Form.Label>
              <Form.Control value={form.middle_name} onChange={(e) => setField("middle_name", e.target.value)} placeholder="Введите отчество (необязательно)" />
            </Form.Group>

            <div className="mb-2 fw-semibold">Организация</div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Отдел</Form.Label>
              <Form.Control value={form.department} plaintext readOnly />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Должность</Form.Label>
              <Form.Control value={form.position} plaintext readOnly />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Email</Form.Label>
              <Form.Control type="email" value={form.email} onChange={(e) => setField("email", e.target.value)} placeholder="Введите email" required />
            </Form.Group>

            {profileError && <Alert variant="danger" className="mb-3">{profileError}</Alert>}

            <AppButton type="submit" className="w-100" variant="primary" icon={Save}>Сохранить</AppButton>
          </Form>
        </Card.Body>
      </Card>

      <Card>
        <Card.Body>
          <Card.Title>Изменение пароля</Card.Title>
          <Form onSubmit={changePassword} className="mx-auto" style={{ maxWidth: 460 }}>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Текущий пароль</Form.Label>
              <PasswordInput value={pwd.current_password} onChange={(e) => setPwd((prev) => ({ ...prev, current_password: e.target.value }))} placeholder="Введите текущий пароль" required />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Новый пароль</Form.Label>
              <PasswordInput value={pwd.new_password} onChange={(e) => setPwd((prev) => ({ ...prev, new_password: e.target.value }))} placeholder="Введите новый пароль" required />
            </Form.Group>

            {passwordError && <Alert variant="danger" className="mb-3">{passwordError}</Alert>}

            <AppButton type="submit" className="w-100" variant="outline" icon={KeyRound}>Изменить</AppButton>
          </Form>
        </Card.Body>
      </Card>
    </Stack>
  );
}
