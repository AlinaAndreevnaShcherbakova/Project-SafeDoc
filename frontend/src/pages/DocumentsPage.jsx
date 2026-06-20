import React, { useEffect, useMemo, useRef, useState } from "react";
import Alert from "react-bootstrap/Alert";
import Badge from "react-bootstrap/Badge";
import Breadcrumb from "react-bootstrap/Breadcrumb";
import Card from "react-bootstrap/Card";
import Dropdown from "react-bootstrap/Dropdown";
import Form from "react-bootstrap/Form";
import InputGroup from "react-bootstrap/InputGroup";
import Modal from "react-bootstrap/Modal";
import Offcanvas from "react-bootstrap/Offcanvas";
import Row from "react-bootstrap/Row";
import Col from "react-bootstrap/Col";
import Stack from "react-bootstrap/Stack";
import Table from "react-bootstrap/Table";
import Tabs from "react-bootstrap/Tabs";
import Tab from "react-bootstrap/Tab";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  FolderPlus,
  Link2,
  Lock,
  Move,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  SearchX,
  ShieldX,
  Trash2,
  Upload,
  UserPlus,
} from "lucide-react";

import { api } from "../api/client";
import { buildBulkResultMessage, getApiErrorMessage } from "../api/bulkResults";
import AppButton from "../components/ui/AppButton";
import Loader from "../components/Loader";
import { useToast } from "../components/notifications/ToastProvider";
import { useAuth } from "../context/AuthContext";

const VISIBILITY_OPTIONS = [
  ["by_request", "По запросу"],
  ["read_all", "Доступно всем для чтения"],
  ["edit_all", "Доступно всем для редактирования"],
];
const VISIBILITY_LABELS = Object.fromEntries(VISIBILITY_OPTIONS);
const ACCESS_FILTER_OPTIONS = [
  ["all", "Все"],
  ["with_access", "Есть доступ"],
  ["without_access", "Нет доступа"],
];

const PERMISSION_PRESETS = {
  reader: { label: "Читатель", role: "reader", permissions: ["preview", "version_view"] },
  editor: { label: "Редактор", role: "editor", permissions: ["preview", "download", "edit", "version_view", "version_manage"] },
};

const REQUEST_PRESETS = {
  reader: { label: "Читатель", role: "reader", permissions: ["preview", "version_view"] },
  editor: { label: "Редактор", role: "editor", permissions: ["preview", "download", "edit", "version_view", "version_manage"] },
};

function permissionsToPreset(permissions = []) {
  const normalized = [...permissions].sort().join(",");
  for (const [key, value] of Object.entries(PERMISSION_PRESETS)) {
    if ([...value.permissions].sort().join(",") === normalized) {
      return key;
    }
  }
  return "reader";
}

function getErrorMessage(err, fallback) {
  const detail = err?.response?.data?.detail;

  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item?.msg === "string" && item.msg.trim()) {
          return item.msg;
        }
        return "";
      })
      .filter(Boolean);
    if (messages.length > 0) {
      return messages.join(" ");
    }
  }

  return fallback;
}

function buildPublicLinkUrl(token) {
  return `${window.location.origin}/api/links/public/${token}`;
}

function formatSize(sizeBytes) {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  const exponent = Math.min(Math.floor(Math.log(sizeBytes) / Math.log(1024)), units.length - 1);
  const value = sizeBytes / 1024 ** exponent;
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[exponent]}`;
}

function buildFolderMaps(folders) {
  //Плоский список папок преобразуется в дерево для боковой навигации.
  const byId = new Map();
  const children = new Map();
  folders.forEach((folder) => {
    byId.set(folder.id, folder);
    children.set(folder.id, []);
  });

  const roots = [];
  folders.forEach((folder) => {
    if (folder.parent_id && children.has(folder.parent_id)) {
      children.get(folder.parent_id).push(folder);
      return;
    }
    roots.push(folder);
  });

  for (const list of children.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }
  roots.sort((a, b) => a.name.localeCompare(b.name, "ru"));

  return { byId, children, roots };
}

function FolderTree({ roots, children, selectedFolderId, onSelectFolder }) {
  const [expanded, setExpanded] = useState(new Set());

  function toggle(id) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function renderNode(folder, depth = 0) {
    const hasChildren = (children.get(folder.id) || []).length > 0;
    const isOpen = expanded.has(folder.id);
    return (
      <div key={folder.id} style={{ paddingLeft: depth * 12 }}>
        <div className="d-flex align-items-center gap-1">
          <AppButton
            size="sm"
            variant="ghost"
            icon={isOpen ? ChevronDown : ChevronRight}
            className="p-0 text-decoration-none"
            style={{ width: 16, visibility: hasChildren ? "visible" : "hidden" }}
            onClick={() => toggle(folder.id)}
          />
          <button
            type="button"
            className={`sd-folder-btn ${selectedFolderId === folder.id ? "active" : ""}`}
            onClick={() => onSelectFolder(folder.id)}
          >
            {folder.name}
          </button>
        </div>
        {isOpen && (children.get(folder.id) || []).map((child) => renderNode(child, depth + 1))}
      </div>
    );
  }

  return <div>{roots.map((folder) => renderNode(folder))}</div>;
}

export default function DocumentsPage() {
  const { user, loading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [initialLoaded, setInitialLoaded] = useState(false);
  const [error, setErrorState] = useState("");

  const [documents, setDocuments] = useState([]);
  const [catalogDocuments, setCatalogDocuments] = useState([]);
  const [folders, setFolders] = useState([]);
  const [searchInput, setSearchInput] = useState("");
  const [searchApplied, setSearchApplied] = useState("");
  const [scope, setScope] = useState("all");
  const [accessFilter, setAccessFilter] = useState("all");

  const [requestModalOpen, setRequestModalOpen] = useState(false);
  const [requestDocument, setRequestDocument] = useState(null);
  const [requestBulkDocIds, setRequestBulkDocIds] = useState([]);
  const [requestPreset, setRequestPreset] = useState("reader");
  const [requestComment, setRequestComment] = useState("");

  const [selectedFolderId, setSelectedFolderId] = useState(null);
  const [selectedDocIds, setSelectedDocIds] = useState([]);
  const [selectedRequestDocIds, setSelectedRequestDocIds] = useState([]);
  const [bulkMoveFolderId, setBulkMoveFolderId] = useState("");

  const [uploadFile, setUploadFile] = useState(null);
  const [uploadComment, setUploadComment] = useState("");
  const [uploadVisibility, setUploadVisibility] = useState("by_request");
  const [uploadFolderId, setUploadFolderId] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [folderEditingName, setFolderEditingName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  const [selectedDocument, setSelectedDocument] = useState(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelTab, setPanelTab] = useState("preview");
  const [panelPreviewUrl, setPanelPreviewUrl] = useState("");
  const [panelPreviewLoading, setPanelPreviewLoading] = useState(false);
  const [links, setLinks] = useState([]);
  const [linkName, setLinkName] = useState("");
  const [linkExpiresAt, setLinkExpiresAt] = useState("");
  const [linkError, setLinkError] = useState("");
  const [detailsError, setDetailsError] = useState("");
  const [versionError, setVersionError] = useState("");
  const [accessError, setAccessError] = useState("");
  const [requestError, setRequestError] = useState("");
  const [versions, setVersions] = useState([]);
  const [versionFile, setVersionFile] = useState(null);
  const [versionFileInputKey, setVersionFileInputKey] = useState(0);
  const [versionComment, setVersionComment] = useState("");
  const [versionUploading, setVersionUploading] = useState(false);
  const [moveTargetByDoc, setMoveTargetByDoc] = useState({});
  const [editingDocName, setEditingDocName] = useState("");
  const [editingDocVisibility, setEditingDocVisibility] = useState("by_request");
  const [aclLoading, setAclLoading] = useState(false);
  const [aclRows, setAclRows] = useState([]);
  const [userSearch, setUserSearch] = useState("");
  const [userOptions, setUserOptions] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedUserLabel, setSelectedUserLabel] = useState("");
  const [showUserSuggestions, setShowUserSuggestions] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState("reader");
  const [rowPresetByUser, setRowPresetByUser] = useState({});
  const [selectedAclUserIds, setSelectedAclUserIds] = useState([]);
  const [bulkAclPreset, setBulkAclPreset] = useState("reader");
  const [linkStatusNow, setLinkStatusNow] = useState(Date.now());

  function setError(value) {
    if (typeof value === "string") {
      setErrorState(value);
      return;
    }
    if (Array.isArray(value)) {
      const messages = value
        .map((item) => {
          if (typeof item === "string" && item.trim()) {
            return item;
          }
          if (typeof item?.msg === "string" && item.msg.trim()) {
            return item.msg;
          }
          return "";
        })
        .filter(Boolean);
      setErrorState(messages.join(" ") || "Произошла ошибка");
      return;
    }
    if (value && typeof value === "object" && typeof value.msg === "string" && value.msg.trim()) {
      setErrorState(value.msg);
      return;
    }
    setErrorState(value ? String(value) : "");
  }

  function clearPanelErrors() {
    setDetailsError("");
    setVersionError("");
    setAccessError("");
    setLinkError("");
  }

  useEffect(() => {
    const timerId = window.setInterval(() => {
      setLinkStatusNow(Date.now());
    }, 30000);
    return () => window.clearInterval(timerId);
  }, []);

  useEffect(() => {
    if (!selectedDocument) {
      return;
    }
    syncDocumentPublicLinkState(selectedDocument.id, links, linkStatusNow);
  }, [linkStatusNow, links, selectedDocument?.id]);

  const myDocs = useMemo(
    () => (documents || []).filter((doc) => doc.owner_id === user?.id),
    [documents, user?.id]
  );
  const allDocs = useMemo(() => (catalogDocuments || []), [catalogDocuments]);
  const availableDocs = useMemo(
    () => (catalogDocuments || []).filter((doc) => doc.owner_id !== user?.id && doc.has_access),
    [catalogDocuments, user?.id]
  );
  const allScopeDocs = useMemo(() => {
    if (scope === "mine") return myDocs;
    if (scope === "available") return availableDocs;
    return allDocs;
  }, [scope, myDocs, availableDocs, allDocs]);

  const canManageSelectedDocumentAccess = useMemo(() => {
    if (!selectedDocument) {
      return false;
    }
    return selectedDocument.owner_id === user?.id || selectedDocument.can_manage_access === true;
  }, [selectedDocument, user?.id]);
  const canWriteSelectedDocument = useMemo(() => {
    if (!selectedDocument) {
      return false;
    }
    const matchingDoc = [...documents, ...catalogDocuments].find((doc) => doc.id === selectedDocument.id);
    const effectiveDocument = matchingDoc || selectedDocument;
    return effectiveDocument.owner_id === user?.id || effectiveDocument.can_write === true;
  }, [selectedDocument, documents, catalogDocuments, user?.id]);
  const selectedDocumentCurrentVersion = useMemo(() => {
    if (!selectedDocument) {
      return null;
    }
    if (typeof selectedDocument.current_version === "number") {
      return selectedDocument.current_version;
    }
    const matchingDoc = [...documents, ...catalogDocuments].find((doc) => doc.id === selectedDocument.id);
    return typeof matchingDoc?.current_version === "number" ? matchingDoc.current_version : null;
  }, [selectedDocument, documents, catalogDocuments]);

  const { byId: foldersById, children: folderChildren, roots: folderRoots } = useMemo(() => buildFolderMaps(folders), [folders]);

  function getDocumentLabel(id) {
    const doc = [...documents, ...catalogDocuments].find((row) => row.id === id);
    return doc?.name || (id ? `Документ #${id}` : "Документ");
  }

  function getAclUserLabel(id) {
    const row = aclRows.find((item) => item.user_id === id);
    return row?.user_full_name || row?.user_login || (id ? `Пользователь #${id}` : "Пользователь");
  }

  function isActivePublicLink(link, now = Date.now()) {
    return !link?.revoked_at && new Date(link?.expires_at).getTime() > now;
  }

  function setDocumentPublicLinkState(documentId, hasActivePublicLinks) {
    const applyFlag = (doc) => (
      doc.id === documentId && doc.has_active_public_links !== hasActivePublicLinks
        ? { ...doc, has_active_public_links: hasActivePublicLinks }
        : doc
    );
    setDocuments((prev) => prev.map(applyFlag));
    setCatalogDocuments((prev) => prev.map(applyFlag));
    setSelectedDocument((prev) => (
      prev?.id === documentId && prev.has_active_public_links !== hasActivePublicLinks
        ? { ...prev, has_active_public_links: hasActivePublicLinks }
        : prev
    ));
  }

  function syncDocumentPublicLinkState(documentId, nextLinks, now = Date.now()) {
    setDocumentPublicLinkState(documentId, (nextLinks || []).some((link) => isActivePublicLink(link, now)));
  }

  function applyBulkResult(data, { successMessage, resolveLabel, setErrorMessage = setError }) {
    const result = buildBulkResultMessage(data, resolveLabel);
    if (result.status === "success") {
      setErrorMessage("");
      toast.success(successMessage);
      return true;
    }
    setErrorMessage(result.message);
    if (result.status === "partial") {
      toast.info("Операция выполнена частично");
      return true;
    }
    toast.error("Операция не выполнена");
    return false;
  }

  const visibleDocs = useMemo(() => {
    const byScope = scope !== "mine" ? allScopeDocs : allScopeDocs.filter((doc) => {
      if (selectedFolderId === null && doc.folder_id) {
        return false;
      }
      if (selectedFolderId !== null && doc.folder_id !== selectedFolderId) {
        return false;
      }
      return true;
    });

    if (scope !== "all") {
      return byScope;
    }

    if (accessFilter === "with_access") {
      return byScope.filter((doc) => doc.has_access !== false);
    }
    if (accessFilter === "without_access") {
      return byScope.filter((doc) => doc.has_access === false);
    }
    return byScope;
  }, [allScopeDocs, scope, selectedFolderId, accessFilter]);

  const breadcrumbItems = useMemo(() => {
    if (scope === "all") return ["Все файлы"];
    if (scope === "available") return ["Доступные мне"];
    const items = ["Мои файлы", "Корень"];
    if (selectedFolderId === null) return items;
    const chain = [];
    let cursor = foldersById.get(selectedFolderId);
    while (cursor) {
      chain.unshift(cursor.name);
      cursor = cursor.parent_id ? foldersById.get(cursor.parent_id) : null;
    }
    return ["Мои файлы", ...chain];
  }, [scope, selectedFolderId, foldersById]);

  useEffect(() => {
    if (authLoading) return;
    const timer = setTimeout(() => {
      const query = searchInput.trim();
      setSearchApplied(query);
      loadData(query);
    }, 300);
    return () => clearTimeout(timer);
    //Зависимости ограничены вручную, чтобы не перезапускать поиск на каждый внутренний state.
  }, [authLoading, searchInput]);

  useEffect(() => {
    setSelectedFolderId(null);
    setSelectedDocIds([]);
    setSelectedRequestDocIds([]);
  }, [scope]);

  useEffect(() => {
    setSelectedDocIds((prev) => prev.filter((id) => visibleDocs.some((doc) => doc.id === id)));
  }, [visibleDocs]);

  useEffect(() => {
    setSelectedRequestDocIds((prev) => prev.filter((id) => visibleDocs.some((doc) => doc.id === id)));
  }, [visibleDocs]);

  useEffect(() => {
    if (selectedFolderId === null) {
      setFolderEditingName("");
      return;
    }
    setFolderEditingName(foldersById.get(selectedFolderId)?.name || "");
  }, [selectedFolderId, foldersById]);

  useEffect(() => {
    if (!selectedDocument) return;
    loadPanelData(selectedDocument.id);
    //Загрузка данных панели привязана именно к выбранному документу.
  }, [selectedDocument?.id]);

  useEffect(() => {
    if (!panelOpen || !selectedDocument || !canManageSelectedDocumentAccess) {
      return undefined;
    }
    const timer = setTimeout(() => {
      loadUserOptions(userSearch);
    }, 300);
    return () => clearTimeout(timer);
    //Поиск пользователей в ACL выполняется с задержкой, чтобы не дергать API на каждый символ.
  }, [panelOpen, selectedDocument?.id, userSearch, canManageSelectedDocumentAccess]);

  useEffect(() => {
    if (!selectedDocument) {
      setEditingDocName("");
      setEditingDocVisibility("by_request");
      return;
    }
    setEditingDocName(selectedDocument.name || "");
    setEditingDocVisibility(selectedDocument.visibility || "by_request");
  }, [selectedDocument]);

  async function loadData(searchValue = "") {
    if (!initialLoaded) {
      setLoading(true);
    }
    setError("");

    const [docsResult, catalogResult, foldersResult] = await Promise.allSettled([
      api.get("/documents", { params: { search: searchValue || undefined } }),
      api.get("/documents/catalog", { params: { search: searchValue || undefined } }),
      api.get("/documents/folders"),
    ]);

    const loadErrors = [];
    let docsData = [];
    let catalogData = [];

    if (docsResult.status === "fulfilled") {
      docsData = docsResult.value.data || [];
      setDocuments(docsData);
    } else {
      setDocuments([]);
      loadErrors.push("документы");
    }

    if (catalogResult.status === "fulfilled") {
      catalogData = catalogResult.value.data || [];
      setCatalogDocuments(catalogData);
    } else {
      setCatalogDocuments([]);
      loadErrors.push("каталог файлов");
    }

    if (foldersResult.status === "fulfilled") {
      setFolders(foldersResult.value.data || []);
    } else {
      setFolders([]);
      loadErrors.push("папки");
    }

    if (loadErrors.length > 0) {
      setError(`Не удалось загрузить: ${loadErrors.join(", ")}`);
    }

    if (selectedDocument) {
      const refreshedSelectedDocument = [...docsData, ...catalogData].find((doc) => doc.id === selectedDocument.id);
      if (refreshedSelectedDocument) {
        setSelectedDocument(refreshedSelectedDocument);
      }
    }

    setLoading(false);
    setInitialLoaded(true);
  }

  async function loadPanelData(docId) {
    const canReadSelectedDocument = selectedDocument?.has_access !== false || selectedDocument?.owner_id === user?.id;
    const loaders = [loadLinks(docId), loadVersions(docId)];
    if (canReadSelectedDocument) {
      loaders.unshift(loadPanelPreview(docId));
    } else {
      setPanelPreviewUrl("");
    }

    await Promise.all(loaders);
    if (canManageSelectedDocumentAccess) {
      await loadDocumentAcl(docId);
    } else {
      setAclRows([]);
    }
  }

  async function loadPanelPreview(docId) {
    setPanelPreviewLoading(true);
    try {
      const response = await api.get(`/documents/${docId}/preview`, { responseType: "blob" });
      if (panelPreviewUrl) {
        window.URL.revokeObjectURL(panelPreviewUrl);
      }
      const url = window.URL.createObjectURL(response.data);
      setPanelPreviewUrl(url);
    } catch (err) {
      setPanelPreviewUrl("");
      setError(err?.response?.data?.detail || "Не удалось загрузить предпросмотр");
    } finally {
      setPanelPreviewLoading(false);
    }
  }

  async function loadLinks(docId) {
    try {
      const { data } = await api.get(`/links/${docId}`);
      const nextLinks = data || [];
      setLinks(nextLinks);
      syncDocumentPublicLinkState(docId, nextLinks);
      return nextLinks;
    } catch {
      setLinks([]);
      syncDocumentPublicLinkState(docId, []);
      return [];
    }
  }

  async function loadVersions(docId) {
    try {
      const { data } = await api.get(`/documents/${docId}/versions`);
      setVersions(data || []);
    } catch {
      setVersions([]);
    }
  }

  function openDocument(doc) {
    setSelectedDocument(doc);
    clearPanelErrors();
    if (doc.has_access === false && doc.can_manage_access === true) {
      setPanelTab("access");
    } else {
      setPanelTab("preview");
    }
    setPanelOpen(true);
  }

  function closePanel() {
    setPanelOpen(false);
    setSelectedDocument(null);
    setLinks([]);
    setVersions([]);
    clearPanelErrors();
    setVersionFile(null);
    setVersionFileInputKey((prev) => prev + 1);
    setVersionComment("");
    setAclRows([]);
    setSelectedUserId("");
    setSelectedUserLabel("");
    setUserSearch("");
    setShowUserSuggestions(false);
    if (panelPreviewUrl) {
      window.URL.revokeObjectURL(panelPreviewUrl);
      setPanelPreviewUrl("");
    }
  }

  async function handleDownload(doc) {
    try {
      const response = await api.get(`/documents/${doc.id}/download`, { responseType: "blob" });
      const url = window.URL.createObjectURL(response.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.name;
      a.click();
      window.URL.revokeObjectURL(url);
      toast.success("Файл успешно скачан");
    } catch (err) {
      setError(err?.response?.data?.detail || "Ошибка скачивания файла");
      toast.error("Не удалось скачать файл");
    }
  }

  async function handleDelete(doc) {
    if (!window.confirm(`Вы действительно хотите удалить файл «${doc.name}»?`)) {
      return;
    }
    try {
      await api.delete(`/documents/${doc.id}`);
      await loadData(searchApplied);
      if (selectedDocument?.id === doc.id) {
        closePanel();
      }
      toast.success("Файл удален");
    } catch (err) {
      setError(err?.response?.data?.detail || "Не удалось удалить файл");
      toast.error("Удаление не выполнено");
    }
  }

  async function handleCreateFolder(event) {
    event.preventDefault();
    if (!newFolderName.trim()) {
      setError("Укажите название папки");
      return;
    }
    try {
      await api.post("/documents/folders", {
        name: newFolderName.trim(),
        parent_id: selectedFolderId,
      });
      setNewFolderName("");
      await loadData(searchApplied);
      toast.success("Папка создана");
    } catch (err) {
      setError(err?.response?.data?.detail || "Не удалось создать папку");
      toast.error("Папка не создана");
    }
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (!uploadFile) {
      setError("Сначала выберите файл");
      return;
    }
    const targetFolderId = uploadFolderId === "" ? null : Number(uploadFolderId);
    const normalizedUploadName = uploadFile.name.trim().toLowerCase();
    const existingDocument = myDocs.find(
      (doc) => typeof doc.name === "string"
        && doc.name.trim().toLowerCase() === normalizedUploadName
        && (doc.folder_id ?? null) === targetFolderId
    );

    let versionComment = uploadComment.trim();
    if (existingDocument) {
      const shouldReplace = window.confirm(
        "Файл с таким именем уже был загружен в систему. Заменить текущую версию? При необходимости вы сможете ее восстановить"
      );
      if (!shouldReplace) {
        return;
      }
      const promptedComment = window.prompt("Укажите комментарий для новой версии (необязательно)", versionComment);
      if (promptedComment !== null) {
        versionComment = promptedComment.trim();
      }
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      if (versionComment) {
        formData.append("comment", versionComment);
      }
      if (existingDocument) {
        await api.post(`/documents/${existingDocument.id}/versions`, formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else {
        formData.append("visibility", uploadVisibility);
        if (targetFolderId !== null) {
          formData.append("folder_id", String(targetFolderId));
        }
        await api.post("/documents", formData, { headers: { "Content-Type": "multipart/form-data" } });
      }
      setUploadFile(null);
      setUploadFolderId("");
      setUploadComment("");
      await loadData(searchApplied);
      toast.success(existingDocument ? "Загружена новая версия файла" : "Файл загружен");
    } catch (err) {
      setError(err?.response?.data?.detail || "Не удалось загрузить файл");
      toast.error("Ошибка загрузки");
    } finally {
      setUploading(false);
    }
  }

  async function uploadSelectedDocumentVersion(event) {
    //Новая версия загружается из карточки документа и не меняет выбранную папку.
    event.preventDefault();
    if (!selectedDocument || !versionFile) {
      setVersionError("Сначала выберите файл");
      return;
    }

    setVersionError("");
    setVersionUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", versionFile);
      const trimmedComment = versionComment.trim();
      if (trimmedComment) {
        formData.append("comment", trimmedComment);
      }

      const { data: uploadedVersion } = await api.post(`/documents/${selectedDocument.id}/versions`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      if (typeof uploadedVersion?.version === "number") {
        setSelectedDocument((prev) => (
          prev?.id === selectedDocument.id
            ? { ...prev, current_version: uploadedVersion.version }
            : prev
        ));
      }

      setVersionFile(null);
      setVersionFileInputKey((prev) => prev + 1);
      setVersionComment("");
      await Promise.all([
        loadVersions(selectedDocument.id),
        loadPanelPreview(selectedDocument.id),
        loadData(searchApplied),
      ]);
      toast.success("Загружена новая версия файла");
    } catch (err) {
      setVersionError(getErrorMessage(err, "Не удалось загрузить новую версию файла"));
      toast.error("Ошибка загрузки версии");
    } finally {
      setVersionUploading(false);
    }
  }

  async function createLink() {
    if (!selectedDocument) return;
    const parsed = new Date(linkExpiresAt);
    if (!linkExpiresAt || Number.isNaN(parsed.getTime()) || parsed <= new Date()) {
      setLinkError("Укажите корректную дату и время действия ссылки в будущем");
      return;
    }
    setLinkError("");
    try {
      await api.post(`/links/${selectedDocument.id}`, {
        name: linkName.trim() || null,
        expires_at: parsed.toISOString(),
      });
      setLinkName("");
      setLinkExpiresAt("");
      const nextLinks = await loadLinks(selectedDocument.id);
      syncDocumentPublicLinkState(selectedDocument.id, nextLinks);
      toast.success("Публичная ссылка создана");
    } catch (err) {
      setLinkError(getErrorMessage(err, "Не удалось создать ссылку"));
      toast.error("Ошибка создания ссылки");
    }
  }

  async function revokeLink(linkId) {
    if (!window.confirm("Вы действительно хотите отозвать ссылку?")) {
      return;
    }
    try {
      await api.post(`/links/${linkId}/revoke`);
      if (selectedDocument) {
        const nextLinks = await loadLinks(selectedDocument.id);
        syncDocumentPublicLinkState(selectedDocument.id, nextLinks);
      }
      toast.success("Ссылка отозвана");
    } catch (err) {
      setLinkError(getErrorMessage(err, "Не удалось отозвать ссылку"));
      toast.error("Отзыв ссылки не выполнен");
    }
  }

  async function restoreVersion(version) {
    if (!selectedDocument) return;
    if (!window.confirm(`Вы действительно хотите восстановить версию ${version}?`)) {
      return;
    }
    setVersionError("");
    try {
      const { data } = await api.post(`/documents/${selectedDocument.id}/restore/${version}`);
      setSelectedDocument(data);
      await loadData(searchApplied);
      await loadVersions(selectedDocument.id);
      toast.success("Версия восстановлена");
    } catch (err) {
      setVersionError(getErrorMessage(err, "Не удалось восстановить версию"));
      toast.error("Восстановление не выполнено");
    }
  }

  async function renameSelectedFolder() {
    if (scope !== "mine" || selectedFolderId === null) {
      return;
    }
    const trimmed = folderEditingName.trim();
    if (!trimmed) {
      setError("Укажите новое название папки");
      return;
    }
    try {
      const selectedFolder = foldersById.get(selectedFolderId);
      await api.patch(`/documents/folders/${selectedFolderId}`, {
        name: trimmed,
        parent_id: selectedFolder?.parent_id || null,
      });
      setFolderEditingName("");
      await loadData(searchApplied);
      toast.success("Папка переименована");
    } catch (err) {
      setError(err?.response?.data?.detail || "Не удалось переименовать папку");
      toast.error("Переименование папки не выполнено");
    }
  }

  async function deleteSelectedFolder() {
    if (scope !== "mine" || selectedFolderId === null) {
      return;
    }
    if (!window.confirm("Вы действительно хотите удалить выбранную папку?")) {
      return;
    }
    try {
      await api.delete(`/documents/folders/${selectedFolderId}`);
      setSelectedFolderId(null);
      await loadData(searchApplied);
      toast.success("Папка удалена");
    } catch (err) {
      setError(err?.response?.data?.detail || "Не удалось удалить папку");
      toast.error("Удаление папки не выполнено");
    }
  }

  async function moveDocument(event, docId) {
    event.preventDefault();
    const selectedValue = Object.prototype.hasOwnProperty.call(moveTargetByDoc, docId)
      ? moveTargetByDoc[docId]
      : "";
    const targetValue = selectedValue === "" ? null : Number(selectedValue);
    const currentDocument = (documents || []).find((row) => row.id === docId);
    const duplicateDocument = (documents || []).find(
      (row) => row.id !== docId
        && row.owner_id === user?.id
        && row.name === currentDocument?.name
        && (row.folder_id ?? null) === targetValue
    );
    const replaceExisting = duplicateDocument
      ? window.confirm("Файл с таким именем уже был загружен в систему. Заменить текущую версию? При необходимости вы сможете ее восстановить")
      : false;
    if (duplicateDocument && !replaceExisting) {
      return;
    }
    try {
      await api.post(`/documents/${docId}/move`, {
        folder_id: targetValue,
        replace_existing: replaceExisting,
      });
      setMoveTargetByDoc((prev) => ({ ...prev, [docId]: "" }));
      await loadData(searchApplied);
      if (selectedDocument?.id === docId) {
        const refreshed = (documents || []).find((row) => row.id === docId);
        if (refreshed) {
          setSelectedDocument(refreshed);
        }
      }
      toast.success("Документ перемещен");
    } catch (err) {
      setError(err?.response?.data?.detail || "Не удалось переместить документ");
      toast.error("Перемещение не выполнено");
    }
  }

  async function bulkMoveDocuments(event) {
    event.preventDefault();
    if (selectedDocIds.length === 0) {
      setError("Выберите документы для перемещения");
      return;
    }
    const targetFolderId = bulkMoveFolderId === "" ? null : Number(bulkMoveFolderId);
    const duplicateSelectedDocs = selectedDocIds.filter((docId) => {
      const currentDocument = (documents || []).find((row) => row.id === docId);
      return (documents || []).some(
        (row) => row.id !== docId
          && row.owner_id === user?.id
          && row.name === currentDocument?.name
          && (row.folder_id ?? null) === targetFolderId
      );
    });
    const replaceExisting = duplicateSelectedDocs.length > 0
      ? window.confirm("Файл с таким именем уже был загружен в систему. Заменить текущую версию? При необходимости вы сможете ее восстановить")
      : false;
    if (duplicateSelectedDocs.length > 0 && !replaceExisting) {
      return;
    }
    try {
      const { data } = await api.post("/documents/move/bulk", {
        document_ids: selectedDocIds,
        folder_id: targetFolderId,
        replace_existing: replaceExisting,
      });
      setSelectedDocIds([]);
      setBulkMoveFolderId("");
      await loadData(searchApplied);
      applyBulkResult(data, {
        successMessage: "Документы перемещены",
        resolveLabel: (item, id) => getDocumentLabel(item?.id ?? item?.document_id ?? id),
      });
    } catch (err) {
      const message = getApiErrorMessage(err, "Не удалось переместить документы");
      setError(message);
      toast.error(message);
    }
  }

  async function copyPublicLink(href) {
    try {
      setLinkError("");
      await navigator.clipboard.writeText(href);
      toast.success("Ссылка скопирована");
    } catch {
      setLinkError("Не удалось скопировать ссылку");
      toast.error("Копирование не выполнено");
    }
  }

  async function bulkDeleteDocuments() {
    if (selectedDocIds.length === 0) {
      setError("Выберите документы для удаления");
      return;
    }
    if (!window.confirm("Вы действительно хотите удалить выбранные документы?")) {
      return;
    }
    try {
      const { data } = await api.post("/documents/bulk/delete", { document_ids: selectedDocIds });
      setSelectedDocIds([]);
      await loadData(searchApplied);
      applyBulkResult(data, {
        successMessage: "Документы удалены",
        resolveLabel: (item, id) => getDocumentLabel(item?.id ?? item?.document_id ?? id),
      });
    } catch (err) {
      const message = getApiErrorMessage(err, "Не удалось удалить документы");
      setError(message);
      toast.error(message);
    }
  }

  function toggleDocSelection(docId, checked) {
    setSelectedDocIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(docId);
      } else {
        next.delete(docId);
      }
      return Array.from(next);
    });
  }

  function toggleSelectAllVisibleMine(checked) {
    if (!checked) {
      setSelectedDocIds([]);
      return;
    }
    setSelectedDocIds(visibleDocs.filter((doc) => doc.owner_id === user?.id).map((doc) => doc.id));
  }

  async function loadDocumentAcl(documentId) {
    setAclLoading(true);
    try {
      const { data } = await api.get(`/access/documents/${documentId}/acl`);
      setAclRows(data || []);
      setSelectedAclUserIds([]);
      const initialPresets = {};
      (data || []).forEach((row) => {
        initialPresets[row.user_id] = permissionsToPreset(row.permissions);
      });
      setRowPresetByUser(initialPresets);
    } catch {
      setAclRows([]);
    } finally {
      setAclLoading(false);
    }
  }

  async function loadUserOptions(query) {
    try {
      const { data } = await api.get("/access/users/search", { params: { query: query || undefined } });
      setUserOptions(data || []);
    } catch {
      setUserOptions([]);
    }
  }

  function onUserSearchChange(value) {
    setUserSearch(value);
    setSelectedUserId("");
    setSelectedUserLabel(value);
    setShowUserSuggestions(true);
  }

  function selectUserOption(option) {
    setSelectedUserId(String(option.id));
    setSelectedUserLabel(`${option.full_name} (${option.login})`);
    setUserSearch(option.login);
    setShowUserSuggestions(false);
  }

  async function grantAccess(event) {
    event.preventDefault();
    if (!selectedDocument || !selectedUserId) {
      setAccessError("Выберите пользователя");
      return;
    }
    const presetConfig = PERMISSION_PRESETS[selectedPreset];
    if (!presetConfig?.permissions?.length) {
      setAccessError("Не удалось определить набор прав");
      return;
    }
    setAccessError("");
    try {
      await api.post("/access/grant", {
        document_id: selectedDocument.id,
        user_id: Number(selectedUserId),
        role: presetConfig.role,
        permissions: presetConfig.permissions,
      });
      setSelectedUserId("");
      setSelectedUserLabel("");
      setUserSearch("");
      await loadDocumentAcl(selectedDocument.id);
      toast.success("Доступ выдан");
    } catch (err) {
      setAccessError(getErrorMessage(err, "Не удалось выдать доступ"));
      toast.error("Выдача доступа не выполнена");
    }
  }

  async function updateAccessForUser(userId) {
    if (!selectedDocument) return;
    const preset = rowPresetByUser[userId] || "reader";
    const presetConfig = PERMISSION_PRESETS[preset];
    setAccessError("");
    try {
      await api.post("/access/grant", {
        document_id: selectedDocument.id,
        user_id: userId,
        role: presetConfig.role,
        permissions: presetConfig.permissions,
      });
      await loadDocumentAcl(selectedDocument.id);
      toast.success("Права обновлены");
    } catch (err) {
      setAccessError(getErrorMessage(err, "Не удалось обновить права"));
      toast.error("Изменение прав не выполнено");
    }
  }

  async function revokeAccessForUser(userId) {
    if (!selectedDocument) return;
    if (!window.confirm("Вы действительно хотите отозвать доступ?")) {
      return;
    }
    setAccessError("");
    try {
      await api.post("/access/revoke", {
        document_id: selectedDocument.id,
        user_id: userId,
      });
      await loadDocumentAcl(selectedDocument.id);
      toast.success("Доступ отозван");
    } catch (err) {
      setAccessError(getErrorMessage(err, "Не удалось отозвать доступ"));
      toast.error("Отзыв доступа не выполнен");
    }
  }

  function toggleRequestDocSelection(documentId, checked) {
    setSelectedRequestDocIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(documentId);
      } else {
        next.delete(documentId);
      }
      return Array.from(next);
    });
  }

  function toggleSelectAllRequestable(checked) {
    if (!checked) {
      setSelectedRequestDocIds([]);
      return;
    }
    setSelectedRequestDocIds(
      visibleDocs
        .filter((doc) => doc.has_access === false && doc.can_request)
        .map((doc) => doc.id)
    );
  }

  function openBulkRequestModal() {
    if (selectedRequestDocIds.length === 0) {
      setError("Выберите хотя бы один файл для запроса доступа");
      return;
    }
    setRequestError("");
    setRequestDocument(null);
    setRequestBulkDocIds(selectedRequestDocIds);
    setRequestPreset("reader");
    setRequestComment("");
    setRequestModalOpen(true);
  }

  function toggleAclUserSelection(userId, checked) {
    setSelectedAclUserIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(userId);
      } else {
        next.delete(userId);
      }
      return Array.from(next);
    });
  }

  function toggleSelectAllAcl(checked) {
    if (!checked) {
      setSelectedAclUserIds([]);
      return;
    }
    setSelectedAclUserIds(
      aclRows
        .filter((row) => row.user_id !== selectedDocument?.owner_id)
        .map((row) => row.user_id)
    );
  }

  async function revokeSelectedAclUsers() {
    if (!selectedDocument || selectedAclUserIds.length === 0) {
      setAccessError("Выберите пользователей для отзыва доступа");
      return;
    }
    if (!window.confirm("Вы действительно хотите отозвать доступ у выбранных пользователей?")) {
      return;
    }
    try {
      setAccessError("");
      const { data } = await api.post("/access/revoke/bulk", {
        document_id: selectedDocument.id,
        user_ids: selectedAclUserIds,
      });
      setSelectedAclUserIds([]);
      await loadDocumentAcl(selectedDocument.id);
      applyBulkResult(data, {
        successMessage: "Доступ отозван у выбранных пользователей",
        resolveLabel: (item, id) => getAclUserLabel(item?.id ?? item?.user_id ?? id),
        setErrorMessage: setAccessError,
      });
    } catch (err) {
      const message = getApiErrorMessage(err, "Не удалось выполнить массовый отзыв доступа");
      setAccessError(message);
      toast.error(message);
    }
  }

  async function updateSelectedAclUsers() {
    if (!selectedDocument || selectedAclUserIds.length === 0) {
      setAccessError("Выберите пользователей для изменения уровня полномочий");
      return;
    }
    const presetConfig = PERMISSION_PRESETS[bulkAclPreset];
    if (!presetConfig?.permissions?.length) {
      setAccessError("Не удалось определить набор прав");
      return;
    }

    try {
      setAccessError("");
      const { data } = await api.post("/access/grant/bulk", {
        document_id: selectedDocument.id,
        user_ids: selectedAclUserIds,
        role: presetConfig.role,
        permissions: presetConfig.permissions,
      });
      setSelectedAclUserIds([]);
      await loadDocumentAcl(selectedDocument.id);
      applyBulkResult(data, {
        successMessage: "Уровень полномочий обновлен",
        resolveLabel: (item, id) => getAclUserLabel(item?.id ?? item?.user_id ?? id),
        setErrorMessage: setAccessError,
      });
    } catch (err) {
      const message = getApiErrorMessage(err, "Не удалось массово изменить уровень полномочий");
      setAccessError(message);
      toast.error(message);
    }
  }


  async function saveDocumentName() {
    if (!selectedDocument) return;
    const nextName = editingDocName.trim();
    if (!nextName) {
      setDetailsError("Укажите название файла");
      return;
    }
    setDetailsError("");
    try {
      const payload = new FormData();
      payload.append("name", nextName);
      const { data } = await api.patch(`/documents/${selectedDocument.id}/rename`, payload);
      setSelectedDocument(data);
      await loadData(searchApplied);
      toast.success("Название файла обновлено");
    } catch (err) {
      setDetailsError(getErrorMessage(err, "Не удалось переименовать файл"));
      toast.error("Переименование не выполнено");
    }
  }

  async function saveDocumentVisibility() {
    if (!selectedDocument) return;
    setDetailsError("");
    try {
      const { data } = await api.patch(`/documents/${selectedDocument.id}/visibility`, {
        visibility: editingDocVisibility,
      });
      setSelectedDocument(data);
      await loadData(searchApplied);
      toast.success("Уровень доступа обновлен");
    } catch (err) {
      setDetailsError(getErrorMessage(err, "Не удалось обновить уровень доступа"));
      toast.error("Изменение уровня доступа не выполнено");
    }
  }

  function resetSearch() {
    setSearchInput("");
  }

  async function submitAccessRequest(event) {
    event.preventDefault();
    if (!requestDocument && requestBulkDocIds.length === 0) {
      return;
    }
    setRequestError("");
    try {
      let bulkResultData = null;
      if (requestDocument) {
        await api.post("/access/requests", {
          document_id: requestDocument.id,
          requested_role: REQUEST_PRESETS[requestPreset].role,
          requested_permissions: REQUEST_PRESETS[requestPreset].permissions,
          message: requestComment.trim() || null,
        });
      } else {
        const { data } = await api.post("/access/requests/bulk", {
          document_ids: requestBulkDocIds,
          requested_role: REQUEST_PRESETS[requestPreset].role,
          requested_permissions: REQUEST_PRESETS[requestPreset].permissions,
          message: requestComment.trim() || null,
        });
        bulkResultData = data;
      }
      setRequestModalOpen(false);
      setRequestDocument(null);
      setRequestBulkDocIds([]);
      setRequestPreset("reader");
      setRequestComment("");
      setRequestError("");
      setSelectedRequestDocIds([]);
      await loadData(searchApplied);
      if (bulkResultData) {
        applyBulkResult(bulkResultData, {
          successMessage: "Заявки на доступ отправлены",
          resolveLabel: (item, id) => getDocumentLabel(item?.document_id ?? item?.id ?? id),
        });
      } else {
        toast.success("Заявка на доступ отправлена");
      }
    } catch (err) {
      const message = getApiErrorMessage(err, "Не удалось отправить заявку на доступ");
      setRequestError(message);
      toast.error(message);
    }
  }

  if (loading && !initialLoaded) {
    return <Loader />;
  }

  return (
    <Stack gap={3}>
      <div className="sd-page-shell">
        <aside className="sd-sidebar">
          <h6 className="mb-3">Навигация</h6>
          <Stack gap={2} className="mb-3">
            <AppButton variant={scope === "all" ? "primary" : "outline"} size="sm" onClick={() => setScope("all")}>
              Все файлы
            </AppButton>
            <AppButton variant={scope === "mine" ? "primary" : "outline"} size="sm" onClick={() => setScope("mine")}>
              Мои файлы
            </AppButton>
            <AppButton variant={scope === "available" ? "primary" : "outline"} size="sm" onClick={() => setScope("available")}> 
              Доступные мне
            </AppButton>
          </Stack>

          {scope === "mine" && (
            <>
              <button
                type="button"
                className={`sd-folder-btn ${selectedFolderId === null ? "active" : ""}`}
                onClick={() => setSelectedFolderId(null)}
              >
                Корень
              </button>
              <FolderTree
                roots={folderRoots}
                children={folderChildren}
                selectedFolderId={selectedFolderId}
                onSelectFolder={setSelectedFolderId}
              />
              <Form onSubmit={handleCreateFolder} className="mt-3">
                <InputGroup size="sm">
                  <Form.Control
                    placeholder="Новая папка"
                    value={newFolderName}
                    onChange={(e) => setNewFolderName(e.target.value)}
                  />
                  <AppButton type="submit" variant="outline" icon={FolderPlus}>Создать</AppButton>
                </InputGroup>
              </Form>
              {selectedFolderId !== null && (
                <Form
                  className="mt-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    renameSelectedFolder();
                  }}
                >
                  <InputGroup size="sm" className="mb-2">
                    <Form.Control
                      placeholder="Переименовать папку"
                      value={folderEditingName}
                      onChange={(e) => setFolderEditingName(e.target.value)}
                    />
                    <AppButton type="submit" variant="outline" icon={Save}>Сохранить</AppButton>
                  </InputGroup>
                  <AppButton size="sm" variant="danger" icon={Trash2} className="w-100" onClick={deleteSelectedFolder}>
                    Удалить папку
                  </AppButton>
                </Form>
              )}
            </>
          )}
        </aside>

        <div className="sd-main">
          <Card>
            <Card.Body>
              <Row className="g-3 align-items-end">
                <Col md={8}>
                  <InputGroup>
                    <Form.Control
                      placeholder="Введите название документа для поиска"
                      value={searchInput}
                      onChange={(e) => setSearchInput(e.target.value)}
                    />
                    <AppButton type="button" variant="ghost" icon={SearchX} onClick={resetSearch}>Сбросить</AppButton>
                  </InputGroup>
                </Col>
                <Col md={4} className="text-md-end">
                  <AppButton variant="outline" icon={RefreshCw} onClick={() => loadData(searchApplied)} title="Обновить список" aria-label="Обновить список" />
                </Col>
              </Row>

              <Breadcrumb className="mt-3 mb-0">
                {breadcrumbItems.map((item, index) => (
                  <Breadcrumb.Item key={`${item}-${index}`} active={index === breadcrumbItems.length - 1}>
                    {item}
                  </Breadcrumb.Item>
                ))}
              </Breadcrumb>
            </Card.Body>
          </Card>

          {scope === "mine" && (
            <Card className="mt-3">
              <Card.Body>
                <Card.Title>Загрузка файла</Card.Title>
                <Form onSubmit={handleUpload}>
                <div
                  className={`sd-dropzone ${dragActive ? "sd-dropzone-active" : ""}`}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragActive(true);
                  }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragActive(false);
                    const dropped = event.dataTransfer.files?.[0];
                    if (dropped) setUploadFile(dropped);
                  }}
                >
                  <Stack direction="horizontal" className="justify-content-between align-items-center flex-wrap" gap={2}>
                    <div>
                      <div className="fw-semibold">1) Выберите файл</div>
                      <div className="small text-muted">
                        {uploadFile ? `Выбран файл: ${uploadFile.name}` : "Перетащите файл сюда или выберите вручную"}
                      </div>
                    </div>
                    <>
                      <input
                        ref={fileInputRef}
                        type="file"
                        className="d-none"
                        onChange={(event) => setUploadFile(event.target.files?.[0] || null)}
                      />
                      <AppButton type="button" variant="outline" icon={Plus} onClick={() => fileInputRef.current?.click()}>
                        Выбрать файл
                      </AppButton>
                    </>
                  </Stack>
                </div>

                <Row className="g-2 mt-2">
                  <Col md={4}>
                    <Form.Label className="small text-muted mb-1">2) Выберите папку</Form.Label>
                    <Form.Select value={uploadFolderId} onChange={(e) => setUploadFolderId(e.target.value)}>
                      <option value="">Корень</option>
                      {folders.map((folder) => (
                        <option key={folder.id} value={folder.id}>{folder.name}</option>
                      ))}
                    </Form.Select>
                  </Col>
                  <Col md={4}>
                    <Form.Label className="small text-muted mb-1">3) Настройте доступ</Form.Label>
                    <Form.Select value={uploadVisibility} onChange={(e) => setUploadVisibility(e.target.value)}>
                      {VISIBILITY_OPTIONS.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </Form.Select>
                  </Col>
                  <Col md={4}>
                    <Form.Label className="small text-muted mb-1">Комментарий (необязательно)</Form.Label>
                    <Form.Control value={uploadComment} onChange={(e) => setUploadComment(e.target.value)} placeholder="Укажите комментарий" />
                  </Col>
                </Row>

                  <div className="mt-3">
                    <AppButton type="submit" variant="primary" icon={Upload} disabled={uploading || !uploadFile}>
                      {uploading ? "Загрузка..." : "Загрузить файл"}
                    </AppButton>
                  </div>
                </Form>
              </Card.Body>
            </Card>
          )}

          <Card className="mt-3">
            <Card.Body>
              <Stack direction="horizontal" className="justify-content-between align-items-center mb-2">
                <Card.Title className="mb-0">{scope === "mine" ? "Мои документы" : scope === "available" ? "Доступные мне" : "Все файлы"}</Card.Title>
                {scope === "mine" && selectedDocIds.length > 0 && (
                  <Stack direction="horizontal" gap={2}>
                    <Form onSubmit={bulkMoveDocuments}>
                      <InputGroup size="sm">
                        <Form.Select value={bulkMoveFolderId} onChange={(e) => setBulkMoveFolderId(e.target.value)}>
                          <option value="">Корень</option>
                          {folders.map((folder) => (
                            <option key={`bulk-move-${folder.id}`} value={folder.id}>{folder.name}</option>
                          ))}
                        </Form.Select>
                        <AppButton type="submit" size="sm" variant="outline" icon={Move}>Переместить выбранные</AppButton>
                      </InputGroup>
                    </Form>
                    <AppButton size="sm" variant="danger" icon={Trash2} onClick={bulkDeleteDocuments}>Удалить выбранные</AppButton>
                  </Stack>
                )}
                {scope === "all" && (
                  <Stack direction="horizontal" gap={2}>
                    <Form.Select size="sm" value={accessFilter} onChange={(e) => setAccessFilter(e.target.value)}>
                      {ACCESS_FILTER_OPTIONS.map(([value, label]) => (
                        <option key={`access-filter-${value}`} value={value}>{label}</option>
                      ))}
                    </Form.Select>
                    {selectedRequestDocIds.length > 0 && (
                      <AppButton
                        size="sm"
                        variant="outline"
                        icon={Lock}
                        onClick={openBulkRequestModal}
                        className="text-nowrap px-3"
                        style={{ minWidth: 190 }}
                      >
                        Запросить доступ
                      </AppButton>
                    )}
                  </Stack>
                )}
              </Stack>
              {error && <Alert variant="danger" style={{ whiteSpace: "pre-line" }}>{error}</Alert>}

              {visibleDocs.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  {scope === "mine" ? "Вы еще не загрузили ни одного файла в выбранный раздел." : "Файлы не найдены."}
                </Alert>
              ) : (
                <Table responsive hover>
                  <thead>
                    <tr>
                      <th>
                        {scope === "mine" ? (
                          <Form.Check
                            type="checkbox"
                            onChange={(e) => toggleSelectAllVisibleMine(e.target.checked)}
                            checked={
                              visibleDocs.filter((doc) => doc.owner_id === user?.id).length > 0
                              && visibleDocs.filter((doc) => doc.owner_id === user?.id).every((doc) => selectedDocIds.includes(doc.id))
                            }
                          />
                        ) : scope === "all" ? (
                          <Form.Check
                            type="checkbox"
                            onChange={(e) => toggleSelectAllRequestable(e.target.checked)}
                            checked={
                              visibleDocs.filter((doc) => doc.has_access === false && doc.can_request).length > 0
                              && visibleDocs
                                .filter((doc) => doc.has_access === false && doc.can_request)
                                .every((doc) => selectedRequestDocIds.includes(doc.id))
                            }
                          />
                        ) : null}
                      </th>
                      <th>Название</th>
                      <th>Папка</th>
                      <th>Размер</th>
                      <th>Доступ</th>
                      <th style={{ width: 220 }}>Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleDocs.map((doc) => {
                      const hasAccess = doc.has_access !== false;
                      const ownerLabel = doc.owner_login || (doc.owner_id === user?.id ? (user?.login ? `Вы (${user.login})` : "Вы") : `Пользователь #${doc.owner_id}`);

                      return (
                      <tr
                        key={doc.id}
                        className="sd-doc-row"
                        onDoubleClick={() => {
                          if (hasAccess || doc.can_manage_access) {
                            openDocument(doc);
                          }
                        }}
                      >
                        <td>
                          {scope === "mine" && doc.owner_id === user?.id ? (
                            <Form.Check
                              type="checkbox"
                              checked={selectedDocIds.includes(doc.id)}
                              onClick={(event) => event.stopPropagation()}
                              onChange={(event) => toggleDocSelection(doc.id, event.target.checked)}
                            />
                          ) : scope === "all" && doc.has_access === false && doc.can_request ? (
                            <Form.Check
                              type="checkbox"
                              checked={selectedRequestDocIds.includes(doc.id)}
                              onClick={(event) => event.stopPropagation()}
                              onChange={(event) => toggleRequestDocSelection(doc.id, event.target.checked)}
                            />
                          ) : null}
                        </td>
                            <td>
                              <div className="d-flex align-items-center gap-2">
                                <span>{doc.name}</span>
                                {doc.has_active_public_links ? (
                                  <Badge bg="info" className="sd-public-link-marker" title="Есть действующие публичные ссылки">
                                    <Link2 size={14} aria-hidden="true" />
                                    <span>Публичная ссылка</span>
                                  </Badge>
                                ) : null}
                              </div>
                              <div className="small text-muted">Владелец: {ownerLabel}</div>
                            </td>
                        <td>{doc.folder_name || "Корень"}</td>
                        <td>{Number.isFinite(doc.size_bytes) ? formatSize(doc.size_bytes) : "-"}</td>
                        <td>
                          {doc.has_access === false ? (
                            doc.can_request ? <Badge bg="warning" text="dark">Нужен доступ</Badge> : <Badge bg="secondary">Запрос уже отправлен</Badge>
                          ) : (
                            <Badge bg="success">Есть доступ</Badge>
                          )}
                        </td>
                        <td>
                          <Stack direction="horizontal" gap={2}>
                            {hasAccess && doc.can_download ? (
                              <AppButton
                                size="sm"
                                variant="outline"
                                icon={Download}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleDownload(doc);
                                }}
                              >
                                Скачать
                              </AppButton>
                            ) : doc.can_manage_access ? (
                              <AppButton
                                size="sm"
                                variant="outline"
                                icon={UserPlus}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openDocument(doc);
                                }}
                              >
                                Управлять доступом
                              </AppButton>
                            ) : (
                              <AppButton
                                size="sm"
                                variant="outline"
                                icon={Lock}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  if (doc.can_request) {
                                    setRequestError("");
                                    setRequestDocument(doc);
                                    setRequestBulkDocIds([]);
                                    setRequestPreset("reader");
                                    setRequestComment("");
                                    setRequestModalOpen(true);
                                  }
                                }}
                                disabled={!doc.can_request}
                              >
                                Запросить доступ
                              </AppButton>
                            )}
                            {doc.owner_id === user?.id && (
                              <Dropdown onClick={(event) => event.stopPropagation()}>
                                <Dropdown.Toggle size="sm" variant="light">Переместить</Dropdown.Toggle>
                                <Dropdown.Menu className="px-2" style={{ minWidth: 260 }}>
                                  <Form
                                    onSubmit={(event) => moveDocument(event, doc.id)}
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    <Form.Label className="small text-muted">Переместить в папку</Form.Label>
                                    <InputGroup size="sm" className="mb-2">
                                      <Form.Select
                                        value={Object.prototype.hasOwnProperty.call(moveTargetByDoc, doc.id) ? moveTargetByDoc[doc.id] : ""}
                                        onChange={(event) => {
                                          const value = event.target.value;
                                          setMoveTargetByDoc((prev) => ({ ...prev, [doc.id]: value }));
                                        }}
                                      >
                                        <option value="">Корень</option>
                                        {folders.map((folder) => (
                                          <option key={`move-${doc.id}-${folder.id}`} value={folder.id}>{folder.name}</option>
                                        ))}
                                      </Form.Select>
                                      <AppButton type="submit" size="sm" variant="outline" icon={Move}>Переместить</AppButton>
                                    </InputGroup>
                                  </Form>
                                </Dropdown.Menu>
                              </Dropdown>
                            )}
                            {doc.owner_id === user?.id && (
                              <AppButton
                                size="sm"
                                variant="danger"
                                icon={Trash2}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleDelete(doc);
                                }}
                              >
                                Удалить
                              </AppButton>
                            )}
                          </Stack>
                        </td>
                      </tr>
                    );
                    })}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </div>
      </div>

      <Offcanvas show={panelOpen} onHide={closePanel} placement="end" style={{ width: "100vw", maxWidth: "100vw" }}>
        <Offcanvas.Header closeButton>
          <Offcanvas.Title>{selectedDocument ? `Документ: ${selectedDocument.name}` : "Документ"}</Offcanvas.Title>
        </Offcanvas.Header>
        <Offcanvas.Body>
          {!selectedDocument ? (
            <Alert variant="light">Выберите документ для просмотра карточки.</Alert>
          ) : (
            <Tabs activeKey={panelTab} onSelect={(key) => setPanelTab(key || "preview")}>
              <Tab eventKey="preview" title="Предпросмотр">
                <div className="pt-3">
                  {panelPreviewLoading ? (
                    <Loader />
                  ) : panelPreviewUrl ? (
                    <iframe title="preview-panel" src={panelPreviewUrl} style={{ width: "100%", height: "calc(100vh - 140px)", border: 0 }} />
                  ) : (
                    <Alert variant="light">Предпросмотр недоступен для выбранного файла.</Alert>
                  )}
                </div>
              </Tab>

              <Tab eventKey="details" title="Данные">
                <div className="pt-3">
                  <Row className="mt-3 g-2">
                    <Col md={6}><div className="small text-muted">Файл</div><div>{selectedDocument.name}</div></Col>
                    <Col md={6}><div className="small text-muted">Размер</div><div>{formatSize(selectedDocument.size_bytes)}</div></Col>
                    <Col md={6}><div className="small text-muted">Папка</div><div>{selectedDocument.folder_name || "Корень"}</div></Col>
                    <Col md={6}><div className="small text-muted">Видимость</div><div>{VISIBILITY_LABELS[selectedDocument.visibility] || selectedDocument.visibility}</div></Col>
                  </Row>

                  {selectedDocument.owner_id === user?.id && (
                    <>
                      <hr />
                      {detailsError ? (
                        <Alert variant="danger" className="mb-3">{detailsError}</Alert>
                      ) : null}
                      <Row className="g-2">
                        <Col md={8}>
                          <Form.Label>Название файла</Form.Label>
                          <InputGroup>
                            <Form.Control
                              value={editingDocName}
                              onChange={(event) => {
                                setEditingDocName(event.target.value);
                                setDetailsError("");
                              }}
                              placeholder="Укажите название файла"
                            />
                            <AppButton type="button" variant="outline" icon={Pencil} onClick={saveDocumentName}>Сохранить</AppButton>
                          </InputGroup>
                        </Col>
                        <Col md={4}>
                          <Form.Label>Уровень доступа</Form.Label>
                          <InputGroup>
                            <Form.Select
                              value={editingDocVisibility}
                              onChange={(event) => {
                                setEditingDocVisibility(event.target.value);
                                setDetailsError("");
                              }}
                            >
                              {VISIBILITY_OPTIONS.map(([value, label]) => (
                                <option key={`details-visibility-${value}`} value={value}>{label}</option>
                              ))}
                            </Form.Select>
                            <AppButton type="button" variant="outline" icon={Save} onClick={saveDocumentVisibility}>Сохранить</AppButton>
                          </InputGroup>
                        </Col>
                      </Row>
                    </>
                  )}
                </div>
              </Tab>

              <Tab eventKey="versions" title="Версии">
                <div className="pt-3">
                  {canWriteSelectedDocument && (
                    <Card className="mb-3">
                      <Card.Body>
                        <Card.Title className="h6">Загрузить новую версию</Card.Title>
                        {versionError ? (
                          <Alert variant="danger" className="mb-3">{versionError}</Alert>
                        ) : null}
                        <Form onSubmit={uploadSelectedDocumentVersion}>
                          <Row className="g-2 align-items-end">
                            <Col md={5}>
                              <Form.Label className="small text-muted mb-1">Файл</Form.Label>
                              <Form.Control
                                key={versionFileInputKey}
                                type="file"
                                onChange={(event) => {
                                  setVersionFile(event.target.files?.[0] || null);
                                  setVersionError("");
                                }}
                              />
                            </Col>
                            <Col md={5}>
                              <Form.Label className="small text-muted mb-1">Комментарий</Form.Label>
                              <Form.Control
                                value={versionComment}
                                onChange={(event) => {
                                  setVersionComment(event.target.value);
                                  setVersionError("");
                                }}
                                placeholder="Необязательно"
                              />
                            </Col>
                            <Col md={2}>
                              <AppButton
                                type="submit"
                                variant="primary"
                                icon={Upload}
                                disabled={versionUploading || !versionFile}
                                className="w-100"
                              >
                                {versionUploading ? "Загрузка..." : "Загрузить"}
                              </AppButton>
                            </Col>
                          </Row>
                        </Form>
                      </Card.Body>
                    </Card>
                  )}
                  {versions.length === 0 ? (
                    <Alert variant="light" className="mb-0">История версий пока отсутствует.</Alert>
                  ) : (
                    <Table responsive hover>
                      <thead>
                        <tr>
                          <th>Версия</th>
                          <th>Автор</th>
                          <th>Комментарий</th>
                          <th>Дата</th>
                          <th></th>
                        </tr>
                      </thead>
                        <tbody>
                          {versions.map((version) => (
                            <tr key={version.id}>
                              <td>{version.version}</td>
                              <td>{version.author_full_name || `Пользователь #${version.author_id}`}</td>
                              <td>{version.comment || "-"}</td>
                              <td>{new Date(version.created_at).toLocaleString("ru-RU")}</td>
                              <td>
                                {selectedDocumentCurrentVersion !== null && version.version === selectedDocumentCurrentVersion ? (
                                  <span className="text-muted">Текущая версия</span>
                                ) : canWriteSelectedDocument ? (
                                  <AppButton size="sm" variant="outline" icon={RotateCcw} onClick={() => restoreVersion(version.version)}>
                                    Восстановить
                                  </AppButton>
                                ) : (
                                  <span className="text-muted">-</span>
                                )}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </Table>
                  )}
                </div>
              </Tab>

              <Tab eventKey="access" title="Доступ">
                <div className="pt-3">
                  {!canManageSelectedDocumentAccess ? (
                    <Alert variant="light" className="mb-0">У вас нет прав на управление доступом для этого документа.</Alert>
                  ) : (
                    <Stack gap={3}>
                      {accessError ? (
                        <Alert variant="danger" className="mb-0">{accessError}</Alert>
                      ) : null}
                      <Card>
                        <Card.Body>
                          <Card.Title className="h6">Добавить пользователя</Card.Title>
                          <Form onSubmit={grantAccess} style={{ maxWidth: 520 }}>
                            <Form.Group className="mb-2 position-relative">
                              <Form.Control
                                placeholder="Введите имя или логин пользователя"
                                value={selectedUserLabel}
                                onChange={(e) => {
                                  onUserSearchChange(e.target.value);
                                  setAccessError("");
                                }}
                                onFocus={() => setShowUserSuggestions(true)}
                                onBlur={() => setTimeout(() => setShowUserSuggestions(false), 150)}
                              />
                              {showUserSuggestions && userOptions.length > 0 && (
                                <div className="sd-autocomplete-list">
                                  {userOptions.map((option) => (
                                    <button
                                      key={option.id}
                                      type="button"
                                      className="sd-autocomplete-item"
                                      onMouseDown={(event) => event.preventDefault()}
                                      onClick={() => selectUserOption(option)}
                                    >
                                      {option.full_name} ({option.login})
                                    </button>
                                  ))}
                                </div>
                              )}
                            </Form.Group>
                            <Form.Group className="mb-2">
                              <Form.Select
                                value={selectedPreset}
                                onChange={(e) => {
                                  setSelectedPreset(e.target.value);
                                  setAccessError("");
                                }}
                              >
                                {Object.entries(PERMISSION_PRESETS).map(([key, preset]) => (
                                  <option key={`grant-${key}`} value={key}>{preset.label}</option>
                                ))}
                              </Form.Select>
                            </Form.Group>
                            <AppButton type="submit" variant="outline" icon={UserPlus}>Добавить пользователя</AppButton>
                          </Form>
                        </Card.Body>
                      </Card>

                      <Card>
                        <Card.Body>
                          <Stack direction="horizontal" className="justify-content-between align-items-center mb-2">
                            <Card.Title className="h6 mb-0">Пользователи с доступом</Card.Title>
                            {selectedAclUserIds.length > 0 && (
                              <Stack direction="horizontal" gap={2} className="flex-nowrap align-items-center">
                                <Form.Select
                                  size="sm"
                                  value={bulkAclPreset}
                                  onChange={(e) => {
                                    setBulkAclPreset(e.target.value);
                                    setAccessError("");
                                  }}
                                >
                                  {Object.entries(PERMISSION_PRESETS).map(([key, preset]) => (
                                    <option key={`acl-bulk-${key}`} value={key}>{preset.label}</option>
                                  ))}
                                </Form.Select>
                                <AppButton size="sm" variant="outline" icon={Check} onClick={updateSelectedAclUsers} className="text-nowrap px-3" style={{ minWidth: 230 }}>
                                  Изменить роль выбранным
                                </AppButton>
                                <AppButton size="sm" variant="danger" icon={ShieldX} onClick={revokeSelectedAclUsers} className="text-nowrap px-3" style={{ minWidth: 310 }}>
                                  Отозвать доступ у выбранных
                                </AppButton>
                              </Stack>
                            )}
                          </Stack>
                          {aclLoading ? (
                            <Loader />
                          ) : aclRows.length === 0 ? (
                            <Alert variant="light" className="mb-0">Для документа пока нет выданных доступов.</Alert>
                          ) : (
                            <Table responsive hover>
                              <thead>
                                <tr>
                                  <th>
                                    <Form.Check
                                      type="checkbox"
                                      onChange={(e) => toggleSelectAllAcl(e.target.checked)}
                                      checked={
                                        aclRows.filter((row) => row.user_id !== selectedDocument?.owner_id).length > 0
                                        && aclRows
                                          .filter((row) => row.user_id !== selectedDocument?.owner_id)
                                          .every((row) => selectedAclUserIds.includes(row.user_id))
                                      }
                                    />
                                  </th>
                                  <th>Пользователь</th>
                                  <th style={{ width: 260 }}>Роль</th>
                                  <th style={{ width: 220 }}>Действия</th>
                                </tr>
                              </thead>
                              <tbody>
                                {aclRows.map((row) => {
                                  const isOwnerRow = row.user_id === selectedDocument.owner_id;
                                  return (
                                    <tr key={`acl-${row.user_id}`}>
                                      <td>
                                        {!isOwnerRow ? (
                                          <Form.Check
                                            type="checkbox"
                                            checked={selectedAclUserIds.includes(row.user_id)}
                                            onChange={(e) => toggleAclUserSelection(row.user_id, e.target.checked)}
                                          />
                                        ) : null}
                                      </td>
                                      <td>
                                        <div className="fw-semibold">{row.user_full_name}</div>
                                        <div className="small text-muted">{row.user_login}</div>
                                      </td>
                                      <td>
                                        {isOwnerRow ? (
                                          <div className="small fw-semibold">Владелец</div>
                                        ) : (
                                          <Form.Select
                                            size="sm"
                                            value={rowPresetByUser[row.user_id] || "reader"}
                                            onChange={(e) => {
                                              setRowPresetByUser((prev) => ({ ...prev, [row.user_id]: e.target.value }));
                                              setAccessError("");
                                            }}
                                            disabled={isOwnerRow}
                                          >
                                            {Object.entries(PERMISSION_PRESETS).map(([key, preset]) => (
                                              <option key={`acl-${row.user_id}-${key}`} value={key}>{preset.label}</option>
                                            ))}
                                          </Form.Select>
                                        )}
                                      </td>
                                      <td>
                                        {!isOwnerRow && (
                                          <Stack direction="horizontal" gap={2}>
                                            <AppButton size="sm" variant="outline" icon={Check} onClick={() => updateAccessForUser(row.user_id)}>
                                              Сохранить
                                            </AppButton>
                                            <AppButton size="sm" variant="danger" icon={ShieldX} onClick={() => revokeAccessForUser(row.user_id)} className="text-nowrap px-3" style={{ minWidth: 170 }}>
                                              Отозвать доступ
                                            </AppButton>
                                          </Stack>
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
                    </Stack>
                  )}
                </div>
              </Tab>

              <Tab eventKey="links" title="Ссылки">
                <div className="pt-3">
                  <Card className="mb-3">
                    <Card.Body>
                      <Card.Title className="h6">Создание публичной ссылки</Card.Title>
                      {linkError ? (
                        <Alert variant="danger" className="mb-3">{linkError}</Alert>
                      ) : null}
                      <Row className="g-2">
                        <Col md={5}>
                          <Form.Control
                            placeholder="Укажите название ссылки"
                            value={linkName}
                            onChange={(e) => {
                              setLinkName(e.target.value);
                              setLinkError("");
                            }}
                          />
                        </Col>
                        <Col md={4}>
                          <Form.Control
                            type="datetime-local"
                            value={linkExpiresAt}
                            isInvalid={Boolean(linkError)}
                            onChange={(e) => {
                              setLinkExpiresAt(e.target.value);
                              setLinkError("");
                            }}
                          />
                          <Form.Text>Укажите срок действия ссылки</Form.Text>
                        </Col>
                        <Col md={3}>
                          <AppButton className="w-100" variant="primary" icon={Plus} onClick={createLink}>Создать ссылку</AppButton>
                        </Col>
                      </Row>
                    </Card.Body>
                  </Card>

                  {links.length === 0 ? (
                    <Alert variant="light" className="mb-0">Публичные ссылки для документа еще не создавались.</Alert>
                  ) : (
                    <Table responsive hover>
                      <thead>
                        <tr>
                          <th>Название</th>
                          <th>Ссылка</th>
                          <th>Срок действия</th>
                          <th>Статус</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {links.map((link) => {
                          const href = buildPublicLinkUrl(link.token);
                          const revoked = Boolean(link.revoked_at);
                          const expired = !revoked && new Date(link.expires_at).getTime() <= linkStatusNow;
                          return (
                            <tr key={link.id}>
                              <td>{link.name || "Без названия"}</td>
                              <td><AppButton size="sm" variant="outline" onClick={() => copyPublicLink(href)}>Копировать</AppButton></td>
                              <td>{new Date(link.expires_at).toLocaleString("ru-RU")}</td>
                              <td>{revoked ? <Badge bg="danger">Отозвана</Badge> : expired ? <Badge bg="secondary">Истекла</Badge> : <Badge bg="success">Активна</Badge>}</td>
                              <td>
                                {!revoked && !expired && (
                                  <AppButton size="sm" variant="danger" icon={Trash2} onClick={() => revokeLink(link.id)}>
                                    Отозвать
                                  </AppButton>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </Table>
                  )}
                </div>
              </Tab>
            </Tabs>
          )}
        </Offcanvas.Body>
      </Offcanvas>

      <Modal
        show={requestModalOpen}
        onHide={() => {
          setRequestModalOpen(false);
          setRequestDocument(null);
          setRequestBulkDocIds([]);
          setRequestError("");
        }}
        centered
      >
        <Form onSubmit={submitAccessRequest}>
          <Modal.Header closeButton>
            <Modal.Title>Запрос доступа</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            {requestError ? (
              <Alert variant="danger" className="mb-3">{requestError}</Alert>
            ) : null}
            {requestDocument ? (
              <Stack gap={2}>
                <div>
                  <div className="small text-muted">Документ</div>
                  <div className="fw-semibold">{requestDocument.name}</div>
                </div>
                <Form.Group>
                  <Form.Label>Набор прав</Form.Label>
                  <Form.Select
                    value={requestPreset}
                    onChange={(e) => {
                      setRequestPreset(e.target.value);
                      setRequestError("");
                    }}
                  >
                    {Object.entries(REQUEST_PRESETS).map(([key, preset]) => (
                      <option key={`request-${key}`} value={key}>{preset.label}</option>
                    ))}
                  </Form.Select>
                </Form.Group>
                <Form.Group>
                  <Form.Label>Комментарий</Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={3}
                    value={requestComment}
                    onChange={(e) => {
                      setRequestComment(e.target.value);
                      setRequestError("");
                    }}
                    placeholder="Опишите, зачем нужен доступ (необязательно)"
                  />
                </Form.Group>
              </Stack>
            ) : requestBulkDocIds.length > 0 ? (
              <Stack gap={2}>
                <div>
                  <div className="small text-muted">Выбранные документы</div>
                  <div className="fw-semibold">{requestBulkDocIds.length} шт.</div>
                </div>
                <Form.Group>
                  <Form.Label>Набор прав</Form.Label>
                  <Form.Select
                    value={requestPreset}
                    onChange={(e) => {
                      setRequestPreset(e.target.value);
                      setRequestError("");
                    }}
                  >
                    {Object.entries(REQUEST_PRESETS).map(([key, preset]) => (
                      <option key={`request-bulk-${key}`} value={key}>{preset.label}</option>
                    ))}
                  </Form.Select>
                </Form.Group>
                <Form.Group>
                  <Form.Label>Комментарий</Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={3}
                    value={requestComment}
                    onChange={(e) => {
                      setRequestComment(e.target.value);
                      setRequestError("");
                    }}
                    placeholder="Опишите, зачем нужен доступ (необязательно)"
                  />
                </Form.Group>
              </Stack>
            ) : (
              <Alert variant="light" className="mb-0">Документ не выбран.</Alert>
            )}
          </Modal.Body>
          <Modal.Footer>
            <AppButton
              type="button"
              variant="outline"
              onClick={() => {
                setRequestModalOpen(false);
                setRequestDocument(null);
                setRequestBulkDocIds([]);
                setRequestError("");
              }}
            >
              Отмена
            </AppButton>
            <AppButton type="submit" variant="primary" disabled={!requestDocument && requestBulkDocIds.length === 0}>Отправить заявку</AppButton>
          </Modal.Footer>
        </Form>
      </Modal>

    </Stack>
  );
}



