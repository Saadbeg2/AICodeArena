import React from "react";

export default function PromptModal({ open, prompt, onClose }) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section
        className="modal-panel"
        aria-modal="true"
        role="dialog"
        aria-label="Problem prompt"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">$ cat generated.prompt</p>
            <h3>FULL_PROMPT</h3>
          </div>
          <button className="modal-close" onClick={onClose} type="button">
            [ CLOSE ]
          </button>
        </div>
        <pre>{prompt}</pre>
      </section>
    </div>
  );
}
