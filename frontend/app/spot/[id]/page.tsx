export default async function SpotDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<{ shap?: string; cite?: string }>
}) {
  const { id } = await params
  const { shap, cite } = await searchParams
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="font-display text-3xl text-tide-high">Spot #{id}</h1>
      <p className="text-stone-500">
        Detail panel lands in Plan 05. shap={shap ?? "—"}, cite={cite ?? "—"}
      </p>
    </main>
  )
}
