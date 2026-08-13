import { useEffect, useState } from "react";
import { ArrowLeft, BookOpen, Layers3, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { SkillsCatalog as SkillsCatalogValue } from "../types/domain";

export function SkillsCatalog({ onBackToChat }: { onBackToChat: () => void }) {
  const [catalog, setCatalog] = useState<SkillsCatalogValue | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api.listSkills(controller.signal)
      .then(setCatalog)
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFailed(true);
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="skills-catalog-page" aria-label="Skills catalog">
      <header className="skills-page-header">
        <button onClick={onBackToChat} aria-label="Back to chat">
          <ArrowLeft size={17} />
          Back to chat
        </button>
        <span className="skills-page-eyebrow">Procedural memory</span>
        <h1>Skills</h1>
        <p>
          Klara sees this compact catalog first and loads one procedure only
          when it is relevant. Skill text never expands runtime permissions.
        </p>
      </header>
      {failed ? (
        <section className="skills-empty" role="alert">
          The Skill catalog is unavailable. Chat remains usable without it.
        </section>
      ) : !catalog ? (
        <section className="skills-empty" aria-live="polite">Loading Skills…</section>
      ) : (
        <>
          <section className="skills-contract" aria-label="Skill loading contract">
            <span><Layers3 size={16} />{catalog.precedence.join(" → ")} precedence</span>
            <span><BookOpen size={16} />Bodies load on demand</span>
            <span><ShieldCheck size={16} />Permissions fail closed</span>
          </section>
          <section className="skills-grid" aria-label="Available Skills">
            {catalog.skills.map((skill) => (
              <article className="skill-card" key={skill.name}>
                <header>
                  <span className={`skill-scope is-${skill.scope}`}>{formatScope(skill.scope)}</span>
                  <small>v{skill.version}</small>
                </header>
                <h2>{skill.name}</h2>
                <p>{skill.description}</p>
                <dl>
                  <div><dt>Tools</dt><dd>{skill.tools.length ? skill.tools.join(", ") : "None"}</dd></div>
                  <div><dt>Permissions</dt><dd>{skill.permissions.length ? skill.permissions.join(", ") : "None"}</dd></div>
                  <div><dt>References</dt><dd>{skill.references.length}</dd></div>
                </dl>
                {skill.shadowed_scopes.length ? (
                  <small className="skill-shadowed">Overrides {skill.shadowed_scopes.join(", ")}</small>
                ) : null}
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  );
}

function formatScope(scope: "built_in" | "user" | "project") {
  if (scope === "built_in") return "Built-in";
  return scope[0].toUpperCase() + scope.slice(1);
}
