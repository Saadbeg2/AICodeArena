import React from "react";

export default function ActionButton({
  children,
  loading,
  onClick,
  variant = "primary",
  disabled = false,
  ...buttonProps
}) {
  return (
    <button
      className={`action-button ${variant}`}
      disabled={loading || disabled}
      onClick={onClick}
      type="button"
      {...buttonProps}
    >
      {loading ? "[ RUNNING... ]" : children}
    </button>
  );
}
