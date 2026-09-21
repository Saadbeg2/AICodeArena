import React from "react";

export default function LoadingPanel({ title, message }) {
  return (
    <section className="panel detail-panel loading-state" aria-live="polite">
      <div className="loading-indicator" />
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
      </div>
    </section>
  );
}
