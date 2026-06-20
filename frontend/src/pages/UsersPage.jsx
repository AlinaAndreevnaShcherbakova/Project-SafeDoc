import React, { useEffect, useMemo, useState } from "react";
import Alert from "react-bootstrap/Alert";
import Card from "react-bootstrap/Card";
import Modal from "react-bootstrap/Modal";
import Form from "react-bootstrap/Form";
import Stack from "react-bootstrap/Stack";
import Table from "react-bootstrap/Table";
import InputGroup from "react-bootstrap/InputGroup";
import { KeyRound, Pencil, Plus, RefreshCw, Save, SearchX, Trash2, UserRoundPen, X } from "lucide-react";

import { api } from "../api/client";
import { buildBulkResultMessage } from "../api/bulkResults";
import Loader from "../components/Loader";
import { useToast } from "../components/notifications/ToastProvider";
import AppButton from "../components/ui/AppButton";
import PasswordInput from "../components/ui/PasswordInput";
import { useAuth } from "../context/AuthContext";

const emptyForm = {
  login: "",
  role: "user",
  password: "",
  password_confirm: "",
  surname: "",
  name: "",
  middle_name: "",
  department: "",
  position: "",
  email: "",
};

const fieldLabels = {
  login: "Логин",
  password: "Пароль",
  surname: "Фамилия",
  name: "Имя",
  middle_name: "Отчество",
  department: "Отдел",
  position: "Должность",
  email: "Email",
  role: "Роль",
};

function getFieldLabel(field) {
  return fieldLabels[field] || field;
}

function formatValidationError(detailItem) {
  if (!detailItem || typeof detailItem !== "object") {
    return "";
  }

  const location = Array.isArray(detailItem.loc)
    ? detailItem.loc.filter((part) => part !== "body").map(String)
    : [];
  const fieldName = location[location.length - 1];
  const label = getFieldLabel(fieldName);

  if (detailItem.type === "string_too_short" && fieldName === "password") {
    return "Пароль должен содержать не менее 8 символов";
  }

  if (detailItem.type === "string_pattern_mismatch") {
    if (fieldName === "login") {
      return "Логин должен содержать только латинские буквы, цифры, точку, дефис и нижнее подчеркивание";
    }
    if (["surname", "name", "middle_name"].includes(fieldName)) {
      return `${label} должно содержать только буквы`;
    }
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

export default function UsersPage() {
  //Формы создания и редактирования используют общий набор полей пользователя.
  const { user } = useAuth();
  const toast = useToast();
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(emptyForm);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showUserModal, setShowUserModal] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [passwordUser, setPasswordUser] = useState(null);
  const [passwordForm, setPasswordForm] = useState({ password: "", password_confirm: "" });
  const [editingUserId, setEditingUserId] = useState(null);
  const [searchInput, setSearchInput] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createFormError, setCreateFormError] = useState("");
  const [editFormError, setEditFormError] = useState("");
  const [passwordFormError, setPasswordFormError] = useState("");

  const visibleUsers = useMemo(() => {
    const query = searchInput.trim().toLowerCase();
    if (!query) return users;
    return users.filter((row) => (
      `${row.login} ${row.surname} ${row.name} ${row.middle_name || ""} ${row.department || ""} ${row.position || ""} ${row.email}`
        .toLowerCase()
        .includes(query)
    ));
  }, [users, searchInput]);

  function getUserLabel(id) {
    const row = users.find((item) => item.id === id);
    if (!row) {
      return id ? `Пользователь #${id}` : "Пользователь";
    }
    return [row.surname, row.name, row.middle_name].filter(Boolean).join(" ") || row.login || `Пользователь #${id}`;
  }

  function applyBulkResult(data, successMessage) {
    const result = buildBulkResultMessage(data, (item, id) => getUserLabel(item?.id ?? item?.user_id ?? id));
    if (result.status === "success") {
      setError("");
      toast.success(successMessage);
      return;
    }
    setError(result.message);
    if (result.status === "partial") {
      toast.info("Операция выполнена частично");
    } else {
      toast.error("Операция не выполнена");
    }
  }

  async function loadUsers() {
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get("/users");
      setUsers(data);
    } catch (err) {
      if (err?.response?.status === 403) {
        setError("Не удается загрузить список пользователей: у вас недостаточно прав");
      } else {
        setError(getErrorMessage(err, "Не удается загрузить список пользователей"));
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    //Список пользователей загружается только для суперадминистратора.
    if (!user?.is_superadmin) {
      setLoading(false);
      setUsers([]);
      setError("");
      return;
    }
    loadUsers();
    //Повторная загрузка нужна только при изменении права суперадминистратора.
  }, [user?.is_superadmin]);

  function validateForm(mode = "create") {
    const setFormError = mode === "create" ? setCreateFormError : setEditFormError;
    if (!/^[A-Za-z0-9._-]+$/.test(form.login)) {
      setFormError("Логин должен содержать только латинские буквы, цифры, точку, дефис и нижнее подчеркивание");
      return false;
    }

    const namePattern = /^[A-Za-zА-Яа-яЁё]+$/;
    if (!namePattern.test(form.surname) || !namePattern.test(form.name)) {
      setFormError("Фамилия и имя должны содержать только буквы");
      return false;
    }
    if (form.middle_name && !namePattern.test(form.middle_name)) {
      setFormError("Отчество должно содержать только буквы");
      return false;
    }

    if (!form.department.trim()) {
      setFormError(form.role === "access_manager" ? "Укажите отдел ответственности менеджера доступа" : "Укажите отдел");
      return false;
    }

    if (mode === "create" && !form.password) {
      setFormError("Укажите пароль");
      return false;
    }

    if ((mode === "create" || (mode === "edit" && (form.password || form.password_confirm))) && form.password !== form.password_confirm) {
      setFormError("Пароли не совпадают");
      return false;
    }

    return true;
  }

  async function createUser(event) {
    event.preventDefault();
    setCreateFormError("");
    if (!validateForm("create")) {
      return;
    }
    try {
      await api.post("/users", {
        login: form.login,
        role: form.role,
        password: form.password,
        surname: form.surname,
        name: form.name,
        middle_name: form.middle_name || null,
        department: form.department,
        position: form.position,
        email: form.email,
        is_superadmin: false,
      });
      setForm(emptyForm);
      setShowCreateModal(false);
      await loadUsers();
      toast.success("Пользователь успешно создан");
    } catch (err) {
      setCreateFormError(getErrorMessage(err, "Ошибка создания пользователя"));
    }
  }

  function startEdit(userRow) {
    setEditingUserId(userRow.id);
    setEditFormError("");
    setForm({
      login: userRow.login || "",
      role: userRow.role || "user",
      password: "",
      password_confirm: "",
      surname: userRow.surname || "",
      name: userRow.name || "",
      middle_name: userRow.middle_name || "",
      department: userRow.department || "",
      position: userRow.position || "",
      email: userRow.email || "",
    });
    setShowEditModal(true);
  }

  function openPasswordModal(userRow) {
    setPasswordUser(userRow);
    setPasswordForm({ password: "", password_confirm: "" });
    setPasswordFormError("");
    setShowPasswordModal(true);
  }

  async function changeUserPassword(event) {
    event.preventDefault();
    if (!passwordUser) return;
    setPasswordFormError("");
    if (!passwordForm.password) {
      setPasswordFormError("Укажите новый пароль");
      return;
    }
    if (passwordForm.password !== passwordForm.password_confirm) {
      setPasswordFormError("Пароли не совпадают");
      return;
    }

    try {
      await api.put(`/users/${passwordUser.id}`, {
        login: passwordUser.login,
        surname: passwordUser.surname,
        name: passwordUser.name,
        middle_name: passwordUser.middle_name || null,
        department: passwordUser.department,
        position: passwordUser.position,
        email: passwordUser.email,
        password: passwordForm.password,
      });
      setShowPasswordModal(false);
      setPasswordUser(null);
      setPasswordForm({ password: "", password_confirm: "" });
      toast.success("Пароль пользователя обновлен");
    } catch (err) {
      setPasswordFormError(getErrorMessage(err, "Не удалось изменить пароль пользователя"));
    }
  }

  async function updateUser(event) {
    event.preventDefault();
    setEditFormError("");
    if (!editingUserId) return;
    if (!validateForm("edit")) return;

    try {
      const payload = {
        login: form.login,
        role: form.role,
        surname: form.surname,
        name: form.name,
        middle_name: form.middle_name || null,
        department: form.department,
        position: form.position,
        email: form.email,
      };
      if (form.password) {
        payload.password = form.password;
      }
      await api.put(`/users/${editingUserId}`, payload);
      setShowEditModal(false);
      setEditingUserId(null);
      setForm(emptyForm);
      await loadUsers();
      toast.success("Пользователь обновлен");
    } catch (err) {
      setEditFormError(getErrorMessage(err, "Ошибка обновления пользователя"));
    }
  }

  async function deleteUser(userId) {
    if (!window.confirm("Вы действительно хотите удалить пользователя?")) {
      return;
    }
    setError("");
    try {
      await api.delete(`/users/${userId}`);
      await loadUsers();
      toast.success("Пользователь удален");
    } catch (err) {
      setError(getErrorMessage(err, "Ошибка удаления пользователя"));
      toast.error("Не удалось удалить пользователя");
    }
  }

  async function bulkDeleteUsers() {
    if (selectedUserIds.length === 0) {
      setError("Выберите пользователей для удаления");
      return;
    }
    if (!window.confirm("Вы действительно хотите удалить выбранных пользователей?")) {
      return;
    }
    setError("");
    try {
      const { data } = await api.post("/users/bulk-delete", { user_ids: selectedUserIds });
      setSelectedUserIds([]);
      await loadUsers();
      applyBulkResult(data, "Выбранные пользователи удалены");
    } catch (err) {
      setError(getErrorMessage(err, "Не удалось удалить выбранных пользователей"));
      toast.error("Массовое удаление не выполнено");
    }
  }

  function toggleUserSelection(userId, checked) {
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(userId);
      } else {
        next.delete(userId);
      }
      return Array.from(next);
    });
  }

  function toggleSelectAllUsers(checked) {
    if (!checked) {
      setSelectedUserIds([]);
      return;
    }
    setSelectedUserIds(visibleUsers.filter((row) => !row.is_superadmin).map((row) => row.id));
  }

  function updateField(field, value) {
    setCreateFormError("");
    setEditFormError("");
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function openUserCard(userRow) {
    setSelectedUser(userRow);
    setShowUserModal(true);
  }

  return (
    <Stack gap={3}>
      <Card>
        <Card.Body>
          <Stack direction="horizontal" gap={2} className="align-items-center flex-nowrap">
            <InputGroup className="flex-grow-1" style={{ minWidth: 0 }}>
              <Form.Control
                placeholder="Введите данные пользователя для поиска"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
              <AppButton type="button" variant="ghost" icon={SearchX} onClick={() => setSearchInput("")}>Сбросить</AppButton>
            </InputGroup>
            <Stack direction="horizontal" gap={2} className="ms-auto flex-nowrap">
              <AppButton variant="outline" icon={RefreshCw} onClick={loadUsers} title="Обновить список" aria-label="Обновить список" />
              <AppButton
                variant="primary"
                icon={Plus}
                className="text-nowrap px-3"
                style={{ minWidth: 210 }}
                onClick={() => {
                  setForm(emptyForm);
                  setCreateFormError("");
                  setShowCreateModal(true);
                }}
              >
                Создать пользователя
              </AppButton>
            </Stack>
          </Stack>
        </Card.Body>
      </Card>

      {error && <Alert variant="danger" style={{ whiteSpace: "pre-line" }}>{error}</Alert>}

      <Card>
        <Card.Body>
          <Stack direction="horizontal" className="justify-content-between align-items-center mb-2">
            <Card.Title className="mb-0">Список пользователей</Card.Title>
            {selectedUserIds.length > 0 && (
              <AppButton variant="danger" icon={Trash2} onClick={bulkDeleteUsers}>Удалить выбранных</AppButton>
            )}
          </Stack>
          {loading ? (
            <Loader />
          ) : visibleUsers.length === 0 ? (
            <Alert variant="light" className="mb-0">Пользователи пока не добавлены.</Alert>
          ) : (
            <Table responsive hover>
              <thead>
                <tr>
                  <th>
                    <Form.Check
                      type="checkbox"
                      onChange={(event) => toggleSelectAllUsers(event.target.checked)}
                      checked={
                        visibleUsers.filter((row) => !row.is_superadmin).length > 0
                        && visibleUsers.filter((row) => !row.is_superadmin).every((row) => selectedUserIds.includes(row.id))
                      }
                    />
                  </th>
                  <th>ID</th>
                  <th>Логин</th>
                  <th>ФИО</th>
                  <th>Отдел</th>
                  <th>Должность</th>
                  <th>Роль</th>
                  <th>Email</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {visibleUsers.map((user) => (
                  <tr key={user.id} onDoubleClick={() => openUserCard(user)} style={{ cursor: "pointer" }}>
                    <td>
                      {!user.is_superadmin ? (
                        <Form.Check
                          type="checkbox"
                          checked={selectedUserIds.includes(user.id)}
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) => toggleUserSelection(user.id, event.target.checked)}
                        />
                      ) : null}
                    </td>
                    <td>{user.id}</td>
                    <td>{user.login}</td>
                    <td>{[user.surname, user.name, user.middle_name].filter(Boolean).join(" ")}</td>
                    <td>{user.department}</td>
                    <td>{user.position}</td>
                    <td>{user.role === "superadmin" ? "Суперадминистратор" : user.role === "access_manager" ? "Менеджер доступа" : "Пользователь"}</td>
                    <td>{user.email}</td>
                    <td>
                      <Stack direction="horizontal" gap={2}>
                        <AppButton
                          size="sm"
                          variant="outline"
                          icon={Pencil}
                          title="Редактировать"
                          aria-label="Редактировать"
                          onClick={(event) => {
                            event.stopPropagation();
                            startEdit(user);
                          }}
                        >
                          Редактировать
                        </AppButton>
                        <AppButton
                          size="sm"
                          variant="ghost"
                          icon={UserRoundPen}
                          title="Сменить пароль"
                          aria-label="Сменить пароль"
                          onClick={(event) => {
                            event.stopPropagation();
                            openPasswordModal(user);
                          }}
                        >
                          Пароль
                        </AppButton>
                        <AppButton
                          size="sm"
                          variant="danger"
                          icon={Trash2}
                          title="Удалить"
                          aria-label="Удалить"
                          onClick={(event) => {
                            event.stopPropagation();
                            deleteUser(user.id);
                          }}
                        >
                          Удалить
                        </AppButton>
                      </Stack>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Modal show={showCreateModal} onHide={() => setShowCreateModal(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Создание пользователя</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form onSubmit={createUser} className="mx-auto" style={{ maxWidth: 460 }}>
            {createFormError && <Alert variant="danger">{createFormError}</Alert>}
            <div className="mb-2 fw-semibold">Учетные данные</div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Логин</Form.Label>
              <Form.Control placeholder="Введите логин" value={form.login} onChange={(e) => updateField("login", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Роль</Form.Label>
              <Form.Select value={form.role} onChange={(e) => updateField("role", e.target.value)}>
                <option value="user">Пользователь</option>
                <option value="access_manager">Менеджер доступа</option>
              </Form.Select>
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Пароль</Form.Label>
              <PasswordInput placeholder="Введите пароль" value={form.password} onChange={(e) => updateField("password", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Подтверждение пароля</Form.Label>
              <PasswordInput
                placeholder="Повторите пароль"
                value={form.password_confirm}
                onChange={(e) => updateField("password_confirm", e.target.value)}
                required
              />
            </Form.Group>

            <div className="mb-2 fw-semibold">Личные данные</div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Фамилия</Form.Label>
              <Form.Control placeholder="Введите фамилию" value={form.surname} onChange={(e) => updateField("surname", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Имя</Form.Label>
              <Form.Control placeholder="Введите имя" value={form.name} onChange={(e) => updateField("name", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Отчество</Form.Label>
              <Form.Control placeholder="Введите отчество (необязательно)" value={form.middle_name} onChange={(e) => updateField("middle_name", e.target.value)} />
            </Form.Group>

            <div className="mb-2 fw-semibold">Организация</div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Отдел</Form.Label>
              <Form.Control
                placeholder={form.role === "access_manager" ? "Введите отдел ответственности менеджера доступа" : "Введите отдел"}
                value={form.department}
                onChange={(e) => updateField("department", e.target.value)}
                required
              />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Должность</Form.Label>
              <Form.Control placeholder="Введите должность" value={form.position} onChange={(e) => updateField("position", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Email</Form.Label>
              <Form.Control placeholder="Введите email" type="email" value={form.email} onChange={(e) => updateField("email", e.target.value)} required />
            </Form.Group>
            <Stack direction="horizontal" className="justify-content-end gap-2 mt-3">
              <AppButton variant="ghost" icon={X} onClick={() => setShowCreateModal(false)}>Отмена</AppButton>
              <AppButton type="submit" variant="primary" icon={Save}>Создать</AppButton>
            </Stack>
          </Form>
        </Modal.Body>
      </Modal>

      <Modal show={showEditModal} onHide={() => setShowEditModal(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Редактирование пользователя</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form onSubmit={updateUser} className="mx-auto" style={{ maxWidth: 460 }}>
            {editFormError && <Alert variant="danger">{editFormError}</Alert>}
            <div className="mb-2 fw-semibold">Учетные данные</div>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Логин</Form.Label>
              <Form.Control placeholder="Введите логин" value={form.login} onChange={(e) => updateField("login", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Роль</Form.Label>
              <Form.Select value={form.role} onChange={(e) => updateField("role", e.target.value)}>
                <option value="user">Пользователь</option>
                <option value="access_manager">Менеджер доступа</option>
              </Form.Select>
            </Form.Group>

            <div className="mb-2 fw-semibold">Личные данные</div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Фамилия</Form.Label>
              <Form.Control placeholder="Введите фамилию" value={form.surname} onChange={(e) => updateField("surname", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Имя</Form.Label>
              <Form.Control placeholder="Введите имя" value={form.name} onChange={(e) => updateField("name", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Отчество</Form.Label>
              <Form.Control placeholder="Введите отчество (необязательно)" value={form.middle_name} onChange={(e) => updateField("middle_name", e.target.value)} />
            </Form.Group>

            <div className="mb-2 fw-semibold">Организация</div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Отдел</Form.Label>
              <Form.Control
                placeholder={form.role === "access_manager" ? "Введите отдел ответственности менеджера доступа" : "Введите отдел"}
                value={form.department}
                onChange={(e) => updateField("department", e.target.value)}
                required
              />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Должность</Form.Label>
              <Form.Control placeholder="Введите должность" value={form.position} onChange={(e) => updateField("position", e.target.value)} required />
            </Form.Group>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Email</Form.Label>
              <Form.Control placeholder="Введите email" type="email" value={form.email} onChange={(e) => updateField("email", e.target.value)} required />
            </Form.Group>

            <Stack direction="horizontal" className="justify-content-end gap-2 mt-3">
              <AppButton variant="ghost" icon={X} onClick={() => setShowEditModal(false)}>Отмена</AppButton>
              <AppButton type="submit" variant="outline" icon={Save}>Сохранить</AppButton>
            </Stack>
          </Form>
        </Modal.Body>
      </Modal>

      <Modal show={showPasswordModal} onHide={() => setShowPasswordModal(false)} size="md">
        <Modal.Header closeButton>
          <Modal.Title>Смена пароля пользователя</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form onSubmit={changeUserPassword} className="mx-auto" style={{ maxWidth: 420 }}>
            {passwordFormError && <Alert variant="danger">{passwordFormError}</Alert>}
            <div className="small text-muted mb-2">
              Пользователь: <strong>{passwordUser?.login || "-"}</strong>
            </div>
            <Form.Group className="mb-2">
              <Form.Label className="small text-muted">Новый пароль</Form.Label>
              <PasswordInput
                placeholder="Введите новый пароль"
                value={passwordForm.password}
                onChange={(e) => {
                  setPasswordFormError("");
                  setPasswordForm((prev) => ({ ...prev, password: e.target.value }));
                }}
                required
              />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label className="small text-muted">Подтверждение пароля</Form.Label>
              <PasswordInput
                placeholder="Повторите новый пароль"
                value={passwordForm.password_confirm}
                onChange={(e) => {
                  setPasswordFormError("");
                  setPasswordForm((prev) => ({ ...prev, password_confirm: e.target.value }));
                }}
                required
              />
            </Form.Group>
            <Stack direction="horizontal" className="justify-content-end gap-2">
              <AppButton variant="ghost" icon={X} onClick={() => setShowPasswordModal(false)}>Отмена</AppButton>
              <AppButton type="submit" variant="outline" icon={KeyRound}>Изменить пароль</AppButton>
            </Stack>
          </Form>
        </Modal.Body>
      </Modal>

      <Modal show={showUserModal} onHide={() => setShowUserModal(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Карточка пользователя</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {!selectedUser ? (
            <Alert variant="light" className="mb-0">Пользователь не выбран.</Alert>
          ) : (
            <Stack gap={2}>
              <div><span className="text-muted">Логин:</span> {selectedUser.login}</div>
              <div><span className="text-muted">ФИО:</span> {selectedUser.surname} {selectedUser.name} {selectedUser.middle_name || ""}</div>
              <div><span className="text-muted">Отдел:</span> {selectedUser.department}</div>
              <div><span className="text-muted">Должность:</span> {selectedUser.position}</div>
              <div><span className="text-muted">Роль:</span> {selectedUser.role === "superadmin" ? "Суперадминистратор" : selectedUser.role === "access_manager" ? "Менеджер доступа" : "Пользователь"}</div>
              <div><span className="text-muted">Email:</span> {selectedUser.email}</div>
            </Stack>
          )}
        </Modal.Body>
      </Modal>
    </Stack>
  );
}
