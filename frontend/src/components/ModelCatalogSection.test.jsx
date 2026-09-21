import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ModelCatalogSection from "./ModelCatalogSection";

const models = [
  {
    id: "openrouter:openai/gpt-oss-20b:free",
    display_name: "GPT OSS 20B",
    provider: "openrouter",
    model_creator: "OpenAI",
    api_provider: "OpenRouter",
    description:
      "OpenAI's open-weight GPT-OSS 20B model designed for coding, reasoning, and general instruction following. Accessed through OpenRouter's free model routing infrastructure.",
    provider_type: "model_router",
  },
  {
    id: "openrouter:cohere/north-mini-code:free",
    display_name: "North Mini Code",
    provider: "openrouter",
    model_creator: "Cohere",
    api_provider: "OpenRouter",
    description:
      "Cohere's specialized coding model built for code generation, software engineering, agentic development workflows, and repository-level programming tasks.",
    provider_type: "model_router",
  },
  {
    id: "openrouter:poolside/laguna-s-2.1:free",
    display_name: "Laguna S 2.1",
    provider: "openrouter",
    model_creator: "Poolside",
    api_provider: "OpenRouter",
    description:
      "Poolside's coding-focused model designed for software engineering, complex code generation, repository understanding, and agentic development tasks.",
    provider_type: "model_router",
  },
  {
    id: "openrouter:google/gemma-4-31b-it:free",
    display_name: "Gemma 4 31B IT",
    provider: "openrouter",
    model_creator: "Google",
    api_provider: "OpenRouter",
    description:
      "Google's instruction-tuned Gemma 4 31B model offering strong reasoning, multilingual support, long-context understanding, and competitive programming capability.",
    provider_type: "model_router",
  },
  {
    id: "openrouter:inclusionai/ling-3.0-flash:free",
    display_name: "Ling 3.0 Flash",
    provider: "openrouter",
    model_creator: "Inclusion AI",
    api_provider: "OpenRouter",
    description:
      "Inclusion AI's Mixture-of-Experts model focused on fast inference, efficient token usage, general reasoning, and strong programming performance.",
    provider_type: "model_router",
  },
  {
    id: "groq:llama-3.3-70b-versatile",
    display_name: "Groq Llama 3.3 70B Versatile",
    provider: "groq",
    model_creator: "Meta",
    api_provider: "Groq",
    description:
      "Meta's 70-billion-parameter Llama 3.3 model served through Groq's low-latency inference platform. Designed for strong instruction following, reasoning, and code generation.",
    provider_type: "direct_provider",
  },
  {
    id: "openrouter:example/unknown-model:free",
    display_name: "Unknown Model",
    provider: "openrouter",
    model_creator: "Example",
    api_provider: "OpenRouter",
    description: "No description available.",
    provider_type: "model_router",
  },
];

describe("ModelCatalogSection", () => {
  it("renders curated model descriptions", () => {
    render(<ModelCatalogSection loading={false} models={models} />);

    expect(screen.getByText(/open-weight GPT-OSS 20B model/i)).toBeInTheDocument();
    expect(screen.getByText(/specialized coding model/i)).toBeInTheDocument();
    expect(screen.getByText(/coding-focused model/i)).toBeInTheDocument();
    expect(screen.getByText(/Gemma 4 31B model/i)).toBeInTheDocument();
    expect(screen.getByText(/Mixture-of-Experts model/i)).toBeInTheDocument();
  });

  it("renders fallback description for unknown models", () => {
    render(<ModelCatalogSection loading={false} models={models} />);

    expect(screen.getAllByText("No description available.").length).toBeGreaterThan(0);
  });

  it("renders user-friendly labels and standardized provider badges", () => {
    render(<ModelCatalogSection loading={false} models={models} />);

    expect(screen.getAllByText("CREATOR").length).toBeGreaterThan(0);
    expect(screen.getAllByText("HOSTED VIA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PROVIDER TYPE").length).toBeGreaterThan(0);
    expect(screen.getAllByText("[DIRECT PROVIDER]").length).toBeGreaterThan(0);
    expect(screen.getAllByText("[MODEL ROUTER]").length).toBeGreaterThan(0);
  });

  it("keeps the full long model id visible", () => {
    render(<ModelCatalogSection loading={false} models={models} />);

    expect(screen.getAllByText("openrouter:openai/gpt-oss-20b:free").length).toBeGreaterThan(0);
  });
});
