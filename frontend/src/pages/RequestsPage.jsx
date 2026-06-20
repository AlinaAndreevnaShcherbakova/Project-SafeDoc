import React, { useEffect, useMemo, useState } from "react";
import Alert from "react-bootstrap/Alert";
import Badge from "react-bootstrap/Badge";
import Card from "react-bootstrap/Card";
import Col from "react-bootstrap/Col";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";
import Row from "react-bootstrap/Row";
import Stack from "react-bootstrap/Stack";
import Table from "react-bootstrap/Table";
import Tab from "react-bootstrap/Tab";
import Tabs from "react-bootstrap/Tabs";
import { Check, RefreshCw, SearchX, ShieldX } from "lucide-react";

import { api } from "../api/client";
import { buildBulkResultMessage, getApiErrorMessage } from "../api/bulkResults";
import Loader from "../components/Loader";
import { useToast } from "../components/notifications/ToastProvider";
import AppButton from "../components/ui/AppButton";

const ROLE_LABELS = {
  reader: "Читатель",
  editor: "Редактор",
  owner: "Владелец",
};

const STATUS_FILTER_OPTIONS = [
  ["all", "Все"],
  ["pending", "Необработанные"],
  ["processed", "Обработанные"],
];

function filterByDate(rows, dateFrom, dateTo) {
  const fromTs = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : null;
  const toTs = dateTo ? new Date(`${dateTo}T23:59:59`).getTime() : null;

  return rows.filter((row) => {
    const sourceDate = row.status === "pending" ? row.created_at : (row.resolved_at || row.created_at);
    const ts = new Date(sourceDate).getTime();
    if (!Number.isFinite(ts)) {
      return false;
    }
    if (fromTs !== null && ts < fromTs) {
      return false;
    }
    if (toTs !== null && ts > toTs) {
      return false;
    }
    return true;
  });
}

function filterByStatus(rows, statusFilter) {
  if (statusFilter === "pending") {
    return rows.filter((row) => row.status === "pending");
  }
  if (statusFilter === "processed") {
    return rows.filter((row) => row.status !== "pending");
  }
  return rows;
}

function getRequestedRoleLabel(row) {
  if (row?.requested_role && ROLE_LABELS[row.requested_role]) {
    return ROLE_LABELS[row.requested_role];
  }
  const permissions = row?.requested_permissions || [];
  if (permissions.includes("edit") || permissions.includes("version_manage")) {
    return ROLE_LABELS.editor;
  }
  return ROLE_LABELS.reader;
}

export default function RequestsPage() {
  //Страница объединяет исходящие заявки и входящие заявки на согласование.
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [myRequests, setMyRequests] = useState([]);
  const [inboxRequests, setInboxRequests] = useState([]);
  const [selectedInboxIds, setSelectedInboxIds] = useState([]);
  const [resolveModalOpen, setResolveModalOpen] = useState(false);
  const [resolveModalApprove, setResolveModalApprove] = useState(true);
  const [resolveModalBulk, setResolveModalBulk] = useState(false);
  const [resolveModalRequestId, setResolveModalRequestId] = useState(null);
  const [resolveModalComment, setResolveModalComment] = useState("");
  const [resolveModalError, setResolveModalError] = useState("");
  const [resolveSubmitting, setResolveSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState("my");
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const datedMyRows = useMemo(() => filterByDate(myRequests, dateFrom, dateTo), [myRequests, dateFrom, dateTo]);
  const datedInboxRows = useMemo(() => filterByDate(inboxRequests, dateFrom, dateTo), [inboxRequests, dateFrom, dateTo]);

  const filteredMyRows = useMemo(() => filterByStatus(datedMyRows, statusFilter), [datedMyRows, statusFilter]);
  const filteredInboxRows = useMemo(() => filterByStatus(datedInboxRows, statusFilter), [datedInboxRows, statusFilter]);

  const activeRows = activeTab === "my" ? filteredMyRows : filteredInboxRows;
  const pendingInboxRows = useMemo(
    () => (activeTab === "inbox" ? filteredInboxRows.filter((row) => row.status === "pending") : []),
    [activeTab, filteredInboxRows]
  );

  function getRequestLabel(id) {
    const row = [...myRequests, ...inboxRequests].find((item) => item.id === id);
    if (!row) {
      return id ? `Заявка #${id}` : "Заявка";
    }
    return row.document_name || `Документ #${row.document_id}`;
  }

  function applyBulkResult(data, successMessage, setErrorMessage = setError) {
    const result = buildBulkResultMessage(data, (item, id) => getRequestLabel(item?.id ?? item?.request_id ?? id));
    if (result.status === "success") {
      setErrorMessage("");
      toast.success(successMessage);
      return true;
    }
    setErrorMessage(result.message);
    if (result.status === "partial") {
      toast.info("Операция выполнена частично");
    } else {
      toast.error("Операция не выполнена");
    }
    return false;
  }

  useEffect(() => {
    setSelectedInboxIds((prev) => prev.filter((id) => pendingInboxRows.some((row) => row.id === id)));
  }, [pendingInboxRows]);

  useEffect(() => {
    loadAllData();
  }, []);

  async function loadAllData() {
    setLoading(true);
    setError("");

    const [myResult, inboxResult] = await Promise.allSettled([
      api.get("/access/requests/my"),
      api.get("/access/requests/inbox"),
    ]);

    const errors = [];

    if (myResult.status === "fulfilled") {
      setMyRequests(myResult.value.data || []);
    } else {
      setMyRequests([]);
      errors.push("мои заявки");
    }

    if (inboxResult.status === "fulfilled") {
      setInboxRequests(inboxResult.value.data || []);
    } else if (inboxResult.reason?.response?.status === 403) {
      setInboxRequests([]);
    } else {
      setInboxRequests([]);
      errors.push("входящие заявки");
    }

    if (errors.length > 0) {
      setError(`Не удалось загрузить: ${errors.join(", ")}`);
    }
    setLoading(false);
  }

  function openResolveModal({ approve, bulk, requestId = null }) {
    setResolveModalApprove(approve);
    setResolveModalBulk(bulk);
    setResolveModalRequestId(requestId);
    setResolveModalComment("");
    setResolveModalError("");
    setResolveModalOpen(true);
  }

  function closeResolveModal() {
    if (resolveSubmitting) {
      return;
    }
    setResolveModalOpen(false);
    setResolveModalRequestId(null);
    setResolveModalComment("");
    setResolveModalError("");
  }

  async function submitResolveModal(event) {
    event.preventDefault();
    const resolutionComment = resolveModalComment.trim() || null;
    setResolveSubmitting(true);

    try {
      if (resolveModalBulk) {
        if (selectedInboxIds.length === 0) {
          setResolveModalError("Выберите хотя бы одну заявку");
          setResolveSubmitting(false);
          return;
        }
        const { data } = await api.post("/access/requests/resolve/bulk", {
          request_ids: selectedInboxIds,
          approve: resolveModalApprove,
          resolution_comment: resolutionComment,
        });
        setSelectedInboxIds([]);
        await loadAllData();
        const success = applyBulkResult(
          data,
          resolveModalApprove ? "Заявки одобрены" : "Заявки отклонены",
          setResolveModalError
        );
        if (!success) {
          return;
        }
      } else {
        if (!resolveModalRequestId) {
          setResolveSubmitting(false);
          return;
        }
        await api.post(`/access/requests/${resolveModalRequestId}/resolve`, {
          approve: resolveModalApprove,
          resolution_comment: resolutionComment,
        });
        await loadAllData();
        toast.success(resolveModalApprove ? "Заявка одобрена" : "Заявка отклонена");
      }
      closeResolveModal();
    } catch (err) {
      const message = getApiErrorMessage(err, "Не удалось обработать заявку");
      setResolveModalError(message);
      toast.error(message);
    } finally {
      setResolveSubmitting(false);
    }
  }

  function toggleInboxSelection(id, checked) {
    setSelectedInboxIds((prev) => {
      const draft = new Set(prev);
      if (checked) {
        draft.add(id);
      } else {
        draft.delete(id);
      }
      return Array.from(draft);
    });
  }

  function toggleSelectAllPending(checked) {
    if (!checked) {
      setSelectedInboxIds([]);
      return;
    }
    setSelectedInboxIds(pendingInboxRows.map((row) => row.id));
  }

  function resolveSelected(approve) {
    if (selectedInboxIds.length === 0) {
      setError("Выберите хотя бы одну заявку");
      return;
    }
    openResolveModal({ approve, bulk: true });
  }

  if (loading) {
    return <Loader />;
  }

  return (
    <Stack gap={3}>
      <Card>
        <Card.Body>
          <Stack direction="horizontal" className="justify-content-between align-items-center mb-3">
            <Card.Title className="mb-0">Заявки</Card.Title>
            <AppButton variant="outline" icon={RefreshCw} onClick={loadAllData} title="Обновить" aria-label="Обновить" />
          </Stack>

          <Row className="g-2 mb-3">
            <Col md={4}>
              <Form.Label className="small text-muted">Статус</Form.Label>
              <Form.Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                {STATUS_FILTER_OPTIONS.map(([value, label]) => (
                  <option key={`status-filter-${value}`} value={value}>{label}</option>
                ))}
              </Form.Select>
            </Col>
            <Col md={3}>
              <Form.Label className="small text-muted">Дата от</Form.Label>
              <Form.Control type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </Col>
            <Col md={3}>
              <Form.Label className="small text-muted">Дата до</Form.Label>
              <Form.Control type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </Col>
            <Col md={2} className="d-flex align-items-end">
              <AppButton variant="ghost" icon={SearchX} onClick={() => { setStatusFilter("all"); setDateFrom(""); setDateTo(""); }}>
                Сбросить
              </AppButton>
            </Col>
          </Row>

          {error && <Alert variant="danger" style={{ whiteSpace: "pre-line" }}>{error}</Alert>}

          <Tabs activeKey={activeTab} onSelect={(key) => setActiveTab(key || "my")} className="mb-3">
            <Tab eventKey="my" title="Мои заявки" />
            <Tab eventKey="inbox" title="Входящие заявки" />
          </Tabs>

          {activeTab === "inbox" && selectedInboxIds.length > 0 && (
            <Stack direction="horizontal" gap={2} className="mb-2">
              <AppButton size="sm" variant="outline" icon={Check} onClick={() => resolveSelected(true)}>Одобрить выбранные</AppButton>
              <AppButton size="sm" variant="danger" icon={ShieldX} onClick={() => resolveSelected(false)}>Отклонить выбранные</AppButton>
            </Stack>
          )}

          {activeRows.length === 0 ? (
            <Alert variant="light" className="mb-0">Нет данных по выбранным фильтрам.</Alert>
          ) : activeTab === "my" ? (
            <Table responsive hover>
              <thead>
                <tr>
                  <th>Документ</th>
                  <th>Роль</th>
                  <th>Статус</th>
                  <th>Дата</th>
                  <th>Комментарий</th>
                </tr>
              </thead>
              <tbody>
                {activeRows.map((row) => (
                  <tr key={`my-${row.id}`}>
                    <td>{row.document_name || `Документ #${row.document_id}`}</td>
                    <td><Badge bg="secondary">{getRequestedRoleLabel(row)}</Badge></td>
                    <td>{row.status_ru || row.status}</td>
                    <td>{new Date(row.status === "pending" ? row.created_at : (row.resolved_at || row.created_at)).toLocaleString("ru-RU")}</td>
                    <td>{row.resolution_comment || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <Table responsive hover>
              <thead>
                <tr>
                  <th>
                    <Form.Check
                      type="checkbox"
                      onChange={(e) => toggleSelectAllPending(e.target.checked)}
                      checked={pendingInboxRows.length > 0 && pendingInboxRows.every((row) => selectedInboxIds.includes(row.id))}
                    />
                  </th>
                  <th>Документ</th>
                  <th>Инициатор</th>
                  <th>Роль</th>
                  <th>Статус</th>
                  <th>Кто обработал</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {activeRows.map((row) => {
                  const isPending = row.status === "pending";
                  return (
                    <tr key={`inbox-${row.id}`}>
                      <td>
                        {isPending ? (
                          <Form.Check
                            type="checkbox"
                            checked={selectedInboxIds.includes(row.id)}
                            onChange={(e) => toggleInboxSelection(row.id, e.target.checked)}
                          />
                        ) : null}
                      </td>
                      <td>{row.document_name || `Документ #${row.document_id}`}</td>
                      <td>{row.requester_login || row.requester_id}</td>
                      <td><Badge bg="secondary">{getRequestedRoleLabel(row)}</Badge></td>
                      <td>{row.status_ru || row.status}</td>
                      <td>{row.resolved_by_login || row.resolved_by_id || "-"}</td>
                      <td>
                        {isPending ? (
                          <Stack direction="horizontal" gap={2}>
                            <AppButton size="sm" variant="outline" icon={Check} onClick={() => openResolveModal({ approve: true, bulk: false, requestId: row.id })}>Одобрить</AppButton>
                            <AppButton size="sm" variant="danger" icon={ShieldX} onClick={() => openResolveModal({ approve: false, bulk: false, requestId: row.id })}>Отклонить</AppButton>
                          </Stack>
                        ) : (
                          <span className="text-muted">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Modal show={resolveModalOpen} onHide={closeResolveModal} centered>
        <Form onSubmit={submitResolveModal}>
          <Modal.Header closeButton>
            <Modal.Title>{resolveModalApprove ? "Одобрить заявку" : "Отклонить заявку"}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            {resolveModalError ? (
              <Alert variant="danger" className="mb-3">{resolveModalError}</Alert>
            ) : null}
            <p className="text-muted mb-2">
              {resolveModalBulk
                ? `Вы обрабатываете выбранные заявки: ${selectedInboxIds.length} шт.`
                : "Вы обрабатываете одну заявку."}
            </p>
            <Form.Group controlId="resolutionComment">
              <Form.Label>Комментарий (необязательно)</Form.Label>
              <Form.Control
                as="textarea"
                rows={3}
                value={resolveModalComment}
                onChange={(event) => {
                  setResolveModalComment(event.target.value);
                  setResolveModalError("");
                }}
                placeholder="Укажите комментарий к решению"
              />
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <AppButton type="button" variant="ghost" onClick={closeResolveModal} disabled={resolveSubmitting}>Отмена</AppButton>
            <AppButton type="submit" variant={resolveModalApprove ? "primary" : "danger"} disabled={resolveSubmitting}>
              {resolveSubmitting ? "Сохранение..." : resolveModalApprove ? "Одобрить" : "Отклонить"}
            </AppButton>
          </Modal.Footer>
        </Form>
      </Modal>
    </Stack>
  );
}
