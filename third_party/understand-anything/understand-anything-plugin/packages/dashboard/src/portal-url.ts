export function currentProjectId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("project");
}

export function runtimeUrl(
  pathname: string,
  token: string | null,
  params: Record<string, string> = {},
): string {
  const query = new URLSearchParams(params);
  const project = currentProjectId();
  if (token) query.set("token", token);
  if (project) query.set("project", project);
  const encoded = query.toString();
  return encoded ? `${pathname}?${encoded}` : pathname;
}
