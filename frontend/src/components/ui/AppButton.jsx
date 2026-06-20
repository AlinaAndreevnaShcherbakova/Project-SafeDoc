import React from "react";
import RBButton from "react-bootstrap/Button";

export default function AppButton({
  variant = "outline",
  size = "md",
  icon: Icon,
  children,
  className = "",
  ...props
}) {
  const classes = [
    "sd-btn",
    `sd-btn-${variant}`,
    size === "sm" ? "sd-btn-sm" : "",
    !children ? "sd-btn-icon-only" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <RBButton {...props} className={classes}>
      {Icon ? <Icon size={17} strokeWidth={1.8} className="sd-btn-icon" /> : null}
      {children ? <span>{children}</span> : null}
    </RBButton>
  );
}

