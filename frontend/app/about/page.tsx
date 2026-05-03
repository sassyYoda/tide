export default function AboutPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-12">
      <h1 className="font-display text-3xl text-tide-high">About Tide</h1>
      <p className="mt-4 text-stone-700">
        Tide fuses live NOAA and Open-Meteo conditions with a per-species XGBoost
        activity model and a RAG corpus of NJ saltwater fishing reports, all
        orchestrated by a 4-node LangGraph agent and traced via Langfuse.
      </p>
      <ul className="mt-6 list-disc pl-5 text-stone-700">
        <li>MVP scope: NJ saltwater, 5 species (striper, fluke, bluefish, weakfish, tautog).</li>
        <li>
          <a className="text-tide-high underline" href="https://github.com">
            GitHub repo
          </a>{" "}
          (link finalized in Plan 08)
        </li>
        <li>
          <a className="text-tide-high underline" href="https://langfuse.com">
            Langfuse public trace
          </a>{" "}
          (link finalized in Plan 08)
        </li>
      </ul>
    </main>
  )
}
