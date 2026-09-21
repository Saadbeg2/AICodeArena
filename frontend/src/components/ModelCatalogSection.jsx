import React from "react";

function formatProviderType(value = "") {
  return String(value || "unknown").replace(/_/g, " ").toUpperCase();
}

export default function ModelCatalogSection({ loading, models }) {
  return (
    <section className="content-section">
      <p className="eyebrow">$ cat ./models/catalog.json</p>
      <h3>MODEL INFO</h3>
      {loading ? (
        <p className="muted">Loading model catalog…</p>
      ) : models.length ? (
        <div className="model-info-grid">
          {models.map((model) => (
            <article className="model-info-card" key={model.id}>
              <div className="section-heading compact model-card-header">
                <div>
                  <p className="eyebrow">$ model --inspect {model.provider}</p>
                  <h4 className="model-card-title">{model.display_name}</h4>
                </div>
                <span className="badge neutral model-provider-badge">
                  [{formatProviderType(model.provider_type)}]
                </span>
              </div>

              <dl className="detail-facts detail-facts-stacked model-card-facts">
                <div className="model-card-field">
                  <dt>MODEL ID</dt>
                  <dd className="model-id-value">{model.id}</dd>
                </div>
                <div className="model-card-field">
                  <dt>CREATOR</dt>
                  <dd>{model.model_creator || "—"}</dd>
                </div>
                <div className="model-card-field">
                  <dt>HOSTED VIA</dt>
                  <dd>{model.api_provider || model.provider || "—"}</dd>
                </div>
                <div className="model-card-field">
                  <dt>PROVIDER TYPE</dt>
                  <dd>{formatProviderType(model.provider_type)}</dd>
                </div>
              </dl>

              <div className="model-description-block">
                <p className="model-description-label">DESCRIPTION</p>
                <p className="model-description">
                  {model.description || "No description available."}
                </p>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted">&gt; No models were returned by /models.</p>
      )}
    </section>
  );
}
