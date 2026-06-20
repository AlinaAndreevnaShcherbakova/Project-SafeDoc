export function getApiErrorMessage(err, fallback = "Операция не выполнена") {
  //Ответы FastAPI могут приходить строкой, списком ошибок или объектом с message.
  const detail = err?.response?.data?.detail;

  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
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

    if (messages.length > 0) {
      return messages.join(" ");
    }
  }

  if (detail && typeof detail === "object" && typeof detail.message === "string" && detail.message.trim()) {
    return detail.message;
  }

  return fallback;
}

export function getBulkProcessedCount(data) {
  if (Array.isArray(data?.processed)) {
    return data.processed.length;
  }
  if (Array.isArray(data?.created_request_ids)) {
    return data.created_request_ids.length;
  }
  return 0;
}

export function formatSkippedList(skipped = [], resolveLabel = null) {
  return skipped
    .map((item) => {
      const id = item?.id ?? item?.document_id ?? item?.request_id ?? item?.user_id;
      const label = resolveLabel ? resolveLabel(item, id) : null;
      const objectLabel = label || (id ? `ID ${id}` : "Объект");
      const reason = item?.reason || "Причина не указана";
      return `- ${objectLabel}: ${reason}`;
    })
    .join("\n");
}

export function buildBulkResultMessage(data, resolveLabel = null) {
  //Единый формат нужен для массовых операций с частично выполненным результатом.
  const processedCount = getBulkProcessedCount(data);
  const skipped = Array.isArray(data?.skipped) ? data.skipped : [];

  if (skipped.length === 0) {
    return { status: "success", processedCount, message: "" };
  }

  const skippedText = formatSkippedList(skipped, resolveLabel);

  if (processedCount > 0) {
    return {
      status: "partial",
      processedCount,
      message: `Операция выполнена частично.\nНе удалось обработать:\n${skippedText}`,
    };
  }

  return {
    status: "failed",
    processedCount,
    message: `Операция не выполнена.\nНе удалось обработать:\n${skippedText}`,
  };
}
