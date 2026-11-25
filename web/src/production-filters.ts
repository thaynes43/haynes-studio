export type ProductionFilters = {
  publication?: "published" | "unpublished";
  approved?: true;
};

export function readProductionFilters(value: unknown): ProductionFilters {
  if (!value || typeof value !== "object") return {};
  const filters: ProductionFilters = {};
  if ("publication" in value && (value.publication === "published" || value.publication === "unpublished")) {
    filters.publication = value.publication;
  }
  if ("approved" in value && value.approved === true) filters.approved = true;
  return filters;
}

export function toggleProductionFilter(
  filters: ProductionFilters, filter: "published" | "unpublished" | "approved",
): ProductionFilters {
  return readProductionFilters(filter === "approved"
    ? { ...filters, approved: !filters.approved }
    : { ...filters, publication: filters.publication === filter ? undefined : filter });
}
