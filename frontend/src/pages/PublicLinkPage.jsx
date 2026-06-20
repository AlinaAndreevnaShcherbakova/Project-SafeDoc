import React from "react";
import { useParams } from "react-router-dom";

function buildPublicLinkUrl(token) {
  return `/api/links/public/${token}`;
}

export default function PublicLinkPage() {
  const { token } = useParams();

  if (!token) {
    return null;
  }

  return (
    <iframe
      src={buildPublicLinkUrl(token)}
      title="Публичный просмотр документа"
      style={{ border: 0, width: "100vw", height: "100vh", display: "block" }}
      referrerPolicy="no-referrer"
    />
  );
}
