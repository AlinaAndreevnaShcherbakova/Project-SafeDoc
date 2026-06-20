import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import Toast from "react-bootstrap/Toast";
import ToastContainer from "react-bootstrap/ToastContainer";

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);

  const pushToast = useCallback((message, variant = "success") => {
    const id = `${Date.now()}-${Math.random()}`;
    setItems((prev) => [...prev, { id, message, variant }]);
  }, []);

  const removeToast = useCallback((id) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const value = useMemo(
    () => ({
      success(message) {
        pushToast(message, "success");
      },
      error(message) {
        pushToast(message, "danger");
      },
      info(message) {
        pushToast(message, "info");
      },
    }),
    [pushToast]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer position="bottom-end" className="p-3" style={{ zIndex: 2000 }}>
        {items.map((item) => (
          <Toast
            key={item.id}
            onClose={() => removeToast(item.id)}
            bg={item.variant}
            delay={3500}
            autohide
          >
            <Toast.Body className="text-white">{item.message}</Toast.Body>
          </Toast>
        ))}
      </ToastContainer>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return context;
}

