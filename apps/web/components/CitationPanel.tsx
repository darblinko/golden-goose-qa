"use client";

import type { Citation } from "@/lib/types";

function CitationItem({
  citation,
  marker,
  highlighted,
}: {
  citation: Citation;
  marker: number;
  highlighted: boolean;
}) {
  return (
    <div className={`citation-item${highlighted ? " highlight" : ""}`}>
      <div>
        <span className="ref">[{marker}]</span>
        <span className="cite-title">{citation.citation}</span>
      </div>
      <div className="cite-meta">
        {[
          citation.doc_type,
          citation.section_path,
          citation.page != null ? `p. ${citation.page}` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
    </div>
  );
}

export default function CitationPanel({
  citations,
  highlightMarker,
}: {
  citations: Citation[];
  highlightMarker: number | null;
}) {
  const withMarkers = citations.map((citation, index) => ({
    citation,
    marker: citation.marker ?? index + 1,
  }));
  const internal = withMarkers.filter(
    ({ citation }) => citation.provenance !== "external",
  );
  const external = withMarkers.filter(
    ({ citation }) => citation.provenance === "external",
  );

  return (
    <aside className="citation-panel">
      <div className="citation-panel-header">Sources</div>
      {citations.length === 0 ? (
        <div className="citation-empty">
          Citations for the current answer appear here.
        </div>
      ) : (
        <>
          {internal.map(({ citation, marker }, index) => (
            <CitationItem
              key={`internal-${marker}-${index}`}
              citation={citation}
              marker={marker}
              highlighted={marker === highlightMarker}
            />
          ))}
          {external.length > 0 && (
            <>
              <div className="citation-panel-header external-header">
                External sources (not QMS evidence)
              </div>
              {external.map(({ citation, marker }, index) => (
                <CitationItem
                  key={`external-${marker}-${index}`}
                  citation={citation}
                  marker={marker}
                  highlighted={marker === highlightMarker}
                />
              ))}
            </>
          )}
        </>
      )}
    </aside>
  );
}
