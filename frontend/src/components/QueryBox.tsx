import { useState, type FormEvent } from "react";
import type { QuestionResponse } from "../types/twin";
import { askQuestion } from "../lib/api";

interface Props {
  sessionId: string;
}

export default function QueryBox({ sessionId }: Props) {
  const [question, setQuestion] = useState("");
  const [response, setResponse] = useState<QuestionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await askQuestion(sessionId, question);
      setResponse(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResponse(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h3>Ask a question</h3>
      <form onSubmit={handleSubmit} className="query-form">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What is the room height?"
        />
        <button type="submit" disabled={loading}>
          {loading ? "Asking..." : "Ask"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {response && (
        <div className="query-response">
          {response.supported ? (
            <pre>{JSON.stringify(response.answer, null, 2)}</pre>
          ) : (
            <div>
              <p className="not-measurable">{response.message ?? "Unsupported question."}</p>
              {response.supported_question_types && (
                <>
                  <p className="muted">Supported questions:</p>
                  <ul>
                    {response.supported_question_types.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
