import createClient from "openapi-fetch";
import type { ApprovalReviewPaths } from "../approval-review-contract";
import type { components, paths } from "./schema";

const safeMethods = new Set(["GET", "HEAD", "OPTIONS"]);
type StudioPaths = Omit<paths, keyof ApprovalReviewPaths> & {
  [Path in keyof ApprovalReviewPaths]: Omit<paths[Path], "get"> & ApprovalReviewPaths[Path];
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code?: string,
    public readonly requestId?: string,
    public readonly detail?: Partial<Pick<components["schemas"]["ErrorDetail"], "message" | "path" | "board_id" | "evidence">>,
  ) {
    super(`Studio request failed (${status})`);
  }

  static async fromResponse(response: Response) {
    const body: Partial<components["schemas"]["ErrorEnvelope"]> | null =
      await response.json().catch(() => null);
    const detail = body?.error;
    const requestId = detail?.request_id;
    return new ApiError(
      response.status,
      typeof detail?.code === "string" ? detail.code : undefined,
      typeof requestId === "string" && /^[\w-]{1,128}$/.test(requestId) ? requestId : undefined,
      detail && {
        message: typeof detail.message === "string" ? detail.message : undefined,
        path: typeof detail.path === "string" ? detail.path : undefined,
        board_id: typeof detail.board_id === "string" ? detail.board_id : undefined,
        evidence: detail.evidence,
      },
    );
  }
}

export function createStudioApi(
  origin: string,
  signal: AbortSignal,
  onUnauthorized: () => void,
  send: typeof fetch = globalThis.fetch.bind(globalThis),
) {
  let csrf: string | undefined;
  const client = createClient<StudioPaths>({
    baseUrl: origin,
    async fetch(request) {
      if (new URL(request.url).origin !== origin) throw new ApiError(403, "auth.origin");
      request.headers.delete("Authorization");
      request.headers.delete("X-Studio-CSRF");
      if (!safeMethods.has(request.method)) {
        if (!csrf) throw new ApiError(403, "auth.csrf");
        request.headers.set("X-Studio-CSRF", csrf);
      }

      const requestSignal = AbortSignal.any([signal, request.signal]);
      let response: Response;
      try {
        response = await send(new Request(request, {
          signal: requestSignal,
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
        }));
      } catch (error) {
        if (requestSignal.aborted) throw error;
        throw new ApiError(0);
      }
      if (response.status === 401 && !requestSignal.aborted) {
        csrf = undefined;
        onUnauthorized();
      }
      if (!response.ok) throw await ApiError.fromResponse(response);
      return response;
    },
  });

  return {
    client,
    async connect() {
      csrf = undefined;
      const { data } = await client.GET("/v1/me");
      if (!data || data.principal?.kind !== "human" || !data.principal.iss ||
          !data.principal.sub || typeof data.csrf_token !== "string" || !data.csrf_token) {
        throw new ApiError(403, "auth.human_required");
      }
      csrf = data.csrf_token;
      return { displayName: data.display_name?.trim() || "Account" };
    },
    async signOut() {
      await client.POST("/auth/logout");
      csrf = undefined;
    },
  };
}

export type StudioClient = ReturnType<typeof createStudioApi>["client"];
