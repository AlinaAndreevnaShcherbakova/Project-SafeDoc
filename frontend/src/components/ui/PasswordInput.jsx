import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import InputGroup from "react-bootstrap/InputGroup";
import { Eye, EyeOff } from "lucide-react";

export default function PasswordInput({ disabled = false, ...props }) {
  const [visible, setVisible] = useState(false);
  const Icon = visible ? EyeOff : Eye;
  const label = visible ? "Скрыть пароль" : "Показать пароль";

  return (
    <InputGroup>
      <Form.Control {...props} type={visible ? "text" : "password"} disabled={disabled} />
      <Button
        type="button"
        variant="outline-secondary"
        className="sd-password-toggle"
        onClick={() => setVisible((current) => !current)}
        disabled={disabled}
        aria-label={label}
        title={label}
      >
        <Icon size={18} strokeWidth={1.8} />
      </Button>
    </InputGroup>
  );
}
