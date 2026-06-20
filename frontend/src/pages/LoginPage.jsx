import React, { useEffect, useMemo, useState } from "react";
import Alert from "react-bootstrap/Alert";
import Card from "react-bootstrap/Card";
import Col from "react-bootstrap/Col";
import Container from "react-bootstrap/Container";
import Form from "react-bootstrap/Form";
import Row from "react-bootstrap/Row";
import { LogIn } from "lucide-react";

import AppButton from "../components/ui/AppButton";
import PasswordInput from "../components/ui/PasswordInput";
import { useAuth } from "../context/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const [loginValue, setLoginValue] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [lockRemainingSeconds, setLockRemainingSeconds] = useState(null);

  const isLocked = lockRemainingSeconds !== null && lockRemainingSeconds > 0;
  const lockLabel = useMemo(() => {
    if (!isLocked) {
      return "";
    }
    const total = Number(lockRemainingSeconds) || 0;
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }, [isLocked, lockRemainingSeconds]);

  useEffect(() => {
    if (!isLocked) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setLockRemainingSeconds((prev) => {
        if (prev === null) {
          return null;
        }
        if (prev <= 1) {
          return null;
        }
        return prev - 1;
      });
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isLocked]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (isLocked) {
      return;
    }
    setError("");
    setSubmitting(true);

    try {
      await login(loginValue, password);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 423 && typeof detail === "object" && detail !== null) {
        const nextSeconds = Number(detail.remaining_seconds);
        if (Number.isFinite(nextSeconds) && nextSeconds > 0) {
          setLockRemainingSeconds(Math.ceil(nextSeconds));
        }
        setError(detail.message || "Форма входа временно заблокирована");
      } else {
        setError(typeof detail === "string" ? detail : "Ошибка входа");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Container className="py-5">
      <Row className="justify-content-center">
        <Col md={6} lg={4}>
          <Card>
            <Card.Body>
              <h4 className="mb-3">Вход в SafeDoc</h4>
              {error && <Alert variant="danger">{error}</Alert>}
              {isLocked && (
                <Alert variant="warning">
                  Форма входа заблокирована. Повторите попытку через {lockLabel}.
                </Alert>
              )}
              <Form onSubmit={handleSubmit}>
                <Form.Group className="mb-3">
                  <Form.Label>Логин</Form.Label>
                  <Form.Control value={loginValue} onChange={(e) => setLoginValue(e.target.value)} required disabled={isLocked || submitting} />
                </Form.Group>
                <Form.Group className="mb-3">
                  <Form.Label>Пароль</Form.Label>
                  <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} required disabled={isLocked || submitting} />
                </Form.Group>
                <AppButton type="submit" disabled={submitting || isLocked} className="w-100" variant="primary" icon={LogIn}>
                  {submitting ? "Входим..." : "Войти"}
                </AppButton>
              </Form>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  );
}

